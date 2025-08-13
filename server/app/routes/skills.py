# server/app/routes/skills.py
from __future__ import annotations

from typing import List, Optional, Dict
from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import select, func

from ..db import SessionLocal
from ..models import Monster, Skill, MonsterSkill  # 确保这些模型存在

router = APIRouter(prefix="", tags=["skills"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# ---- 输入模型 ----
class SkillBasicIn(BaseModel):
    name: str = Field(..., min_length=1)
    description: Optional[str] = None

class SkillSetIn(BaseModel):
    skills: List[SkillBasicIn]

# ---- 获取某怪物的技能列表（给前端详情展示）----
@router.get("/monsters/{monster_id}/skills")
def list_monster_skills(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(
            # 关键修复：不要加载 Monster.skills（association proxy），而是加载关系表再 joinedload 到 Skill
            selectinload(Monster.monster_skills).joinedload(MonsterSkill.skill)
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")

    out = []
    for ms in (m.monster_skills or []):
        # 兼容：Skill 上的 element/kind/power，关联表上保留 description
        s = ms.skill
        out.append({
            "id": ms.id,
            "name": s.name if s else "",
            "element": getattr(s, "element", None),
            "kind": getattr(s, "kind", None),
            "power": getattr(s, "power", None),
            "description": ms.description or getattr(s, "description", None) or "",
        })
    return out

# 内部：根据名称查找或新建 Skill
def _get_or_create_skill(db: Session, name: str) -> Skill:
    sk = db.execute(select(Skill).where(Skill.name == name)).scalar_one_or_none()
    if sk:
        return sk
    sk = Skill(name=name)  # 只按名字新建；其它字段保留空，后续有爬虫/管理再补
    db.add(sk)
    db.flush()
    return sk

# ---- 设置/覆盖一个怪物的技能集合（PUT/POST 都支持）----
def _set_monster_skills(db: Session, monster_id: int, payload: SkillSetIn):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(
            selectinload(Monster.monster_skills).joinedload(MonsterSkill.skill)
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")

    # 归一化输入（去空名、去重）
    desired: Dict[str, str] = {}
    for item in payload.skills or []:
        n = (item.name or "").strip()
        if not n:
            continue
        if n not in desired:
            desired[n] = (item.description or "").strip()

    # 现有关联
    existing_by_name: Dict[str, MonsterSkill] = {}
    for ms in (m.monster_skills or []):
        if ms.skill:
            existing_by_name[ms.skill.name] = ms

    # 需要删除的
    to_delete = [ms for name, ms in existing_by_name.items() if name not in desired]
    for ms in to_delete:
        db.delete(ms)

    # 新增/更新
    for name, desc in desired.items():
        if name in existing_by_name:
            ms = existing_by_name[name]
            # 更新描述（放在关联表上，互不影响 Skill 的通用字段）
            ms.description = desc
        else:
            s = _get_or_create_skill(db, name)
            ms = MonsterSkill(monster_id=m.id, skill_id=s.id, description=desc)
            db.add(ms)

    db.commit()

@router.put("/monsters/{monster_id}/skills")
def put_monster_skills(monster_id: int, body: SkillSetIn = Body(...), db: Session = Depends(get_db)):
    _set_monster_skills(db, monster_id, body)
    return {"ok": True}

# 兼容：POST 也可用
@router.post("/monsters/{monster_id}/skills")
def post_monster_skills(monster_id: int, body: SkillSetIn = Body(...), db: Session = Depends(get_db)):
    _set_monster_skills(db, monster_id, body)
    return {"ok": True}