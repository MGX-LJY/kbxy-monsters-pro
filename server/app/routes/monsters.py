# server/app/routes/monsters.py
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster
from ..schemas import MonsterIn, MonsterOut, MonsterList
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills
from ..services.derive_service import (
    compute_derived_out,
    compute_and_persist,
    recompute_and_autolabel,
    apply_role_tags,
)

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
    db: Session = Depends(get_db),
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
            .options(
                selectinload(Monster.skills),
                selectinload(Monster.tags),
                selectinload(Monster.derived),
            )
        ).scalars().all()

    result = []
    changed = False

    for m in items:
        # 1) 先确保 role / tags
        if (not m.role) or (not m.tags):
            apply_role_tags(db, m, override_role_if_blank=True, merge_tags=True)
            changed = True

        # 2) 计算“最新”的派生；如果和库里不一致则更新（解决：已打标签但 pp 仍为 0）
        fresh = compute_derived_out(m)
        need_update = (
            (not m.derived) or
            m.derived.offense != fresh["offense"] or
            m.derived.survive != fresh["survive"] or
            m.derived.control != fresh["control"] or
            m.derived.tempo != fresh["tempo"] or
            m.derived.pp_pressure != fresh["pp_pressure"]
        )
        if need_update:
            compute_and_persist(db, m)
            changed = True

        d = fresh if need_update else {
            "offense": m.derived.offense,
            "survive": m.derived.survive,
            "control": m.derived.control,
            "tempo": m.derived.tempo,
            "pp_pressure": m.derived.pp_pressure,
        }

        result.append(
            MonsterOut(
                id=m.id,
                name_final=m.name_final,
                element=m.element,
                role=m.role,
                hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
                tags=[t.name for t in (m.tags or [])],
                explain_json=m.explain_json or {},
                derived=d,
            )
        )

    if changed:
        db.commit()  # 可能写入了 derived / role / tags

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

    # 同样做一次“过期检测”
    if (not m.role) or (not m.tags):
        apply_role_tags(db, m, override_role_if_blank=True, merge_tags=True)

    fresh = compute_derived_out(m)
    if (not m.derived) or (
        m.derived.offense != fresh["offense"] or
        m.derived.survive != fresh["survive"] or
        m.derived.control != fresh["control"] or
        m.derived.tempo != fresh["tempo"] or
        m.derived.pp_pressure != fresh["pp_pressure"]
    ):
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
        },
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
        m.skills = list(skills)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    # 初次：打标签+定位，并计算派生
    recompute_and_autolabel(db, m)
    db.commit(); db.refresh(m)
    return detail(m.id, db)


@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    for k in ["name_final", "element", "role", "hp", "speed", "attack", "defense", "magic", "resist"]:
        setattr(m, k, getattr(payload, k))
    m.tags = upsert_tags(db, payload.tags or [])

    if payload.skills is not None:
        m.skills.clear()
        skills = upsert_skills(db, [(s.name, s.description or "") for s in payload.skills])
        m.skills = list(skills)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    # 更新后：按最新标签/技能重算派生
    recompute_and_autolabel(db, m)
    db.commit()
    return detail(monster_id, db)


@router.delete("/monsters/{monster_id}")
def delete(monster_id: int, db: Session = Depends(get_db)):
    """
    删除怪物时，清理关联的 skills/tags（联结表），避免残留。
    """
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    if m.skills is not None:
        m.skills.clear()
    if m.tags is not None:
        m.tags.clear()
    db.flush()

    db.delete(m)  # MonsterDerived 走 delete-orphan 一并删
    db.commit()
    return {"ok": True}


# -------- 新增：批量自动匹配（覆盖定位与标签，并重算派生） --------

class AutoMatchIn(BaseModel):
    ids: Optional[List[int]] = None


@router.post("/monsters/auto_match")
def auto_match(payload: AutoMatchIn, db: Session = Depends(get_db)):
    """
    批量“自动匹配”（重算 role/tags，并重算派生五维）。
    - 若传入 ids，仅处理这些；否则不做任何事（也可改为全量处理，看需要）
    - 行为与 /tags/monsters/{id}/retag 一致：覆盖 role，覆盖 tags（不合并）
    """
    ids = (payload.ids or [])
    if not ids:
        return {"ok": True, "updated": 0}

    mons: List[Monster] = db.execute(
        select(Monster)
        .where(Monster.id.in_(ids))
        .options(selectinload(Monster.skills), selectinload(Monster.tags))
    ).scalars().all()

    updated = 0
    for m in mons:
        # 覆盖定位与标签，然后重算派生
        apply_role_tags(db, m, override_role_if_blank=False, merge_tags=False)
        compute_and_persist(db, m)
        updated += 1

    db.commit()
    return {"ok": True, "updated": updated}