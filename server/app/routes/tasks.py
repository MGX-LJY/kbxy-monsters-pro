import threading, uuid
from typing import Optional, Dict
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Task, Monster
from ..services.rules_engine import calc_scores
from ..services.monsters_service import upsert_tags

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _run_recalc(task_id: str, weights: Optional[Dict[str, float]]):
    db = SessionLocal()
    try:
        t = db.get(Task, task_id)
        t.status = "running"
        db.commit()

        ids = [i for (i,) in db.query(Monster.id).all()]
        total = len(ids)
        done = 0
        for mid in ids:
            m = db.get(Monster, mid)
            r = calc_scores({
                "base_offense": m.base_offense,
                "base_survive": m.base_survive,
                "base_control": m.base_control,
                "base_tempo": m.base_tempo,
                "base_pp": m.base_pp
            }, weights)
            m.explain_json = r.explain
            # 合并计算标签
            existing = [t.name for t in m.tags]
            merged = sorted(set(existing) | set(r.tags))
            m.tags = upsert_tags(db, merged)

            done += 1
            if done % 50 == 0:
                t = db.get(Task, task_id)
                t.progress = done
                t.total = total
                db.commit()
        # final commit
        t = db.get(Task, task_id)
        t.progress = done
        t.total = total
        t.status = "done"
        db.commit()
    except Exception as e:
        t = db.get(Task, task_id)
        if t:
            t.status = "failed"
            t.result_json = {"error": str(e)}
            db.commit()
    finally:
        db.close()

@router.post("/tasks/recalc")
def start_recalc(weights: Optional[Dict[str, float]] = None, db: Session = Depends(get_db)):
    task_id = str(uuid.uuid4())
    t = Task(id=task_id, type="recalc", status="pending", progress=0, total=0, result_json={})
    db.add(t)
    db.commit()
    threading.Thread(target=_run_recalc, args=(task_id, weights), daemon=True).start()
    return {"task_id": task_id, "status": "pending"}

@router.get("/tasks/{task_id}")
def get_task(task_id: str, db: Session = Depends(get_db)):
    t = db.get(Task, task_id)
    if not t:
        raise HTTPException(status_code=404, detail="task not found")
    return {"id": t.id, "type": t.type, "status": t.status, "progress": t.progress, "total": t.total, "result": t.result_json}