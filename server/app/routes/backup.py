# server/app/routes/backup.py
from __future__ import annotations

from fastapi import APIRouter, Depends, Body
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func

from ..db import SessionLocal
from ..models import Monster, Tag, MonsterSkill  # 注意：引入 MonsterSkill 用于统计
from ..services.monsters_service import list_monsters

from typing import Optional, List
from pydantic import BaseModel, Field
import io, csv, json

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/stats")
def stats(db: Session = Depends(get_db)):
    """
    统计摘要：
    - total：怪物总数
    - with_skills：至少关联 1 条 MonsterSkill 的怪物数量
    - tags_total：标签总数
    """
    total = db.scalar(select(func.count(Monster.id))) or 0
    # 新模型：通过 Monster.monster_skills 统计（而非旧的 Monster.skills secondary）
    with_skills = db.scalar(
        select(func.count(func.distinct(Monster.id)))
        .join(Monster.monster_skills)
    ) or 0
    tags_total = db.scalar(select(func.count(Tag.id))) or 0
    return {
        "total": int(total),
        "with_skills": int(with_skills),
        "tags_total": int(tags_total),
    }

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

@router.get("/backup/export_json")
def backup_json(db: Session = Depends(get_db)):
    """
    备份 JSON（适配新库结构）
    - 怪物字段：id/name/element/role/possess/new_type/type/method/原始六维/explain_json.raw_stats
    - 技能字段：按新唯一键导出 name/element/kind/power/description
    - 不导出派生表；如有需要可在客户端或恢复后重算
    """
    monsters = db.execute(
        select(Monster).options(
            selectinload(Monster.tags),
            # 预加载 MonsterSkill 以及 Skill，避免 N+1
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
        )
    ).scalars().all()

    payload = []
    for m in monsters:
        raw = (m.explain_json or {}).get("raw_stats") or {}
        skills_out = []
        # 通过 MonsterSkill 取到 Skill，并携带技能四元组字段
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
                # 如需把关系级数据也备份，可按需解注：
                # "selected": bool(ms.selected),
                # "level": ms.level,
                # "rel_description": ms.description or "",
            })

        payload.append({
            "id": m.id,
            "name": getattr(m, "name", None),
            "element": m.element,
            "role": m.role,
            "possess": getattr(m, "possess", False),
            "new_type": getattr(m, "new_type", None),
            "type": getattr(m, "type", None),
            "method": getattr(m, "method", None),
            # 原始六维
            "hp": float(m.hp or 0),
            "speed": float(m.speed or 0),
            "attack": float(m.attack or 0),
            "defense": float(m.defense or 0),
            "magic": float(m.magic or 0),
            "resist": float(m.resist or 0),
            # 额外信息
            "raw_stats": raw,
            "tags": [t.name for t in (m.tags or [])],
            "skills": skills_out,
            # 有时恢复或审计需要：
            "created_at": getattr(m, "created_at", None).isoformat() if getattr(m, "created_at", None) else None,
            "updated_at": getattr(m, "updated_at", None).isoformat() if getattr(m, "updated_at", None) else None,
        })

    data = json.dumps({"monsters": payload}, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([data]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=backup.json"}
    )

class BulkDeleteIn(BaseModel):
    ids: List[int] = Field(default_factory=list)

@router.delete("/monsters/bulk_delete")
def bulk_delete_delete(payload: BulkDeleteIn = Body(...), db: Session = Depends(get_db)):
    """
    批量删除（保持接口不变）
    """
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