# server/app/routes/images.py
from __future__ import annotations
from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Monster
from ..services.image_service import get_image_resolver

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/images/resolve")
def api_resolve_image(
    id: int | None = Query(None),
    name: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """
    通过 id 或 name 解析图片 URL。
    返回 {found: bool, url: str|null}
    """
    resv = get_image_resolver()
    candidates: list[str] = []

    if id is not None:
        m = db.query(Monster).filter(Monster.id == id).first()
        if not m:
            raise HTTPException(status_code=404, detail="monster not found")
        # name / name_final / alias 可按你表结构添加
        for x in [m.name, getattr(m, "name_final", None), getattr(m, "alias", None)]:
            if x:
                candidates.append(x)
    elif name:
        candidates.append(name)
    else:
        raise HTTPException(status_code=400, detail="require id or name")

    url = resv.resolve_by_names(candidates)
    return {"found": bool(url), "url": url}

@router.post("/images/reindex")
def api_reindex():
    """
    重新扫描图片目录；返回索引数量。
    """
    resv = get_image_resolver()
    n = resv.reindex()
    return {"ok": True, "count": n}

@router.get("/monsters/{monster_id}/image")
def api_monster_image(monster_id: int, db: Session = Depends(get_db)):
    """
    直接拿某个怪的图片 URL。
    """
    m = db.query(Monster).filter(Monster.id == monster_id).first()
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")
    resv = get_image_resolver()
    url = resv.resolve_by_names([m.name, getattr(m, "name_final", None), getattr(m, "alias", None)])
    if not url:
        raise HTTPException(status_code=404, detail="image not found")
    # 也可以 307 重定向到静态 URL，这里用 JSON
    return {"url": url}