# server/app/routes/derived.py
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster

# 统一只依赖 derive_service（仅计算并持久化“新五轴”派生，不做自动定位/打标）
from ..services.derive_service import (
    compute_derived_out,
    recompute_derived_only,
    recompute_all,
)

router = APIRouter()

# ---------------------------
# utils
# ---------------------------

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def _monster_or_404(db: Session, monster_id: int) -> Monster:
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="monster not found")
    return m

def _derived_payload(m: Monster) -> Dict[str, object]:
    """
    统一响应结构：返回“新五轴”派生（0~120 的整数）
      - body_defense / 体防
      - body_resist  / 体抗
      - debuff_def_res / 削防抗
      - debuff_atk_mag / 削攻法
      - special_tactics / 特殊
    """
    return compute_derived_out(m)

# ---------------------------
# 单个：读取/计算（GET）
# ---------------------------

@router.get("/monsters/{monster_id}/derived")
def get_monster_derived(monster_id: int, db: Session = Depends(get_db)):
    """
    读取并返回“新五轴”派生。
    这里直接调用 recompute_derived_only，以确保落库为最新（不做自动定位/标签补齐）。
    """
    m = _monster_or_404(db, monster_id)
    recompute_derived_only(db, m, ensure_prefix_tags=False)
    db.commit()
    return _derived_payload(m)

# 兼容旧路径：/derive/{id}
@router.get("/derive/{monster_id}")
def get_derived_compat(monster_id: int, db: Session = Depends(get_db)):
    m = _monster_or_404(db, monster_id)
    recompute_derived_only(db, m, ensure_prefix_tags=False)
    db.commit()
    return _derived_payload(m)

# ---------------------------
# 单个：强制重算（POST）
# ---------------------------

@router.post("/monsters/{monster_id}/derived/recompute")
def recalc_monster(monster_id: int, db: Session = Depends(get_db)):
    """
    强制重算并落库（仅新五轴，不做自动定位/标签）。
    """
    m = _monster_or_404(db, monster_id)
    recompute_derived_only(db, m, ensure_prefix_tags=False)
    db.commit()
    return _derived_payload(m)

# 兼容旧路径：/derive/recalc/{monster_id}
@router.post("/derive/recalc/{monster_id}")
def recalc_monster_compat(monster_id: int, db: Session = Depends(get_db)):
    m = _monster_or_404(db, monster_id)
    recompute_derived_only(db, m, ensure_prefix_tags=False)
    db.commit()
    return _derived_payload(m)

# ---------------------------
# 批量：重算（POST）
# ---------------------------

from pydantic import BaseModel

class BatchIds(BaseModel):
    ids: Optional[List[int]] = None  # 缺省/空 => 全部

def _batch_recompute(ids: Optional[List[int]], db: Session) -> Dict[str, object]:
    # 取目标 id 列表
    if ids and len(ids) > 0:
        target_ids = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
        # 去重保序
        target_ids = list(dict.fromkeys(target_ids))
    else:
        target_ids = db.scalars(select(Monster.id)).all()

    success, failed = 0, 0
    details: List[Dict[str, object]] = []

    for mid in target_ids:
        m = db.get(Monster, int(mid))
        if not m:
            failed += 1
            details.append({"id": mid, "ok": False, "error": "monster not found"})
            continue
        try:
            recompute_derived_only(db, m, ensure_prefix_tags=False)
            db.commit()
            success += 1
            details.append({"id": mid, "ok": True})
        except Exception as e:
            db.rollback()
            failed += 1
            details.append({"id": mid, "ok": False, "error": str(e)})

    return {
        "ok": True,
        "total": len(target_ids),
        "success": success,
        "failed": failed,
        "details": details[:200],  # 限制返回体大小
    }

@router.post("/derived/batch")
def derived_batch(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    """
    批量重算（兼容前端“/derived/batch”调用）：
      - 未传 ids 或空数组 => 对全部 Monster 重算
      - 逐条串行 recompute_derived_only（不做定位/标签）
    """
    return _batch_recompute(payload.ids, db)

# 兼容别名：/api/v1/derived/batch
@router.post("/api/v1/derived/batch")
def derived_batch_api_v1(payload: BatchIds = Body(...), db: Session = Depends(get_db)):
    return _batch_recompute(payload.ids, db)

# ---------------------------
# 全量：重算（POST）
# ---------------------------

@router.post("/derive/recalc_all")
def recalc_all(db: Session = Depends(get_db)):
    """
    对全部 Monster 重算新五轴（不带明细）。
    """
    n = recompute_all(db)
    db.commit()
    return {"recalculated": n}