# server/app/routes/skills.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from pydantic import BaseModel, Field
from typing import List
from ..db import SessionLocal
from ..models import Monster
from ..services.skills_service import upsert_skills

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class SkillIn(BaseModel):
    name: str
    description: str | None = None

class SkillSetIn(BaseModel):
    skills: List[SkillIn] = Field(default_factory=list)

@router.get("/monsters/{monster_id}/skills")
def get_monster_skills(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .options(selectinload(Monster.skills))
        .where(Monster.id == monster_id)
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")
    return [{"id": s.id, "name": s.name, "description": s.description or ""} for s in (m.skills or [])]

@router.put("/monsters/{monster_id}/skills")
@router.post("/monsters/{monster_id}/skills")
def set_monster_skills(monster_id: int, body: SkillSetIn, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .options(selectinload(Monster.skills))
        .where(Monster.id == monster_id)
    ).scalars().first()
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")

    pairs = [(s.name.strip(), (s.description or "").strip())
             for s in body.skills if s.name and s.name.strip()]

    try:
        # upsert 技能对象（返回 Skill ORM 实体列表）
        upserted = upsert_skills(db, pairs)

        # 用新集合覆盖绑定
        m.skills.clear()
        for s in upserted:
            m.skills.append(s)

        db.flush()
        db.commit()
    except Exception as e:
        db.rollback()
        # 透传更友好的错误
        raise HTTPException(status_code=500, detail=f"save skills failed: {e}")

    return {"ok": True, "count": len(m.skills)}