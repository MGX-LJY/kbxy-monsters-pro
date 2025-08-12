# server/app/routes/derive.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..db import SessionLocal
from ..models import Monster
from ..schemas import DerivedOut
from ..services.derive_service import (
    compute_derived_out, compute_and_persist, recompute_all
)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/derive/{monster_id}", response_model=DerivedOut)
def get_derived(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    return DerivedOut(**compute_derived_out(m))

@router.post("/derive/recalc/{monster_id}", response_model=DerivedOut)
def recalc_one(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    compute_and_persist(db, m)
    db.commit()
    return DerivedOut(**compute_derived_out(m))

@router.post("/derive/recalc_all")
def recalc_all(db: Session = Depends(get_db)):
    n = recompute_all(db)
    db.commit()
    return {"recalculated": n}