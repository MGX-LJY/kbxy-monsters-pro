from fastapi import APIRouter, UploadFile, File, Depends, Header
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..schemas import ImportPreview, ImportResult
from ..services import import_service

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/import/preview", response_model=ImportPreview)
async def import_preview(file: UploadFile = File(...)):
    data = await file.read()
    res = import_service.preview(data)
    return res

@router.post("/import/commit", response_model=ImportResult)
async def import_commit(file: UploadFile = File(...), idempotency_key: str | None = Header(default=None, convert_underscores=False), db: Session = Depends(get_db)):
    data = await file.read()
    res = import_service.commit(db, data, idempotency_key=idempotency_key)
    db.commit()
    return res
