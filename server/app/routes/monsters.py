# server/app/routes/monsters.py
from typing import Optional, Iterable, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ..db import SessionLocal
from ..models import Monster, Tag, Skill
from ..schemas import MonsterIn, MonsterOut, MonsterList, SkillIn

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- helpers ----
def _derive_out(m: Monster) -> MonsterOut:
    hp = float(m.base_hp or 0)
    speed = float(m.base_speed or 0)
    attack = float(m.base_attack or 0)
    defense = float(m.base_defense or 0)
    magic = float(m.base_magic or 0)
    resist = float(m.base_resist or 0)

    control = (defense + magic) / 2.0
    offense = attack
    survive = hp
    tempo = speed
    pp = resist
    total = hp + speed + attack + defense + magic + resist

    return MonsterOut(
        id=m.id,
        name_final=m.name_final,
        element=m.element,
        role=m.role,
        hp=hp, speed=speed, attack=attack, defense=defense, magic=magic, resist=resist,
        sum=total, offense=offense, survive=survive, control=control, tempo=tempo, pp=pp,
        tags=[t.name for t in (m.tags or [])],
        explain_json=m.explain_json or {},
    )

def upsert_tags(db: Session, names: Iterable[str]) -> List[Tag]:
    norm = []
    seen = set()
    for n in (names or []):
        name = (n or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        norm.append(name)
    if not norm:
        return []
    existing = db.execute(select(Tag).where(Tag.name.in_(norm))).scalars().all()
    exist_map = {t.name: t for t in existing}
    out: List[Tag] = []
    for name in norm:
        if name in exist_map:
            out.append(exist_map[name])
        else:
            t = Tag(name=name)
            db.add(t)
            db.flush()
            out.append(t)
    return out

def upsert_skills(db: Session, items: Iterable[Tuple[str, str]]) -> List[Skill]:
    names = [ ( (n or "").strip(), (d or "") ) for n,d in (items or []) if (n or "").strip() ]
    if not names:
        return []
    want = [n for n,_ in names]
    existing = db.execute(select(Skill).where(Skill.name.in_(want))).scalars().all()
    exist_map = {s.name: s for s in existing}
    out: List[Skill] = []
    for name, desc in names:
        if name in exist_map:
            s = exist_map[name]
            # 若传来描述，且库里为空，可顺便补充
            if desc and (s.description or "") == "":
                s.description = desc
            out.append(s)
        else:
            s = Skill(name=name, description=desc or "")
            db.add(s)
            db.flush()
            out.append(s)
    return out

# ---- APIs ----

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

    query = db.query(Monster)

    if q:
        like = f"%{q.strip()}%"
        query = query.filter(Monster.name_final.ilike(like))
    if element:
        query = query.filter(Monster.element == element)
    if role:
        query = query.filter(Monster.role == role)
    if tag:
        query = query.join(Monster.tags).filter(Tag.name == tag)

    # 排序映射
    sort_map = {
        "updated_at": Monster.updated_at,
        "name": Monster.name_final,
        "hp": Monster.base_hp,
        "speed": Monster.base_speed,
        "attack": Monster.base_attack,
        "defense": Monster.base_defense,
        "magic": Monster.base_magic,
        "resist": Monster.base_resist,
        # 派生
        "sum": (Monster.base_hp + Monster.base_speed + Monster.base_attack + Monster.base_defense + Monster.base_magic + Monster.base_resist),
        "offense": Monster.base_attack,
        "survive": Monster.base_hp,
        "control": ((Monster.base_defense + Monster.base_magic) / 2.0),
        "tempo": Monster.base_speed,
        "pp": Monster.base_resist,
    }
    sort_col = sort_map.get(sort, Monster.updated_at)
    if (order or "desc").lower() == "asc":
        query = query.order_by(sort_col.asc())
    else:
        query = query.order_by(sort_col.desc())

    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()

    result = [_derive_out(m) for m in items]
    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}

@router.get("/monsters/{monster_id}", response_model=MonsterOut)
def detail(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    return _derive_out(m)

@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    m = Monster(
        name_final=payload.name_final.strip(),
        element=payload.element,
        role=payload.role,
        base_hp=payload.hp, base_speed=payload.speed, base_attack=payload.attack,
        base_defense=payload.defense, base_magic=payload.magic, base_resist=payload.resist,
    )
    # 标签
    m.tags = upsert_tags(db, payload.tags or [])

    # 写入 explain_json.raw_stats（保留“原版导入”）
    ex = m.explain_json or {}
    ex["raw_stats"] = {
        "hp": payload.hp, "speed": payload.speed, "attack": payload.attack,
        "defense": payload.defense, "magic": payload.magic, "resist": payload.resist,
        "sum": payload.hp + payload.speed + payload.attack + payload.defense + payload.magic + payload.resist,
    }
    m.explain_json = ex

    db.add(m)
    db.flush()  # 先拿到 id

    # 绑定技能
    if payload.skills:
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        m.skills = skills
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    db.commit()
    db.refresh(m)
    return _derive_out(m)

@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    m.name_final = payload.name_final.strip()
    m.element = payload.element
    m.role = payload.role
    m.base_hp = payload.hp
    m.base_speed = payload.speed
    m.base_attack = payload.attack
    m.base_defense = payload.defense
    m.base_magic = payload.magic
    m.base_resist = payload.resist

    # 覆盖标签
    m.tags = upsert_tags(db, payload.tags or [])

    # 可选：同时覆盖技能（如果前端传来；这里 payload.skills 总是存在，按你的新前端来）
    m.skills.clear()
    if payload.skills:
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        m.skills = skills

    # 更新 explain_json.raw_stats / skill_names
    ex = m.explain_json or {}
    ex["raw_stats"] = {
        "hp": payload.hp, "speed": payload.speed, "attack": payload.attack,
        "defense": payload.defense, "magic": payload.magic, "resist": payload.resist,
        "sum": payload.hp + payload.speed + payload.attack + payload.defense + payload.magic + payload.resist,
    }
    ex["skill_names"] = [s.name for s in (m.skills or [])]
    m.explain_json = ex

    db.commit()
    db.refresh(m)
    return _derive_out(m)

@router.delete("/monsters/{monster_id}")
def delete(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")
    db.delete(m)
    db.commit()
    return {"ok": True}