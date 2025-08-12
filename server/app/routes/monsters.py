# server/app/routes/monsters.py
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select
from ..db import SessionLocal
from ..models import Monster, MonsterDerived
from ..schemas import MonsterIn, MonsterOut, MonsterList
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills
from ..services.derive_service import compute_derived_out, compute_and_persist

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

    # 预加载集合关系
    ids = [m.id for m in items]
    if ids:
        _ = db.execute(
            select(Monster)
            .where(Monster.id.in_(ids))
            .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
        ).scalars().all()

    result = []
    for m in items:
        # 没有派生行就现算并落库一次
        if not m.derived:
            compute_and_persist(db, m)
        d = {
            "offense": m.derived.offense if m.derived else compute_derived_out(m)["offense"],
            "survive": m.derived.survive if m.derived else compute_derived_out(m)["survive"],
            "control": m.derived.control if m.derived else compute_derived_out(m)["control"],
            "tempo": m.derived.tempo if m.derived else compute_derived_out(m)["tempo"],
            "pp_pressure": m.derived.pp_pressure if m.derived else compute_derived_out(m)["pp_pressure"],
        }
        result.append(MonsterOut(
            id=m.id,
            name_final=m.name_final,
            element=m.element,
            role=m.role,
            hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
            tags=[t.name for t in (m.tags or [])],
            explain_json=m.explain_json or {},
            derived=d,
        ))
    db.commit()  # 可能写入了 derived
    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}

@router.get("/monsters/{monster_id}", response_model=MonsterOut)
def detail(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster).where(Monster.id == monster_id).options(
            selectinload(Monster.skills),
            selectinload(Monster.tags),
            selectinload(Monster.derived),
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    if not m.derived:
        compute_and_persist(db, m)
        db.commit()

    return MonsterOut(
        id=m.id, name_final=m.name_final, element=m.element, role=m.role,
        hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
        tags=[t.name for t in (m.tags or [])],
        explain_json=m.explain_json or {},
        derived={
            "offense": m.derived.offense,
            "survive": m.derived.survive,
            "control": m.derived.control,
            "tempo": m.derived.tempo,
            "pp_pressure": m.derived.pp_pressure,
        }
    )

@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    m = Monster(
        name_final=payload.name_final, element=payload.element, role=payload.role,
        hp=payload.hp, speed=payload.speed, attack=payload.attack,
        defense=payload.defense, magic=payload.magic, resist=payload.resist,
    )
    m.tags = upsert_tags(db, payload.tags or [])
    db.add(m); db.flush()

    if payload.skills:
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        existed = {s.id for s in (m.skills or [])}
        for s in skills:
            if s.id not in existed:
                m.skills.append(s); existed.add(s.id)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    # 首次计算并落库
    compute_and_persist(db, m)
    db.commit(); db.refresh(m)
    return detail(m.id, db)

@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    for k in ["name_final","element","role","hp","speed","attack","defense","magic","resist"]:
        setattr(m, k, getattr(payload, k))
    m.tags = upsert_tags(db, payload.tags or [])

    if payload.skills is not None:
        m.skills.clear()
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        for s in skills:
            m.skills.append(s)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    # 更新后重算派生并落库
    compute_and_persist(db, m)
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