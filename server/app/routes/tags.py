# server/app/routes/tags.py
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session  # 关键：不再引入 selectinload
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import List, Dict, Optional

from ..db import SessionLocal
from ..models import Monster, Tag
from ..services.monsters_service import upsert_tags
from ..services.tags_service import (
    # 正则方案（默认）
    suggest_tags_for_monster,
    infer_role_for_monster,
    # AI 方案（独立接口）
    ai_suggest_tags_for_monster,
)

router = APIRouter(prefix="/tags", tags=["tags"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# —— 简单的“标签 → 三大类”映射（用于前端分类展示；与自动打标产出对齐）
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
        .join(Tag.monsters, isouter=True)   # 这里假定 Tag.monsters 是 relationship（不是 association proxy）
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
    detail.sort(key=lambda x: (-x["count"], x["category"], x["name"]))
    return {"summary": agg, "detail": detail}

# ======================
# 正则打标签（默认路径）
# ======================

@router.post("/monsters/{monster_id}/suggest")
def suggest(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster).where(Monster.id == monster_id)
        # 不要对 association_proxy 使用任何 loader 选项；让它 lazy-load
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
    正则计算并落库：role + tags
    修复点：移除对 association_proxy 的 selectinload。
    """
    m = db.execute(
        select(Monster).where(Monster.id == monster_id)
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    role = infer_role_for_monster(m)
    tags = suggest_tags_for_monster(m)
    m.role = role
    m.tags = upsert_tags(db, tags)  # 这里假定 upsert_tags 返回 Tag 对象列表
    db.commit()
    return {
        "ok": True,
        "monster_id": m.id,
        "role": role,
        "tags": tags,
        "categories": [{"name": t, "category": tag_category(t)} for t in tags],
    }

# ======================
# AI 打标签（独立接口；不回退正则）
# ======================

class BatchIds(BaseModel):
    ids: Optional[List[int]] = None  # 为空或缺省 => 对全部怪物执行

@router.post("/monsters/{monster_id}/retag_ai")
def retag_ai(monster_id: int, db: Session = Depends(get_db)):
    """
    AI 识别并落库，仅更新 tags（role 仍使用正则/另行派生）。
    """
    m = db.execute(
        select(Monster).where(Monster.id == monster_id)
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    try:
        tags = ai_suggest_tags_for_monster(m)
    except RuntimeError as e:
        raise HTTPException(500, f"AI 标签识别失败：{e}")

    m.tags = upsert_tags(db, tags)
    db.commit()
    return {
        "ok": True,
        "monster_id": m.id,
        "tags": tags,
    }

@router.post("/ai/batch")
def ai_batch(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    """
    批量 AI 打标签（无进度接口；前端可用全屏模糊遮罩即可）：
    - 未传 ids 或传空数组 => 对全部 Monster 执行
    - 串行处理；返回成功/失败明细
    """
    ids: List[int]
    if payload.ids:
        ids = list({int(i) for i in payload.ids if isinstance(i, int)})
    else:
        ids = db.scalars(select(Monster.id)).all()

    success = 0
    failed = 0
    details = []

    for mid in ids:
        m = db.execute(
            select(Monster).where(Monster.id == mid)
        ).scalar_one_or_none()
        if not m:
            failed += 1
            details.append({"id": mid, "ok": False, "error": "monster not found"})
            continue
        try:
            tags = ai_suggest_tags_for_monster(m)
            m.tags = upsert_tags(db, tags)
            db.commit()
            success += 1
            details.append({"id": mid, "ok": True, "tags": tags})
        except Exception as e:
            db.rollback()
            failed += 1
            details.append({"id": mid, "ok": False, "error": str(e)})

    return {
        "ok": True,
        "total": len(ids),
        "success": success,
        "failed": failed,
        "details": details[:200],
    }

# 兼容别名（曾请求过 /tags/ai_batch）
@router.post("/ai_batch")
def ai_batch_alias(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    return ai_batch(payload, db)