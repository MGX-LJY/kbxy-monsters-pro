# server/app/routes/tags.py
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Body
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from pydantic import BaseModel
from typing import List, Dict, Optional

from ..db import SessionLocal
from ..models import Monster, Tag
from ..services.monsters_service import upsert_tags
from ..services.tags_service import (
    # 标签建议（正则）
    suggest_tags_for_monster,
    # 标签建议（AI）
    ai_suggest_tags_for_monster,
    # —— 进度制批处理（可选）——
    start_ai_batch_tagging,
    get_ai_batch_progress,
    cancel_ai_batch,
)
# 只从 derive_service 引入“派生+定位”的入口；不再从 tags_service 引入定位函数
from ..services.derive_service import (
    recompute_and_autolabel,
    infer_role_for_monster,   # 用于 /suggest 纯建议展示；不会持久化
)

router = APIRouter(prefix="/tags", tags=["tags"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# —— 简单“标签 → 三大类”映射（供前端分组展示；与正则/AI产出无缝对齐）——
CATEGORY_MAP: Dict[str, str] = {
    # 增强类
    "高速": "增强类",
    "强攻": "增强类",
    "耐久": "增强类",
    "先手": "增强类",
    "多段": "增强类",
    "回复/增防": "增强类",
    # 削弱类
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
    groups: Dict[str, List[str]] = {"增强类": [], "削弱类": [], "特殊类": []}
    for t, cat in CATEGORY_MAP.items():
        groups.setdefault(cat, []).append(t)
    for k in groups:
        groups[k] = sorted(groups[k])
    return {"groups": groups, "default": DEFAULT_CATEGORY}


@router.get("/cat_counts")
def tag_category_counts(db: Session = Depends(get_db)):
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
# 正则打标签（不落库建议）
# ======================

@router.post("/monsters/{monster_id}/suggest")
def suggest(monster_id: int, db: Session = Depends(get_db)):
    """
    仅返回建议（不写库）：
    - tags: 正则建议标签
    - role_suggest: 通过 derive_service 的 infer_role_for_monster 得到的“建议定位”（不落库）
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")
    tags = suggest_tags_for_monster(m)
    role_suggest = infer_role_for_monster(m)
    return {
        "monster_id": m.id,
        "role_suggest": role_suggest,
        "role": getattr(m, "role", None),  # 若已有则一并返回
        "tags": tags,
        "categories": [{"name": t, "category": tag_category(t)} for t in tags],
    }


# ======================
# 正则落库（统一派生+定位）
# ======================

@router.post("/monsters/{monster_id}/retag")
def retag(monster_id: int, db: Session = Depends(get_db)):
    """
    正则计算并落库：
      1) m.tags = upsert_tags(...)
      2) recompute_and_autolabel(db, m)  → 负责派生与定位
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    tags = suggest_tags_for_monster(m)
    m.tags = upsert_tags(db, tags)

    # 统一由 derive_service 负责派生与定位写库
    recompute_and_autolabel(db, m)
    db.commit()

    return {
        "ok": True,
        "monster_id": m.id,
        "role": getattr(m, "role", None),
        "tags": tags,
        "categories": [{"name": t, "category": tag_category(t)} for t in tags],
    }


# ======================
# AI 打标签（单条，统一派生+定位）
# ======================

@router.post("/monsters/{monster_id}/retag_ai")
def retag_ai(monster_id: int, db: Session = Depends(get_db)):
    """
    AI 识别并落库：
      1) m.tags = upsert_tags(...)
      2) recompute_and_autolabel(db, m)  → 负责派生与定位
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    try:
        tags = ai_suggest_tags_for_monster(m)
    except RuntimeError as e:
        raise HTTPException(500, f"AI 标签识别失败：{e}")

    m.tags = upsert_tags(db, tags)
    recompute_and_autolabel(db, m)
    db.commit()

    return {
        "ok": True,
        "monster_id": m.id,
        "role": getattr(m, "role", None),
        "tags": tags,
    }


# ======================
# AI 批量（同步版，便于一键处理；统一派生+定位）
# ======================

class BatchIds(BaseModel):
    ids: Optional[List[int]] = None  # 为空或缺省 => 对全部怪物执行

@router.post("/ai/batch")
def ai_batch(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    """
    同步批量 AI 打标签：
      - 未传 ids 或传空数组 => 对全部 Monster
      - 对每个目标：
          m.tags = upsert_tags(...)
          recompute_and_autolabel(db, m)
      - 返回成功/失败明细（最多 200 条）
    """
    if payload.ids:
        ids = list({int(i) for i in payload.ids if isinstance(i, int)})
    else:
        ids = db.scalars(select(Monster.id)).all()

    success = 0
    failed = 0
    details = []

    for mid in ids:
        try:
            m = db.execute(select(Monster).where(Monster.id == mid)).scalar_one_or_none()
            if not m:
                failed += 1
                details.append({"id": mid, "ok": False, "error": "monster not found"})
                continue
            tags = ai_suggest_tags_for_monster(m)
            m.tags = upsert_tags(db, tags)
            recompute_and_autolabel(db, m)
            db.commit()
            success += 1
            details.append({"id": mid, "ok": True, "role": getattr(m, "role", None), "tags": tags})
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

# 兼容别名（曾请求过 /api/v1/tags/ai/batch）
@router.post("/ai_batch")
def ai_batch_alias(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    return ai_batch(payload, db)


# ======================
# （可选）AI 批量：进度制后台任务 + 轮询
# ======================
#
# 若前端要显示“实时进度条”，推荐使用这组三个接口：
# - POST   /tags/ai_batch/start         → 返回 job_id
# - GET    /tags/ai_batch/{job_id}      → 轮询进度
# - POST   /tags/ai_batch/{job_id}/cancel → 取消
#
# 说明：
# - 具体打标逻辑在 tags_service.start_ai_batch_tagging 的后台线程中实现；
# - 那里默认只更新 tags，你也可以把 recompute_and_autolabel 加到 worker 内（在 tags_service 中改）。
# - 这三接口纯粹是状态管理/查询，不会阻塞主线程。

class BatchStartBody(BaseModel):
    ids: Optional[List[int]] = None

@router.post("/ai_batch/start")
def ai_batch_start(body: BatchStartBody = Body(...)):
    job_id = start_ai_batch_tagging(body.ids or [], db_factory=SessionLocal)
    return {"ok": True, "job_id": job_id}

@router.get("/ai_batch/{job_id}")
def ai_batch_progress(job_id: str):
    st = get_ai_batch_progress(job_id)
    if not st:
        raise HTTPException(404, "job not found")
    return st

@router.post("/ai_batch/{job_id}/cancel")
def ai_batch_cancel(job_id: str):
    ok = cancel_ai_batch(job_id)
    if not ok:
        raise HTTPException(404, "job not found or already finished")
    return {"ok": True, "job_id": job_id}