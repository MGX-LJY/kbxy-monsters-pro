# server/app/routes/warehouse.py
from __future__ import annotations

from typing import Optional, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from pydantic import BaseModel

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, desc, asc

from ..db import SessionLocal
from ..models import Monster, MonsterSkill, Tag, CollectionItem
from ..schemas import MonsterOut, MonsterList
from ..services.warehouse_service import (
    add_to_warehouse, remove_from_warehouse, bulk_set_warehouse,
    list_warehouse, warehouse_stats,
)
# ⬇️ 新增：图片解析器（若未引入图片服务，可去掉两行 import 和下文 img_url 相关三行）
from ..services.image_service import get_image_resolver

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# 旧→新派生键兜底（与前端保持一致）
LEGACY_FALLBACK = {
    "body_defense": "survive",
    "special_tactics": "pp_pressure",
    # 如还有其它旧键→新键关系，可继续补
}


def pick_derived_value(d: dict, key: str):
    """取派生值：优先新键；没有则用旧键兜底；返回 None 表示无值。"""
    if not isinstance(d, dict):
        return None
    v = d.get(key, None)
    if isinstance(v, (int, float)):
        return float(v)
    legacy = LEGACY_FALLBACK.get(key)
    if legacy is not None:
        lv = d.get(legacy)
        if isinstance(lv, (int, float)):
            return float(lv)
    return None


def compute_derived_out(monster) -> dict:
    """Derived stats functionality has been removed."""
    return {}


def enrich_new_keys(d: dict) -> dict:
    """把缺失的新键补出来，便于前端直接读取。"""
    out = dict(d or {})
    for newk, oldk in LEGACY_FALLBACK.items():
        if newk not in out and isinstance(out.get(oldk), (int, float)):
            out[newk] = out[oldk]
    return out


def sort_key_for(val: Optional[float], mid: int, is_asc: bool):
    """
    生成排序 key：
      - 升序：NULLS FIRST
      - 降序：NULLS LAST
      - 同值按 id ASC
    统一用“升序排序”，不使用 reverse 以避免 NULL 行为出错。
    """
    if val is None:
        # 升序时放前，降序时放后
        return (0, 0.0, mid) if is_asc else (1, 0.0, mid)
    else:
        return (1, float(val), mid) if is_asc else (0, -float(val), mid)


# ---- 列表（拥有过滤：possess=True/False/None）----
@router.get("/warehouse", response_model=MonsterList)
def warehouse_list(
    possess: Optional[bool] = Query(True, description="True=仅已拥有；False=仅未拥有；None=全部"),
    q: Optional[str] = Query(None),
    element: Optional[str] = Query(None),
    role: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    # 多标签 AND + 获取渠道（兼容两个参数名）
    tags_all: Optional[List[str]] = Query(None),
    type: Optional[str] = Query(None),
    acq_type: Optional[str] = Query(None),
    # ✅ 收藏分组筛选
    collection_id: Optional[int] = Query(None, description="收藏分组 ID"),
    # ✅ 排序：支持新五轴 + 六维 + 六维总和 + 基础列
    sort: Optional[str] = Query("updated_at"),
    order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    支持参数：
    - possess: True 仅已拥有；False 仅未拥有（含 None）；None 全部
    - q / element / role
    - tag（单标签）、tags_all（AND 多标签）
    - acq_type / type（获取途径，包含匹配）
    - collection_id：按收藏分组过滤
    - sort：
        * 新五轴：body_defense / body_resist / debuff_def_res / debuff_atk_mag / special_tactics
        * 六维：hp/speed/attack/defense/magic/resist
        * 六维总和：raw_sum
        * 基础：updated_at / created_at / name / element / role
    """
    s_key = (sort or "updated_at").lower()
    is_asc = (order or "desc").lower() == "asc"

    DERIVED_KEYS = {"body_defense", "body_resist", "debuff_def_res", "debuff_atk_mag", "special_tactics"}
    RAW_MAP = {
        "hp": Monster.hp,
        "speed": Monster.speed,
        "attack": Monster.attack,
        "defense": Monster.defense,
        "magic": Monster.magic,
        "resist": Monster.resist,
    }
    raw_sum_expr = (
        func.coalesce(Monster.hp, 0)
        + func.coalesce(Monster.speed, 0)
        + func.coalesce(Monster.attack, 0)
        + func.coalesce(Monster.defense, 0)
        + func.coalesce(Monster.magic, 0)
        + func.coalesce(Monster.resist, 0)
    )

    # ---------- 构建基础过滤 ----------
    base_q = db.query(Monster)

    # possess 过滤
    if possess is True:
        base_q = base_q.filter(Monster.possess.is_(True))
    elif possess is False:
        base_q = base_q.filter(or_(Monster.possess.is_(False), Monster.possess.is_(None)))

    # 收藏分组
    if collection_id is not None:
        base_q = (
            base_q.join(CollectionItem, CollectionItem.monster_id == Monster.id)
                  .filter(CollectionItem.collection_id == int(collection_id))
                  .distinct(Monster.id)
        )

    # 基础筛选
    if q:
        like = f"%{q.strip()}%"
        base_q = base_q.filter(Monster.name.ilike(like))
    if element:
        base_q = base_q.filter(Monster.element == element)
    if role:
        base_q = base_q.filter(Monster.role == role)

    # 标签筛选
    if tags_all:
        for t in tags_all:
            if t:
                base_q = base_q.filter(Monster.tags.any(Tag.name == t))
    if tag:
        base_q = base_q.filter(Monster.tags.any(Tag.name == tag))

    # 获取途径（包含匹配）
    acq = (acq_type or type or "").strip()
    if acq:
        base_q = base_q.filter(Monster.type.ilike(f"%{acq}%"))

    # 先拿总数（和数据行同条件）
    total = base_q.order_by(None).count()

    # ---------- 排序 ----------
    if s_key in DERIVED_KEYS:
        # —— 派生五维：固定走内存排序（保证稳定且有旧键兜底）——
        id_rows = base_q.with_entities(Monster.id).all()
        id_list = [r[0] for r in id_rows]

        items: List[Monster] = []
        if id_list:
            ms = (
                db.query(Monster)
                  .filter(Monster.id.in_(id_list))
                  .options(
                      selectinload(Monster.tags),
                      selectinload(Monster.derived),
                      selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
                  )
                  .all()
            )
            m_map = {m.id: m for m in ms}

            scored: List[Tuple[tuple, int]] = []
            for mid in id_list:
                m = m_map.get(mid)
                if not m:
                    continue
                d = compute_derived_out(m) or {}
                val = pick_derived_value(d, s_key)
                scored.append((sort_key_for(val, mid, is_asc), mid))

            scored.sort(key=lambda x: x[0])  # 统一升序 key（含 NULLS FIRST/LAST 语义）

            start = (page - 1) * page_size
            end = start + page_size
            page_ids = [mid for _, mid in scored[start:end]]
            items = [m_map[mid] for mid in page_ids if mid in m_map]

    elif s_key == "raw_sum":
        q_sorted = base_q.order_by(asc(raw_sum_expr) if is_asc else desc(raw_sum_expr), Monster.id.asc())
        items = q_sorted.offset((page - 1) * page_size).limit(page_size).all()

    elif s_key in RAW_MAP:
        col = RAW_MAP[s_key]
        q_sorted = base_q.order_by(asc(col) if is_asc else desc(col), Monster.id.asc())
        items = q_sorted.offset((page - 1) * page_size).limit(page_size).all()

    elif s_key in {"name", "element", "role", "created_at", "updated_at"}:
        col = getattr(Monster, s_key)
        q_sorted = base_q.order_by(asc(col) if is_asc else desc(col), Monster.id.asc())
        items = q_sorted.offset((page - 1) * page_size).limit(page_size).all()

    else:
        q_sorted = base_q.order_by(Monster.updated_at.desc(), Monster.id.asc())
        items = q_sorted.offset((page - 1) * page_size).limit(page_size).all()

    # 预加载（避免 N+1；上面派生分支已预加载，这里补全其它分支）
    ids = [m.id for m in items]
    if ids:
        _ = db.execute(
            select(Monster)
            .where(Monster.id.in_(ids))
            .options(
                selectinload(Monster.tags),
                selectinload(Monster.derived),
                selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            )
        ).scalars().all()

    # 图片解析器（可选）
    img_resolver = get_image_resolver()

    # 输出
    out = []
    for m in items:
        d_raw = compute_derived_out(m) or {}
        d = enrich_new_keys(d_raw)

        # 可选：为每条记录解析图片 URL
        img_url = img_resolver.resolve_by_names([
            m.name,
            getattr(m, "name_final", None),
            getattr(m, "alias", None),
        ])

        out.append(
            MonsterOut(
                id=m.id,
                name=m.name,
                element=m.element,
                role=m.role,
                hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
                possess=getattr(m, "possess", None),
                new_type=getattr(m, "new_type", None),
                type=getattr(m, "type", None),
                method=getattr(m, "method", None),
                tags=[t.name for t in (m.tags or [])],
                explain_json=m.explain_json or {},
                created_at=getattr(m, "created_at", None),
                updated_at=getattr(m, "updated_at", None),
                derived=d,
                # 若 MonsterOut 未添加 image_url 字段，这里会被忽略；若已添加则直接输出
                image_url=img_url,
            )
        )

    etag = f'W/"warehouse:{total}:{possess}:{collection_id or ""}"'
    return {
        "items": out,
        "total": total,
        "has_more": page * page_size < total,
        "etag": etag,
    }


# ---- 入参模型 ----
class IdIn(BaseModel):
    id: int


class BulkSetIn(BaseModel):
    ids: List[int]
    possess: bool = True


# ---- 单个加入仓库 ----
@router.post("/warehouse/add")
def api_add_to_warehouse(payload: IdIn = Body(...), db: Session = Depends(get_db)):
    ok = add_to_warehouse(db, payload.id)
    if not ok:
        raise HTTPException(status_code=404, detail="monster not found")
    db.commit()
    return {"ok": True, "id": payload.id}


# ---- 单个移出仓库 ----
@router.post("/warehouse/remove")
def api_remove_from_warehouse(payload: IdIn = Body(...), db: Session = Depends(get_db)):
    ok = remove_from_warehouse(db, payload.id)
    if not ok:
        raise HTTPException(status_code=404, detail="monster not found")
    db.commit()
    return {"ok": True, "id": payload.id}


# ---- 批量设置（加入/移出）----
@router.post("/warehouse/bulk_set")
def api_bulk_set(payload: BulkSetIn = Body(...), db: Session = Depends(get_db)):
    n = bulk_set_warehouse(db, payload.ids, payload.possess)
    db.commit()
    return {"ok": True, "affected": n}


# ---- 仓库统计 ----
@router.get("/warehouse/stats")
def api_warehouse_stats(db: Session = Depends(get_db)):
    # 返回 {total, owned_total, not_owned_total, in_warehouse}
    return warehouse_stats(db)