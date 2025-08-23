# server/app/routes/roles.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db import SessionLocal
from ..models import Monster

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/roles")
def list_roles(db: Session = Depends(get_db)):
    q = (db.query(Monster.role, func.count(Monster.id))
           .filter(Monster.role.isnot(None), Monster.role != "")
           .group_by(Monster.role)
           .order_by(func.count(Monster.id).desc()))
    return [{"name": r[0], "count": r[1]} for r in q.all()]