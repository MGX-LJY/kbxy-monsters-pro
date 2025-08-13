# server/app/routes/derived.py
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster

# 统一只依赖 derive_service（内部已整合派生+定位）
from ..services.derive_service import (
    compute_derived_out,
    recompute_and_autolabel,
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
    统一响应结构：
      - 五维派生：offense/survive/control/tempo/pp_pressure
      - role_suggested：当前落库到 monster.role（与 derived.role_suggested 语义一致）
      - tags：当前落库后的标签名列表
    """
    out = compute_derived_out(m)  # dict[int]
    # role：由 derive_service.apply_role_tags / recompute_and_autolabel 负责写入
    role = getattr(m, "role", None) or getattr(getattr(m, "derived", None), "role_suggested", None)
    tags = [t.name for t in (getattr(m, "tags", None) or []) if getattr(t, "name", None)]
    return {
        **out,
        "role_suggested": role,
        "tags": tags,
    }

# ---------------------------
# 单个：读取/计算（GET）
# ---------------------------

@router.get("/monsters/{monster_id}/derived")
def get_monster_derived(monster_id: int, db: Session = Depends(get_db)):
    """
    读取并返回派生五维 + 定位 + 标签。
    这里直接调用 recompute_and_autolabel，以保证 role/tag 与派生一致（并写库）。
    """
    m = _monster_or_404(db, monster_id)
    recompute_and_autolabel(db, m)   # 统一在服务层完成：派生 + 定位 +（必要时）标签合并
    db.commit()
    return _derived_payload(m)

# 兼容旧路径：/derive/{id}
@router.get("/derive/{monster_id}")
def get_derived_compat(monster_id: int, db: Session = Depends(get_db)):
    m = _monster_or_404(db, monster_id)
    recompute_and_autolabel(db, m)
    db.commit()
    return _derived_payload(m)

# ---------------------------
# 单个：强制重算（POST）
# ---------------------------

@router.post("/monsters/{monster_id}/derived/recompute")
def recalc_monster(monster_id: int, db: Session = Depends(get_db)):
    """
    强制重算并落库（派生 + 定位 + 标签）。
    """
    m = _monster_or_404(db, monster_id)
    recompute_and_autolabel(db, m)
    db.commit()
    return _derived_payload(m)

# 兼容旧路径：/derive/recalc/{id}
@router.post("/derive/recalc/{monster_id}")
def recalc_monster_compat(monster_id: int, db: Session = Depends(get_db)):
    m = _monster_or_404(db, monster_id)
    recompute_and_autolabel(db, m)
    db.commit()
    return _derived_payload(m)

# ---------------------------
# 批量：重算（POST）
# ---------------------------

class BatchIdsIn(BaseException):
    pass

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
            recompute_and_autolabel(db, m)
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
      - 逐条串行 recompute_and_autolabel，保证 role 与 tags 与派生一致
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
    对全部 Monster 重算（不带明细）。
    """
    n = recompute_all(db)
    db.commit()
    return {"recalculated": n}