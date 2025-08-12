from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func
from typing import List, Dict

from ..db import SessionLocal
from ..models import Monster, Tag
from ..services.monsters_service import upsert_tags
from ..services.tags_service import (
    suggest_tags_for_monster,
    infer_role_for_monster,
)

router = APIRouter(prefix="/tags", tags=["tags"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# —— 简单的“标签 → 三大类”映射（和自动打标产出的标签对齐）
# 以后如果要更细，可把这段迁到 services/tags_service 里统一维护
CATEGORY_MAP: Dict[str, str] = {
    # 增强类（正向增益/能力提升）
    "高速": "增强类",
    "强攻": "增强类",
    "耐久": "增强类",
    "先手": "增强类",
    "多段": "增强类",
    "回复/增防": "增强类",

    # 削弱类（对敌负面/限制）
    "控制": "削弱类",
    "PP压制": "削弱类",
}
DEFAULT_CATEGORY = "特殊类"

def tag_category(name: str) -> str:
    return CATEGORY_MAP.get(name, DEFAULT_CATEGORY)

@router.get("")
def list_tags(with_counts: bool = Query(False), db: Session = Depends(get_db)):
    if not with_counts:
        rows = db.scalars(select(Tag.name).order_by(Tag.name.asc())).all()
        return {"items": rows}
    rows = db.execute(
        select(Tag.name, func.count())
        .select_from(Tag)
        .join(Tag.monsters, isouter=True)
        .group_by(Tag.id, Tag.name)
        .order_by(func.count().desc(), Tag.name.asc())
    ).all()
    return {"items": [{"name": n, "count": int(c)} for n, c in rows]}

@router.get("/schema")
def tag_schema():
    """
    返回三大类标签的“目录”，便于前端构建筛选/统计 UI。
    """
    groups: Dict[str, List[str]] = {"增强类": [], "削弱类": [], "特殊类": []}
    for t, cat in CATEGORY_MAP.items():
        groups.setdefault(cat, []).append(t)
    # DEFAULT_CATEGORY 不在 map 的都归到“特殊类”，此处仅返回已知映射
    for k in groups:
        groups[k] = sorted(groups[k])
    return {"groups": groups, "default": DEFAULT_CATEGORY}

@router.get("/cat_counts")
def tag_category_counts(db: Session = Depends(get_db)):
    """
    统计三大类的标签覆盖数（以标签-怪物关联条数为基数）。
    """
    rows = db.execute(
        select(Tag.name, func.count())
        .select_from(Tag)
        .join(Tag.monsters, isouter=True)
        .group_by(Tag.id, Tag.name)
    ).all()

    agg = {"增强类": 0, "削弱类": 0, "特殊类": 0}
    detail = []
    for name, cnt in rows:
        cat = tag_category(name)
        agg[cat] = agg.get(cat, 0) + int(cnt)
        detail.append({"name": name, "category": cat, "count": int(cnt)})
    # 排序一下便于阅读
    detail.sort(key=lambda x: (-x["count"], x["category"], x["name"]))
    return {"summary": agg, "detail": detail}

@router.post("/monsters/{monster_id}/suggest")
def suggest(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")
    tags = suggest_tags_for_monster(m)
    return {
        "monster_id": m.id,
        "role": infer_role_for_monster(m),
        "tags": tags,
        "categories": [{"name": t, "category": tag_category(t)} for t in tags],
    }

@router.post("/monsters/{monster_id}/retag")
def retag(monster_id: int, db: Session = Depends(get_db)):
    """
    计算并落库：role + tags
    """
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.skills), selectinload(Monster.tags))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    role = infer_role_for_monster(m)
    tags = suggest_tags_for_monster(m)
    m.role = role
    m.tags = upsert_tags(db, tags)
    db.commit()
    return {
        "ok": True,
        "monster_id": m.id,
        "role": role,
        "tags": tags,
        "categories": [{"name": t, "category": tag_category(t)} for t in tags],
    }