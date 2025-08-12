# server/app/routes/utils.py
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..db import SessionLocal
from ..models import Monster
from ..services.derive_service import compute_and_persist

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/utils/backfill_raw_to_columns")
def backfill_raw_to_columns(db: Session = Depends(get_db)):
    mons = db.scalars(select(Monster)).all()
    touched = 0
    for m in mons:
        ex = (m.explain_json or {})
        raw = ex.get("raw_stats") or {}
        # 只在列缺失/为0时回填
        def need(v): 
            try: return v is None or float(v) == 0.0
            except: return True

        changed = False
        if raw:
            if need(m.hp)      and raw.get("hp")      is not None: m.hp      = float(raw["hp"]); changed = True
            if need(m.speed)   and raw.get("speed")   is not None: m.speed   = float(raw["speed"]); changed = True
            if need(m.attack)  and raw.get("attack")  is not None: m.attack  = float(raw["attack"]); changed = True
            if need(m.defense) and raw.get("defense") is not None: m.defense = float(raw["defense"]); changed = True
            if need(m.magic)   and raw.get("magic")   is not None: m.magic   = float(raw["magic"]); changed = True
            if need(m.resist)  and raw.get("resist")  is not None: m.resist  = float(raw["resist"]); changed = True

        if changed:
            compute_and_persist(db, m)
            touched += 1
    db.commit()
    return {"updated_rows": touched}