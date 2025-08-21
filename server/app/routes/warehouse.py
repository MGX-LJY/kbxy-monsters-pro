# server/app/routes/warehouse.py
from __future__ import annotations

from typing import Optional, List, Tuple

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from pydantic import BaseModel

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, and_

from ..db import SessionLocal
from ..models import Monster, MonsterSkill, Tag, CollectionItem
from ..schemas import MonsterOut, MonsterList
from ..services.warehouse_service import (
    add_to_warehouse, remove_from_warehouse, bulk_set_warehouse,
    list_warehouse, warehouse_stats,
)
from ..services.derive_service import compute_derived_out

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


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
    # ✅ 新增：收藏分组筛选
    collection_id: Optional[int] = Query(None, description="收藏分组 ID"),
    sort: Optional[str] = Query("updated_at"),
    order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    支持参数：
    - possess: True 仅已拥有；False 仅未拥有（含 None）；None 全部
    - q/element/role
    - tag（单标签）、tags_all（AND 多标签）
    - acq_type / type（获取途径，包含匹配）
    - collection_id：按收藏分组过滤
    - sort：updated_at / raw_sum / 六维字段（hp/speed/attack/defense/magic/resist）
    """
    # —— 优先调用 service；若未适配 collection_id 等新参，则回退到本地实现 —— #
    try:
        items, total = list_warehouse(
            db,
            possess=possess,
            q=q,
            element=element,
            role=role,
            tag=tag,
            tags_all=tags_all,
            type=type,
            acq_type=acq_type,
            collection_id=collection_id,          # 新增透传
            sort=sort or "updated_at",
            order=order or "desc",
            page=page,
            page_size=page_size,
        )
    except TypeError:
        # ---------- 本地回退实现 ----------
        page = max(1, int(page))
        page_size = min(200, max(1, int(page_size)))

        query = db.query(Monster)

        # possess 过滤
        if possess is True:
            query = query.filter(Monster.possess.is_(True))
        elif possess is False:
            # 将未拥有定义为 False 或 None
            query = query.filter(or_(Monster.possess.is_(False), Monster.possess.is_(None)))

        # 按收藏分组过滤（JOIN + DISTINCT 防重复）
        if collection_id is not None:
            query = (
                query.join(CollectionItem, CollectionItem.monster_id == Monster.id)
                     .filter(CollectionItem.collection_id == int(collection_id))
                     .distinct(Monster.id)
            )

        # 基础筛选
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(Monster.name.ilike(like))
        if element:
            query = query.filter(Monster.element == element)
        if role:
            query = query.filter(Monster.role == role)

        # 标签筛选
        if tags_all:
            for t in tags_all:
                if t:
                    query = query.filter(Monster.tags.any(Tag.name == t))
        if tag:
            query = query.filter(Monster.tags.any(Tag.name == tag))

        # 获取途径（包含匹配）
        acq = (acq_type or type or "").strip()
        if acq:
            query = query.filter(Monster.type.ilike(f"%{acq}%"))

        # 排序
        s = (sort or "updated_at").lower()
        is_asc = (order or "desc").lower() == "asc"

        if s == "raw_sum":
            raw_sum = (
                (Monster.hp or 0) + (Monster.speed or 0) + (Monster.attack or 0) +
                (Monster.defense or 0) + (Monster.magic or 0) + (Monster.resist or 0)
            )
            query = query.order_by(raw_sum.asc() if is_asc else raw_sum.desc(), Monster.id.asc())
        elif s in {"hp", "speed", "attack", "defense", "magic", "resist", "name", "created_at", "updated_at"}:
            col = getattr(Monster, s)
            query = query.order_by(col.asc() if is_asc else col.desc(), Monster.id.asc())
        else:
            query = query.order_by(Monster.updated_at.desc(), Monster.id.asc())

        # 计数（与查询同条件）
        total = query.order_by(None).count()

        # 分页
        items = query.offset((page - 1) * page_size).limit(page_size).all()

    # 预加载（避免 N+1）
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

    out = []
    for m in items:
        d = compute_derived_out(m)
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