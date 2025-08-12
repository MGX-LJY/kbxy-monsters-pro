from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from ..db import SessionLocal
from ..models import Tag, Monster

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/tags")
def tags(with_counts: bool = True, db: Session = Depends(get_db)):
    if with_counts:
        rows = db.execute(
            select(Tag.name, func.count(Monster.id))
            .join(Tag.monsters, isouter=True)
            .group_by(Tag.id)
            .order_by(Tag.name)
        ).all()
        return [{"name": n, "count": int(c)} for n, c in rows]
    else:
        rows = db.scalars(select(Tag.name).order_by(Tag.name)).all()
        return [{"name": n} for n in rows]
