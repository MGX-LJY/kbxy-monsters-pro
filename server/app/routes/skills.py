from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Monster

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/monsters/{monster_id}/skills")
def list_skills(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")
    return [{"id": s.id, "name": s.name, "description": s.description} for s in (m.skills or [])]