# server/app/routes/warehouse.py
from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel  # ← 提前导入 BaseModel

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster, MonsterSkill
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


# ---- 列表（仅仓库内）----
@router.get("/warehouse", response_model=MonsterList)
def warehouse_list(
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "updated_at",
    order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    items, total = list_warehouse(
        db,
        q=q, element=element, role=role, tag=tag,
        sort=sort or "updated_at", order=order or "desc",
        page=page, page_size=page_size,
    )

    # 预加载（避免 N+1）
    ids = [m.id for m in items]
    if ids:
        _ = db.execute(
            select(Monster)
            .where(Monster.id.in_(ids))
            .options(
                selectinload(Monster.tags),
                selectinload(Monster.derived),
                # 显式走关系 Monster.monster_skills -> MonsterSkill.skill
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

    etag = f'W/"warehouse:{total}"'
    return {"items": out, "total": total, "has_more": page * page_size < total, "etag": etag}


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
    return warehouse_stats(db)