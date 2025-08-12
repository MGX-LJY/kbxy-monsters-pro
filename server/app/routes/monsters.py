# server/app/routes/monsters.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Monster
from ..schemas import MonsterIn, MonsterOut, MonsterList, SkillIn
from ..services.monsters_service import list_monsters, upsert_tags, apply_scores
from ..services.skills_service import upsert_skills

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.get("/monsters", response_model=MonsterList)
def list_api(
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    sort: Optional[str] = "updated_at",
    order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db)
):
    page = max(1, page)
    page_size = min(max(1, page_size), 200)
    items, total = list_monsters(
        db, q=q, element=element, role=role, tag=tag,
        sort=sort, order=order, page=page, page_size=page_size
    )
    result = []
    for m in items:
        result.append(MonsterOut(
            id=m.id,
            name_final=m.name_final,
            element=m.element,
            role=m.role,
            base_offense=m.base_offense,
            base_survive=m.base_survive,
            base_control=m.base_control,
            base_tempo=m.base_tempo,
            base_pp=m.base_pp,
            tags=[t.name for t in m.tags],
            explain_json=m.explain_json or {}
        ))
    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}

@router.get("/monsters/{monster_id}", response_model=MonsterOut)
def detail(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    return MonsterOut(
        id=m.id, name_final=m.name_final, element=m.element, role=m.role,
        base_offense=m.base_offense, base_survive=m.base_survive, base_control=m.base_control,
        base_tempo=m.base_tempo, base_pp=m.base_pp, tags=[t.name for t in m.tags],
        explain_json=m.explain_json or {}
    )

@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    # 基本信息
    m = Monster(
        name_final=payload.name_final,
        element=payload.element,
        role=payload.role,
        base_offense=payload.base_offense,
        base_survive=payload.base_survive,
        base_control=payload.base_control,
        base_tempo=payload.base_tempo,
        base_pp=payload.base_pp,
    )
    # 标签
    m.tags = upsert_tags(db, payload.tags or [])
    # 评分/解释
    apply_scores(m)
    db.add(m)
    db.flush()  # 先拿到 id

    # 绑定技能（支持多个）
    if payload.skills:
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        existed = {s.id for s in (m.skills or [])}
        for s in skills:
            if s.id not in existed:
                m.skills.append(s)
                existed.add(s.id)
        # 将技能名兜底写入 explain_json
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    db.commit()
    db.refresh(m)
    return detail(m.id, db)

@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    for k in ["name_final","element","role","base_offense","base_survive","base_control","base_tempo","base_pp"]:
        setattr(m, k, getattr(payload, k))
    m.tags = upsert_tags(db, payload.tags or [])
    apply_scores(m)

    # 可选：同时覆盖技能（如果前端传来）
    if payload.skills is not None:
        # 清空再绑定（也可做差量；这里简单直接）
        m.skills.clear()
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        for s in skills:
            m.skills.append(s)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    db.commit()
    return detail(monster_id, db)

@router.delete("/monsters/{monster_id}")
def delete(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(m)
    db.commit()
    return {"ok": True}