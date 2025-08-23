# server/app/routes/health.py
from fastapi import APIRouter
from ..db import SessionLocal
from ..models import Monster, Tag
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
