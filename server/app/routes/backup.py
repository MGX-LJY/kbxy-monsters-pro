# server/app/routes/backup.py
from fastapi import APIRouter, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func
from ..db import SessionLocal
from ..models import Monster, Tag
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills
from typing import Dict, Any, Optional, List
from pydantic import BaseModel, Field
import io, csv, json

router = APIRouter()  # 不加 prefix，路径即为下面定义的绝对路径

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ====== 统计（首页卡片用） ======
@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    total = db.scalar(select(func.count(Monster.id))) or 0
    with_skills = db.scalar(
        select(func.count(func.distinct(Monster.id))).join(Monster.skills)
    ) or 0
    tags_total = db.scalar(select(func.count(Tag.id))) or 0
    return {"total": int(total), "with_skills": int(with_skills), "tags_total": int(tags_total)}

# ====== 导出 CSV（新：六维，不再有 control） ======
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
    items, _ = list_monsters(
        db,
        q=q, element=element, role=role, tag=tag,
        sort=sort, order=order, page=1, page_size=100000
    )
    buf = io.StringIO()
    w = csv.writer(buf)
    # 六维导出：offense/survive/defense/magic/tempo/pp
    w.writerow([
        "id","name_final","element","role",
        "offense","survive","defense","magic","tempo","pp",
        "tags"
    ])
    for m in items:
        w.writerow([
            m.id, m.name_final, m.element or "", m.role or "",
            m.base_offense or 0, m.base_survive or 0,
            getattr(m, "base_defense", 0) or 0, getattr(m, "base_magic", 0) or 0,
            m.base_tempo or 0, m.base_pp or 0,
            "|".join(t.name for t in (m.tags or []))
        ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=monsters.csv"}
    )

# ====== 备份 JSON（嵌套结构，导出六维 + 原始 raw_stats） ======
@router.get("/backup/export_json")
def backup_json(db: Session = Depends(get_db)):
    monsters = db.execute(
        select(Monster).options(
            selectinload(Monster.tags),
            selectinload(Monster.skills),
        )
    ).scalars().all()

    payload = []
    for m in monsters:
        ex = m.explain_json or {}
        raw = ex.get("raw_stats") or {}
        payload.append({
            "id": m.id,
            "name_final": m.name_final,
            "element": m.element,
            "role": m.role,
            # 六维（新）
            "base_offense": m.base_offense or 0,
            "base_survive": m.base_survive or 0,
            "base_defense": getattr(m, "base_defense", 0) or 0,
            "base_magic": getattr(m, "base_magic", 0) or 0,
            "base_tempo": m.base_tempo or 0,
            "base_pp": m.base_pp or 0,
            # 原始六维
            "raw_stats": raw,
            # 多对多
            "tags": [t.name for t in (m.tags or [])],
            "skills": [{"name": s.name, "description": s.description or ""} for s in (m.skills or [])],
        })
    data = json.dumps({"monsters": payload}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([data]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=backup.json"}
    )

# ====== 恢复 JSON（Upsert，覆盖技能集合；新：写入 defense/magic） ======
@router.post("/backup/restore_json")
def restore_json(payload: Dict[str, Any] = Body(...), db: Session = Depends(get_db)):
    monsters = payload.get("monsters") or []
    inserted = updated = 0
    with db.begin():
        for item in monsters:
            name = (item.get("name_final") or "").strip()
            if not name:
                continue
            element = (item.get("element") or None)

            q = select(Monster).where(Monster.name_final == name)
            if element:
                q = q.where(Monster.element == element)
            m = db.execute(q).scalar_one_or_none()

            is_new = m is None
            if is_new:
                m = Monster(name_final=name, element=element)

            # 优先读六维字段；若缺少 defense/magic，从 raw_stats 兜底；实在没有则 0
            raw_stats = item.get("raw_stats") or {}
            m.role = item.get("role") or m.role
            m.base_offense = float(item.get("base_offense") or 0)
            m.base_survive = float(item.get("base_survive") or 0)
            # 新：defense/magic
            base_defense = item.get("base_defense")
            base_magic = item.get("base_magic")
            if base_defense is None:
                base_defense = raw_stats.get("defense", 0)
            if base_magic is None:
                base_magic = raw_stats.get("magic", 0)
            # 转 float 存库
            m.base_defense = float(base_defense or 0)
            m.base_magic = float(base_magic or 0)

            m.base_tempo   = float(item.get("base_tempo") or raw_stats.get("speed") or 0)
            m.base_pp      = float(item.get("base_pp") or raw_stats.get("resist") or 0)

            # 回写 raw_stats
            ex = m.explain_json or {}
            if raw_stats:
                ex["raw_stats"] = raw_stats
            m.explain_json = ex

            # 覆盖标签
            m.tags = upsert_tags(db, item.get("tags") or [])

            # 覆盖技能集合
            skill_pairs = [
                ((s.get("name") or "").strip(), (s.get("description") or "").strip())
                for s in (item.get("skills") or [])
                if (s.get("name") or "").strip()
            ]
            upserted = upsert_skills(db, skill_pairs)
            m.skills = list(upserted)

            if is_new:
                db.add(m)
                inserted += 1
            else:
                updated += 1

    return {"inserted": inserted, "updated": updated}

# ====== 批量删除：DELETE + POST 兼容，且用 default_factory 避免可变默认 ======
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