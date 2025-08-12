from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func
from typing import List, Dict

from ..db import SessionLocal
from ..models import Monster, Tag
from ..services.monsters_service import upsert_tags
from ..services.tags_service import (
    suggest_tags_for_monster,
    infer_role_for_monster,
)

router = APIRouter(prefix="/tags", tags=["tags"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("")
def list_tags(with_counts: bool = Query(False), db: Session = Depends(get_db)):
    if not with_counts:
        rows = db.scalars(select(Tag.name).order_by(Tag.name.asc())).all()
        return {"items": rows}
    rows = db.execute(
        select(Tag.name, func.count())
        .select_from(Tag)
        .join(Tag.monsters, isouter=True)
        .group_by(Tag.id, Tag.name)
        .order_by(func.count().desc(), Tag.name.asc())
    ).all()
    return {"items": [{"name": n, "count": int(c)} for n, c in rows]}

@router.post("/monsters/{monster_id}/suggest")
def suggest(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")
    return {
        "monster_id": m.id,
        "role": infer_role_for_monster(m),
        "tags": suggest_tags_for_monster(m),
    }

@router.post("/monsters/{monster_id}/retag")
def retag(monster_id: int, db: Session = Depends(get_db)):
    """
    计算并落库：role + tags
    """
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills), selectinload(Monster.tags))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    role = infer_role_for_monster(m)
    tags = suggest_tags_for_monster(m)
    m.role = role
    m.tags = upsert_tags(db, tags)
    db.commit()
    return {"ok": True, "monster_id": m.id, "role": role, "tags": tags}