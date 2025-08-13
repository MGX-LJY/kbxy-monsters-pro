# server/app/routes/monsters.py
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster
from ..schemas import MonsterIn, MonsterOut, MonsterList  # 假定已将 name_final 改为 name，并补充新字段
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills
from ..services.derive_service import (
    compute_derived_out,
    compute_and_persist,
    recompute_and_autolabel,
    apply_role_tags,
)
from ..services.tags_service import (
    suggest_tags_for_monster,
    infer_role_for_monster,
)

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---------- 请求体验证 ----------
class RawStatsIn(BaseModel):
    hp: float = Field(..., description="体力")
    speed: float = Field(..., description="速度")
    attack: float = Field(..., description="攻击")
    defense: float = Field(..., description="防御")
    magic: float = Field(..., description="法术")
    resist: float = Field(..., description="抗性")

class AutoMatchIdsIn(BaseModel):
    ids: List[int]

class SkillOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    description: Optional[str] = None

class SkillIn(BaseModel):
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    description: Optional[str] = None
    selected: Optional[bool] = None  # 若关联表支持，可写入；否则忽略

# ---------- 列表 ----------
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

    # 预加载集合，避免 N+1
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
        # 若缺 role / tags，自动补齐
        if (not m.role) or (not m.tags):
            apply_role_tags(db, m, override_role_if_blank=True, merge_tags=True)
            changed = True

        # 保证派生是最新
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
                name=m.name,
                element=m.element,
                role=m.role,
                hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
                possess=getattr(m, "possess", None),
                new_type=getattr(m, "new_type", None),
                type=getattr(m, "type", None),
                method=getattr(m, "method", None),
                tags=[t.name for t in (m.tags or [])],
                explain_json=m.explain_json or {},
                created_at=getattr(m, "created_at", None),
                updated_at=getattr(m, "updated_at", None),
                derived=d,
            )
        )

    if changed:
        db.commit()

    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}

# ---------- 详情 ----------
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

    # 缺失信息自动补
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
        id=m.id, name=m.name, element=m.element, role=m.role,
        hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
        possess=getattr(m, "possess", None),
        new_type=getattr(m, "new_type", None),
        type=getattr(m, "type", None),
        method=getattr(m, "method", None),
        tags=[t.name for t in (m.tags or [])],
        explain_json=m.explain_json or {},
        created_at=getattr(m, "created_at", None),
        updated_at=getattr(m, "updated_at", None),
        derived={
            "offense": m.derived.offense,
            "survive": m.derived.survive,
            "control": m.derived.control,
            "tempo": m.derived.tempo,
            "pp_pressure": m.derived.pp_pressure,
        },
    )

# ---------- 只读：当前怪物的技能列表（前端抽屉使用） ----------
@router.get("/monsters/{monster_id}/skills", response_model=List[SkillOut])
def monster_skills(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 直接回传全局 Skill 字段（若需要关联描述/selected，可扩展 MonsterSkill 读取）
    return [
        SkillOut(
            id=s.id,
            name=s.name,
            element=getattr(s, "element", None),
            kind=getattr(s, "kind", None),
            power=getattr(s, "power", None),
            description=s.description or None
        )
        for s in (m.skills or [])
    ]

# ---------- 写入：覆盖（或更新）怪物的技能集合 ----------
@router.put("/monsters/{monster_id}/skills")
def put_monster_skills(monster_id: int, payload: List[SkillIn], db: Session = Depends(get_db)):
    """
    用唯一键 (name, element, kind, power) upsert 技能并更新怪物关联。
    - 若存在显式关联模型 MonsterSkill：逐条 upsert 关联（并可写 selected/关联描述等）
    - 否则 fallback 用 m.skills 多对多集合维护
    """
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 1) upsert 全局技能
    items = [
        (it.name, (it.element or ""), (it.kind or ""), (it.power if it.power is not None else None), (it.description or ""))
        for it in (payload or [])
    ]
    skills = upsert_skills(db, items)  # 返回 Skill 实体列表
    db.flush()

    # 2) 更新/替换关联
    changed = False
    if hasattr(m, "skills") and m.skills is not None:
        # 清空再设（也可 diff 更新，这里简单处理）
        m.skills.clear()
        for s in skills:
            m.skills.append(s)
        changed = True

    # 2.1 若存在 MonsterSkill 关联模型，确保二元唯一并可写 selected
    if hasattr(__import__("server.app.models", fromlist=[""]), "MonsterSkill") or hasattr(m, "monster_skills"):
        try:
            from .. import models as M  # 延迟导入，避免循环
            for s_in in payload:
                # 找到 upsert_skills 返回的对应实体
                sk = next((x for x in skills if x.name == s_in.name
                           and getattr(x, "element", None) == (s_in.element or "")
                           and getattr(x, "kind", None) == (s_in.kind or "")
                           and getattr(x, "power", None) == s_in.power), None)
                if not sk:
                    continue
                ms = (
                    db.query(M.MonsterSkill)
                    .filter(M.MonsterSkill.monster_id == m.id, M.MonsterSkill.skill_id == sk.id)
                    .first()
                )
                if not ms:
                    ms = M.MonsterSkill(monster_id=m.id, skill_id=sk.id)
                    db.add(ms)
                    changed = True
                # 可选字段：selected
                if hasattr(ms, "selected") and (s_in.selected is not None):
                    if ms.selected != s_in.selected:
                        ms.selected = s_in.selected
                        changed = True
        except Exception:
            # 若导入失败，则忽略显式关联模型写入，以上 m.skills 已覆盖
            pass

    if changed:
        db.flush()

    # 3) 更新 explain_json 里技能名快照
    ex = m.explain_json or {}
    ex["skill_names"] = [s.name for s in (m.skills or [])]
    m.explain_json = ex

    # 4) 重新自动打 role/tags，并重算派生
    recompute_and_autolabel(db, m)
    db.commit()
    return {"ok": True, "monster_id": m.id, "skills": [s.name for s in (m.skills or [])]}

# ---------- 保存原始六维（列 + explain_json.raw_stats + 立刻重算派生） ----------
@router.put("/monsters/{monster_id}/raw_stats")
def save_raw_stats(monster_id: int, payload: RawStatsIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 1) 写列
    m.hp = float(payload.hp)
    m.speed = float(payload.speed)
    m.attack = float(payload.attack)
    m.defense = float(payload.defense)
    m.magic = float(payload.magic)
    m.resist = float(payload.resist)

    # 2) 写 explain_json.raw_stats
    ex = m.explain_json or {}
    ex["raw_stats"] = {
        "hp": float(payload.hp),
        "speed": float(payload.speed),
        "attack": float(payload.attack),
        "defense": float(payload.defense),
        "magic": float(payload.magic),
        "resist": float(payload.resist),
        "sum": float(payload.hp + payload.speed + payload.attack + payload.defense + payload.magic + payload.resist),
    }
    m.explain_json = ex

    # 3) 重算派生
    compute_and_persist(db, m)

    db.commit()
    return {"ok": True, "monster_id": m.id}

# ---------- 派生 + 建议（供前端“填充”） ----------
@router.get("/monsters/{monster_id}/derived")
def derived_suggestions(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    role_suggested = infer_role_for_monster(m)
    tags_suggested = suggest_tags_for_monster(m)
    derived_now = compute_derived_out(m)

    return {
        "monster_id": m.id,
        "role_suggested": role_suggested,
        "tags": tags_suggested,
        "derived": derived_now,
    }

# ---------- 批量自动匹配（打 role/tags 并重算派生；不改技能） ----------
@router.post("/monsters/auto_match")
def auto_match(body: AutoMatchIdsIn, db: Session = Depends(get_db)):
    if not body.ids:
        return {"ok": True, "processed": 0}

    mons = db.execute(
        select(Monster)
        .where(Monster.id.in_(body.ids))
        .options(selectinload(Monster.skills), selectinload(Monster.tags), selectinload(Monster.derived))
    ).scalars().all()

    n = 0
    for m in mons:
        apply_role_tags(db, m, override_role_if_blank=True, merge_tags=True)
        compute_and_persist(db, m)
        n += 1

    db.commit()
    return {"ok": True, "processed": n}

# ---------- 创建 ----------
@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    m = Monster(
        name=payload.name,
        element=payload.element,
        role=payload.role,
        hp=payload.hp, speed=payload.speed, attack=payload.attack,
        defense=payload.defense, magic=payload.magic, resist=payload.resist,
        possess=getattr(payload, "possess", None),
        new_type=getattr(payload, "new_type", None),
        type=getattr(payload, "type", None),
        method=getattr(payload, "method", None),
        explain_json=getattr(payload, "explain_json", None),
    )
    m.tags = upsert_tags(db, payload.tags or [])
    db.add(m); db.flush()

    # skills（可选）
    if getattr(payload, "skills", None):
        items = [
            (s.name, (s.element or ""), (s.kind or ""), (s.power if s.power is not None else None), (s.description or ""))
            for s in payload.skills
        ]
        skills = upsert_skills(db, items)
        m.skills = list(skills)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in m.skills]
        m.explain_json = ex

    # 初次：打标签+定位，并计算派生
    recompute_and_autolabel(db, m)
    db.commit(); db.refresh(m)
    return detail(m.id, db)

# ---------- 更新（只有显式提供 skills 字段才会改技能；否则不动） ----------
@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 写基础字段（按新模型）
    for k in ["name", "element", "role", "hp", "speed", "attack", "defense", "magic", "resist",
              "possess", "new_type", "type", "method"]:
        if hasattr(payload, k):
            setattr(m, k, getattr(payload, k))

    # 写 explain_json（可选整体替换）
    if hasattr(payload, "explain_json") and (payload.explain_json is not None):
        m.explain_json = payload.explain_json

    # 写标签
    m.tags = upsert_tags(db, payload.tags or [])

    # —— 关键：只有当请求体“显式包含 skills 字段”时才更新技能 —— #
    skills_field_provided = hasattr(payload, "model_fields_set") and ("skills" in payload.model_fields_set)
    if skills_field_provided:
        m.skills.clear()
        if getattr(payload, "skills", None):
            items = [
                (s.name, (s.element or ""), (s.kind or ""), (s.power if s.power is not None else None), (s.description or ""))
                for s in payload.skills
            ]
            skills = upsert_skills(db, items)
            m.skills = list(skills)
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in (m.skills or [])]
        m.explain_json = ex

    # 更新后：按最新标签/技能重算派生
    recompute_and_autolabel(db, m)
    db.commit()
    return detail(monster_id, db)

# ---------- 删除 ----------
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