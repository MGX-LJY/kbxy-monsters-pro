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
    # —— 正则/AI 建议 —— #
    suggest_tags_for_monster,
    ai_suggest_tags_for_monster,
    # —— 批处理进度制（可选）—— #
    start_ai_batch_tagging,
    get_ai_batch_progress,
    cancel_ai_batch,
    # —— 词表 & 正则热更新 / i18n —— #
    load_catalog,          # 热加载 tags_catalog.json （实现于 tags_service）
    get_i18n_map,          # 返回 {code: "中文"} 映射（实现于 tags_service）
)

router = APIRouter(prefix="/tags", tags=["tags"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 依据 code 前缀分组，供 /schema 与统计使用
def _code_category(code: str) -> str:
    if isinstance(code, str):
        if code.startswith("buf_"):
            return "增强类"
        if code.startswith("deb_"):
            return "削弱类"
        if code.startswith("util_"):
            return "特殊类"
    return "特殊类"

# ======================
# 基础：列表 & 统计（返回的都是“代码”）
# ======================

@router.get("")
def list_tags(with_counts: bool = Query(False), db: Session = Depends(get_db)):
    """
    返回标签代码（Tag.name 存的是 code）。
    前端如需中文展示，请调用 GET /tags/i18n。
    """
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

@router.get("/cat_counts")
def tag_category_counts(db: Session = Depends(get_db)):
    """
    统计三大类覆盖数（基于 Tag-怪物关联条数）。
    """
    rows = db.execute(
        select(Tag.name, func.count())
        .select_from(Tag)
        .join(Tag.monsters, isouter=True)
        .group_by(Tag.id, Tag.name)
    ).all()

    agg = {"增强类": 0, "削弱类": 0, "特殊类": 0}
    detail = []
    for code, cnt in rows:
        cat = _code_category(code)
        agg[cat] = agg.get(cat, 0) + int(cnt)
        detail.append({"code": code, "category": cat, "count": int(cnt)})
    detail.sort(key=lambda x: (-x["count"], x["category"], x["code"]))
    return {"summary": agg, "detail": detail}

# ======================
# 词表 & 正则：i18n / schema / 热更新
# ======================

@router.get("/i18n")
def get_i18n():
    """
    返回 {code: '中文名'} 的映射，来自 tags_catalog.json。
    前端应据此展示中文（而不是写死在前端）。
    """
    return {"i18n": get_i18n_map()}

@router.get("/schema")
def tag_schema():
    """
    返回三大类的“目录”（按 code 前缀划分）。
    groups: Dict[str, List[str]] —— 分组内是 code（非中文）
    default: 默认分组名
    """
    i18n = get_i18n_map() or {}
    groups: Dict[str, List[str]] = {"增强类": [], "削弱类": [], "特殊类": []}
    for code in sorted(i18n.keys()):
        groups[_code_category(code)].append(code)
    return {"groups": groups, "default": "特殊类"}

@router.post("/catalog/reload")
def reload_catalog():
    """
    热加载 tags_catalog.json（正则与 i18n 都会更新）。
    """
    try:
        res = load_catalog(force=True)  # 具体返回值由 tags_service 决定；这里透传/兜底
        return {"ok": True, "detail": res or "reloaded"}
    except Exception as e:
        raise HTTPException(500, f"reload catalog failed: {e}")

# ======================
# 正则打标签（不落库建议）
# ======================

@router.post("/monsters/{monster_id}/suggest")
def suggest(monster_id: int, db: Session = Depends(get_db)):
    """
    仅返回建议（不写库）：
    - tags: 正则建议标签（代码）
    - derived_preview: 当前怪以现有数据计算的“新五轴派生”（0~120 整数），方便前端展示
    - i18n: 附带 code→中文映射，前端可以直接用
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")
    tags = suggest_tags_for_monster(m)
    derived_preview = {}
    return {
        "monster_id": m.id,
        "tags": tags,                 # code list
        "derived_preview": derived_preview,
        "i18n": get_i18n_map(),       # 前端据此渲染中文
    }

# ======================
# 正则落库（写库 + 仅派生，不做定位）
# ======================

@router.post("/monsters/{monster_id}/retag")
def retag(monster_id: int, db: Session = Depends(get_db)):
    """
    正则计算并落库：
      m.tags = upsert_tags(...)
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    tags = suggest_tags_for_monster(m)
    m.tags = upsert_tags(db, tags)

    db.commit()

    return {
        "ok": True,
        "monster_id": m.id,
        "tags": tags,                       # code list
        "derived": {},  # 0~120
        "i18n": get_i18n_map(),             # 便于前端立即显示
    }

# ======================
# AI 打标签（单条，写库 + 仅派生）
# ======================

@router.post("/monsters/{monster_id}/retag_ai")
def retag_ai(monster_id: int, db: Session = Depends(get_db)):
    """
    AI 识别并落库（内部已做审计/修复/自由候选写盘——见 tags_service）：
      m.tags = upsert_tags(...)
    """
    m = db.execute(select(Monster).where(Monster.id == monster_id)).scalar_one_or_none()
    if not m:
        raise HTTPException(404, "monster not found")

    try:
        tags = ai_suggest_tags_for_monster(m)  # 内部完成审计/落盘 JSON
    except RuntimeError as e:
        raise HTTPException(500, f"AI 标签识别失败：{e}")

    m.tags = upsert_tags(db, tags)
    db.commit()

    return {
        "ok": True,
        "monster_id": m.id,
        "tags": tags,
        "derived": {},
        "i18n": get_i18n_map(),
    }

# ======================
# AI 批量（同步版）
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
            db.commit()
            success += 1
            details.append({
                "id": mid,
                "ok": True,
                "tags": tags,
                "derived": {},
            })
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
        "i18n": get_i18n_map(),
    }

# ======================
# （可选）AI 批量：进度制后台任务 + 轮询
# ======================

class BatchStartBody(BaseModel):
    ids: Optional[List[int]] = None

@router.post("/ai_batch/start")
def ai_batch_start(body: BatchStartBody = Body(...), db: Session = Depends(get_db)):
    # 与同步版本保持一致：空列表时处理全部怪物
    if body.ids:
        ids = list({int(i) for i in body.ids if isinstance(i, int)})
    else:
        ids = db.scalars(select(Monster.id)).all()
    
    job_id = start_ai_batch_tagging(ids, db_factory=SessionLocal)
    return {"ok": True, "job_id": job_id, "total_monsters": len(ids)}

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