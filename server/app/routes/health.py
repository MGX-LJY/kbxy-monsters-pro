# server/app/routes/health.py
from fastapi import APIRouter
from sqlalchemy import func
from ..db import SessionLocal
from ..models import Monster, Tag, MonsterSkill
import platform

router = APIRouter()

@router.get("/health")
def health():
    with SessionLocal() as db:
        m = db.query(Monster).count()
        t = db.query(Tag).count()
    return {
        "ok": True,
        "versions": {"python": platform.python_version(), "fastapi": "0.112", "sqlalchemy": "2.x"},
        "db_path": "kbxy-dev.db",
        "engine_version": "rules-2025.08.01",
        "counts": {"monsters": m, "tags": t}
    }

@router.get("/stats")
def stats():
    with SessionLocal() as db:
        # 总怪物数量
        total = db.query(Monster).count()
        
        # 有技能的怪物数量
        with_skills = db.query(func.count(func.distinct(MonsterSkill.monster_id))).scalar() or 0
        
        # 标签总数
        tags_total = db.query(Tag).count()
        
    return {
        "total": total,
        "with_skills": with_skills,
        "tags_total": tags_total
    }
