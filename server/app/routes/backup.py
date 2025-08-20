from __future__ import annotations

from fastapi import APIRouter, Depends, Body, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, delete
from typing import Optional, List, Any, Dict
from pydantic import BaseModel, Field
from datetime import datetime
import io, csv, json, re

from ..db import SessionLocal
from ..models import (
    Monster,
    Tag,
    MonsterSkill,   # 关系表
    Skill,          # 技能主表：用于五元组唯一
    Collection,     # ← 新增：收藏夹
    CollectionItem, # ← 新增：收藏夹成员
)
from ..services.monsters_service import list_monsters

router = APIRouter()

# ---------- DB 依赖 ----------
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- 小工具 ----------
_ZERO_WIDTH_RE = re.compile(r"[\u200B-\u200D\u2060\uFEFF]")
def clean_text(s: Optional[str]) -> Optional[str]:
    if s is None:
        return None
    return _ZERO_WIDTH_RE.sub("", str(s)).strip()

def to_int_or_none(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except Exception:
        try:
            return int(float(v))  # “145.0”这类
        except Exception:
            return None

def parse_dt_or_none(s: Any) -> Optional[datetime]:
    if not s:
        return None
    try:
        # 允许 ISO8601 字符串
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None

def dt_to_iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if isinstance(dt, datetime) else None

def valid_tag(code: str) -> bool:
    return isinstance(code, str) and (
        code.startswith("buf_") or code.startswith("deb_") or code.startswith("util_")
    )

# ---------- 统计 ----------
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """
    统计摘要：
    - total：怪物总数
    - with_skills：至少关联 1 条 MonsterSkill 的怪物数量
    - tags_total：标签总数
    """
    total = db.scalar(select(func.count(Monster.id))) or 0
    with_skills = db.scalar(
        select(func.count(func.distinct(Monster.id))).join(Monster.monster_skills)
    ) or 0
    tags_total = db.scalar(select(func.count(Tag.id))) or 0
    return {
        "total": int(total),
        "with_skills": int(with_skills),
        "tags_total": int(tags_total),
    }

# ---------- 导出 CSV ----------
@router.get("/export/monsters.csv")
def export_csv(
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "updated_at",
    order: Optional[str] = "desc",
    db: Session = Depends(get_db),
):
    """
    导出 CSV（适配新库结构）
    字段：id,name,element,role,offense,survive,control,tempo,pp_pressure,tags
    - 五维来自 MonsterDerived；若为空则输出 0
    """
    items, _ = list_monsters(
        db,
        q=q, element=element, role=role, tag=tag,
        sort=sort, order=order, page=1, page_size=100000
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "element", "role", "offense", "survive", "control", "tempo", "pp_pressure", "tags"])

    for m in items:
        d = m.derived
        w.writerow([
            m.id,
            getattr(m, "name", "") or "",
            m.element or "",
            m.role or "",
            (d.offense if d else 0),
            (d.survive if d else 0),
            (d.control if d else 0),
            (d.tempo if d else 0),
            (d.pp_pressure if d else 0),
            "|".join(t.name for t in (m.tags or [])),
        ])

    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=monsters.csv"}
    )

# ---------- 备份 JSON ----------
@router.get("/backup/export_json")
def backup_json(db: Session = Depends(get_db)):
    """
    备份 JSON（适配新库结构）
    - 怪物字段：id/name/element/role/possess/new_type/type/method/六维/explain_json.raw_stats
    - 技能字段：按新唯一键导出 name/element/kind/power/description
    - 收藏夹：id/name/color,last_used_at,created_at,updated_at,items:[monster_id...]
    - 不导出派生表；如有需要可在客户端或恢复后重算
    """
    monsters = db.execute(
        select(Monster).options(
            selectinload(Monster.tags),
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
        )
    ).scalars().all()

    monsters_payload = []
    for m in monsters:
        raw = (m.explain_json or {}).get("raw_stats") or {}
        skills_out = []
        for ms in (m.monster_skills or []):
            s = ms.skill
            if not s:
                continue
            skills_out.append({
                "name": s.name,
                "element": s.element,
                "kind": s.kind,
                "power": s.power,
                "description": s.description or "",
            })

        monsters_payload.append({
            "id": m.id,
            "name": getattr(m, "name", None),
            "element": m.element,
            "role": m.role,
            "possess": getattr(m, "possess", False),
            "new_type": getattr(m, "new_type", None),
            "type": getattr(m, "type", None),
            "method": getattr(m, "method", None),
            "hp": float(m.hp or 0),
            "speed": float(m.speed or 0),
            "attack": float(m.attack or 0),
            "defense": float(m.defense or 0),
            "magic": float(m.magic or 0),
            "resist": float(m.resist or 0),
            "raw_stats": raw,
            "tags": [t.name for t in (m.tags or [])],
            "skills": skills_out,
            "created_at": dt_to_iso(getattr(m, "created_at", None)),
            "updated_at": dt_to_iso(getattr(m, "updated_at", None)),
        })

    # 收藏夹导出
    collections = db.execute(
        select(Collection).options(selectinload(Collection.items))
    ).scalars().all()

    collections_payload = []
    for c in collections:
        collections_payload.append({
            "id": c.id,
            "name": c.name,
            "color": c.color,
            "last_used_at": dt_to_iso(getattr(c, "last_used_at", None)),
            "created_at": dt_to_iso(getattr(c, "created_at", None)),
            "updated_at": dt_to_iso(getattr(c, "updated_at", None)),
            "items": [ci.monster_id for ci in (c.items or [])],
        })

    data = json.dumps(
        {"monsters": monsters_payload, "collections": collections_payload},
        ensure_ascii=False, indent=2
    )
    return StreamingResponse(
        iter([data]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=backup.json"}
    )

# ---------- 批量删除 ----------
class BulkDeleteIn(BaseModel):
    ids: List[int] = Field(default_factory=list)

@router.delete("/monsters/bulk_delete")
def bulk_delete_delete(payload: BulkDeleteIn = Body(...), db: Session = Depends(get_db)):
    ids = list(set(payload.ids or []))
    if not ids:
        return {"deleted": 0}
    deleted = 0
    with db.begin():
        for mid in ids:
            m = db.get(Monster, mid)
            if m:
                db.delete(m)
                deleted += 1
    return {"deleted": deleted}

@router.post("/monsters/bulk_delete")
def bulk_delete_post(payload: BulkDeleteIn = Body(...), db: Session = Depends(get_db)):
    return bulk_delete_delete(payload, db)

# ---------- 恢复 / 导入 JSON ----------
@router.post("/backup/restore_json")
def restore_json(
    payload: Any = Body(..., description="支持 {\"monsters\": [...], \"collections\": [...]} 或直接 [...](仅怪物)。"),
    replace_links: bool = True,  # True：替换原有 tags/skills/收藏夹成员；False：追加合并
    db: Session = Depends(get_db)
):
    """
    从备份 JSON 恢复（兼容你的示例结构）：
    - 怪物：id 存在则按 id upsert；否则按 (name, element) 兜底匹配
    - 仅接受 buf_/deb_/util_ 标签；其余忽略
    - 技能按 (name, element, kind, power, description) 五元组去重，自动建 Skill，并用 MonsterSkill 关联
    - 收藏夹：按 id 或 name upsert，可选择替换/合并成员（默认替换）
    - 默认**替换**原有关联（replace_links=True）
    - 返回导入汇总
    """
    # 解析 monsters / collections 数组
    monsters_list: List[Dict[str, Any]] = []
    collections_list: List[Dict[str, Any]] = []

    if isinstance(payload, dict):
        if isinstance(payload.get("monsters"), list):
            monsters_list = payload["monsters"]
        if isinstance(payload.get("collections"), list):
            collections_list = payload["collections"]
    elif isinstance(payload, list):
        monsters_list = payload
    else:
        raise HTTPException(status_code=400, detail="载荷格式错误：应为 {\"monsters\": [...]} 或直接数组。")

    created_cnt = 0
    updated_cnt = 0
    linked_skills = 0
    linked_tags = 0

    coll_created = 0
    coll_updated = 0
    coll_members_linked = 0

    with db.begin():
        # ===== 怪物部分 =====
        for raw_m in monsters_list:
            if not isinstance(raw_m, dict):
                continue

            # --- 基础字段清洗 ---
            mid = raw_m.get("id")
            name = clean_text(raw_m.get("name"))
            element = clean_text(raw_m.get("element"))
            role = clean_text(raw_m.get("role"))
            type_ = clean_text(raw_m.get("type"))
            method = clean_text(raw_m.get("method"))

            hp = to_int_or_none(raw_m.get("hp")) or 0
            speed = to_int_or_none(raw_m.get("speed")) or 0
            attack = to_int_or_none(raw_m.get("attack")) or 0
            defense = to_int_or_none(raw_m.get("defense")) or 0
            magic = to_int_or_none(raw_m.get("magic")) or 0
            resist = to_int_or_none(raw_m.get("resist")) or 0

            possess = bool(raw_m.get("possess") or False)
            new_type = raw_m.get("new_type")  # 可能为 True/False/None

            created_at = parse_dt_or_none(raw_m.get("created_at"))
            updated_at = parse_dt_or_none(raw_m.get("updated_at"))

            # --- upsert 怪物 ---
            m: Optional[Monster] = None
            if mid:
                m = db.get(Monster, int(mid))

            if not m and name:
                # 兜底：按 (name, element) 尝试找到同名同元素
                q = select(Monster).where(Monster.name == name)
                if element:
                    q = q.where(Monster.element == element)
                m = db.scalar(q)

            is_create = False
            if not m:
                m = Monster()
                # 如果传了 id，尽量沿用（SQLite/PG 都允许显式插入主键；若冲突会抛错）
                if mid:
                    try:
                        m.id = int(mid)
                    except Exception:
                        pass
                is_create = True
                db.add(m)

            # 写基础字段
            m.name = name or m.name
            m.element = element
            m.role = role
            m.type = type_
            m.method = method
            m.possess = possess
            m.new_type = new_type if new_type in (True, False, None) else None

            m.hp = hp
            m.speed = speed
            m.attack = attack
            m.defense = defense
            m.magic = magic
            m.resist = resist

            # 额外信息：raw_stats 放入 explain_json.raw_stats
            raw_stats = raw_m.get("raw_stats") or {}
            if isinstance(raw_stats, dict):
                ej = dict(m.explain_json or {})
                ej["raw_stats"] = raw_stats
                m.explain_json = ej

            # 时间戳（如果提供了）
            if created_at:
                m.created_at = created_at
            if updated_at:
                m.updated_at = updated_at

            db.flush()  # 确保 m.id 可用

            # --- tags 关联 ---
            tags_in = raw_m.get("tags") or []
            tag_models: List[Tag] = []
            for t in tags_in:
                t = clean_text(t)
                if not t or not valid_tag(t):
                    continue
                existed = db.scalar(select(Tag).where(Tag.name == t))
                if not existed:
                    existed = Tag(name=t)
                    db.add(existed)
                    db.flush()
                tag_models.append(existed)

            if replace_links:
                # 替换关联
                m.tags = tag_models
            else:
                # 追加合并
                have = {tt.name for tt in (m.tags or [])}
                for tm in tag_models:
                    if tm.name not in have:
                        m.tags.append(tm)
                        have.add(tm.name)

            linked_tags += len(tag_models)

            # --- 技能关联（五元组唯一） ---
            skills_in = raw_m.get("skills") or []
            # 替换策略：先清空原 MonsterSkill
            if replace_links:
                db.execute(delete(MonsterSkill).where(MonsterSkill.monster_id == m.id))
                db.flush()

            for s in skills_in:
                if not isinstance(s, dict):
                    continue
                s_name = clean_text(s.get("name"))
                if not s_name:
                    continue
                s_element = clean_text(s.get("element"))
                s_kind = clean_text(s.get("kind"))
                s_power = to_int_or_none(s.get("power"))
                s_desc = clean_text(s.get("description")) or ""

                # 五元组查找/创建 Skill
                sk = db.scalar(
                    select(Skill).where(
                        Skill.name == s_name,
                        Skill.element.is_(s_element) if s_element is None else (Skill.element == s_element),
                        Skill.kind.is_(s_kind) if s_kind is None else (Skill.kind == s_kind),
                        Skill.power.is_(s_power) if s_power is None else (Skill.power == s_power),
                        Skill.description == s_desc,
                    )
                )
                if not sk:
                    sk = Skill(
                        name=s_name,
                        element=s_element,
                        kind=s_kind,
                        power=s_power,
                        description=s_desc,
                    )
                    db.add(sk)
                    db.flush()

                # 建 MonsterSkill 关联（避免重复）
                exists_rel = db.scalar(
                    select(MonsterSkill).where(
                        MonsterSkill.monster_id == m.id,
                        MonsterSkill.skill_id == sk.id,
                    )
                )
                if not exists_rel:
                    rel = MonsterSkill(monster_id=m.id, skill_id=sk.id)
                    db.add(rel)
                    linked_skills += 1

            if is_create:
                created_cnt += 1
            else:
                updated_cnt += 1

        # ===== 收藏夹部分（可选）=====
        for raw_c in collections_list:
            if not isinstance(raw_c, dict):
                continue

            cid = to_int_or_none(raw_c.get("id"))
            cname = clean_text(raw_c.get("name"))
            ccolor = clean_text(raw_c.get("color"))
            last_used_at = parse_dt_or_none(raw_c.get("last_used_at"))
            created_at = parse_dt_or_none(raw_c.get("created_at"))
            updated_at = parse_dt_or_none(raw_c.get("updated_at"))
            items = raw_c.get("items") or []

            # 定位收藏夹：优先 id，其次 name
            col: Optional[Collection] = None
            if cid:
                col = db.get(Collection, cid)
            if not col and cname:
                col = db.scalar(select(Collection).where(Collection.name == cname))

            is_new = False
            if not col:
                col = Collection(name=cname or (cname or f"收藏夹-{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"))
                if cid:
                    try:
                        col.id = cid
                    except Exception:
                        pass
                is_new = True
                db.add(col)
                db.flush()

            # 更新基本信息
            if cname:
                col.name = cname
            col.color = ccolor or col.color
            if last_used_at:
                col.last_used_at = last_used_at
            if created_at:
                col.created_at = created_at
            if updated_at:
                col.updated_at = updated_at

            db.flush()

            # 成员处理
            ids_unique = []
            seen_ids = set()
            for v in items:
                iv = to_int_or_none(v)
                if iv and iv not in seen_ids:
                    seen_ids.add(iv)
                    ids_unique.append(iv)

            if replace_links:
                # 清空原成员
                db.execute(delete(CollectionItem).where(CollectionItem.collection_id == col.id))
                db.flush()

            # 逐个关联（存在即跳过）
            for mid in ids_unique:
                if not db.get(Monster, mid):
                    continue
                existed_rel = db.scalar(
                    select(CollectionItem).where(
                        CollectionItem.collection_id == col.id,
                        CollectionItem.monster_id == mid,
                    )
                )
                if not existed_rel:
                    db.add(CollectionItem(collection_id=col.id, monster_id=mid))
                    coll_members_linked += 1

            if is_new:
                coll_created += 1
            else:
                coll_updated += 1

    return {
        "ok": True,
        "received": {
            "monsters": len(monsters_list),
            "collections": len(collections_list),
        },
        "monsters": {
            "created": created_cnt,
            "updated": updated_cnt,
            "linked_tags": linked_tags,
            "linked_skills": linked_skills,
        },
        "collections": {
            "created": coll_created,
            "updated": coll_updated,
            "members_linked": coll_members_linked,
        },
        "note": (
            "按 id 优先 upsert；未提供 id 时按 (name, element) 匹配；"
            "tags 仅导入 buf_/deb_/util_*；技能用五元组唯一；"
            "收藏夹按 id 或 name upsert，成员默认替换（可用 replace_links=False 合并）。"
        ),
    }