from fastapi import APIRouter, Depends
from pydantic import BaseModel
from typing import List, Optional, Dict
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Monster
from ..services.rules_engine import calc_scores
from ..services.monsters_service import upsert_tags
from ..services.skills_service import derive_tags_from_texts

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

class RecalcIn(BaseModel):
    ids: Optional[List[int]] = None
    weights: Optional[Dict[str, float]] = None
    persist: bool = False
    update_tags: bool = True

@router.post("/recalc")
def recalc(payload: RecalcIn, db: Session = Depends(get_db)):
    ids = payload.ids or [i for (i,) in db.query(Monster.id).all()]
    affected = 0
    result = []
    for mid in ids:
        m = db.get(Monster, mid)
        if not m:
            continue
        r = calc_scores({
            "base_offense": m.base_offense,
            "base_survive": m.base_survive,
            "base_control": m.base_control,
            "base_tempo": m.base_tempo,
            "base_pp": m.base_pp
        }, payload.weights)

        if payload.persist:
            m.explain_json = r.explain
            if payload.update_tags:
                numeric = set(r.tags)
                skill_texts = [s.name for s in (m.skills or [])] + [s.description for s in (m.skills or [])]
                skill_tags = derive_tags_from_texts(skill_texts)
                existing = {t.name for t in (m.tags or [])}
                merged = sorted(existing | numeric | skill_tags)
                m.tags = upsert_tags(db, merged)
            db.add(m); affected += 1

        result.append({"id": mid, "tags": r.tags, "explain": r.explain})

    if payload.persist:
        db.commit()
    return {"affected": affected, "results": result}