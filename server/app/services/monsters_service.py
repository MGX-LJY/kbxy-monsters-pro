# server/app/services/monsters_service.py
from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import select, func, asc, desc, outerjoin

from ..models import Monster, Tag, MonsterDerived


# ---- 排序字段解析：支持派生五维（pp / pp_pressure 都支持） ----

def _get_sort_target(sort: str):
    s = (sort or "updated_at").lower()
    md = MonsterDerived
    m = Monster
    derived_map = {
        "offense": md.offense,
        "survive": md.survive,
        "control": md.control,
        "tempo": md.tempo,
        "pp_pressure": md.pp_pressure,
        "pp": md.pp_pressure,  # 别名
    }
    if s in derived_map:
        return derived_map[s], True
    if s == "name":
        return m.name, False
    if s == "element":
        return m.element, False
    if s == "role":
        return m.role, False
    return m.updated_at, False


# ---- 列表查询：可按标签/元素/定位/获取途径/是否可获取 过滤；按派生或更新时间排序 ----

def list_monsters(
    db: Session,
    *,
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    acq_type: Optional[str] = None,      # ← 获取途径：Monster.type
    new_type: Optional[bool] = None,     # ← 是否当前可获取：Monster.new_type
    sort: Optional[str] = None,
    order: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Monster], int]:
    """
    说明：
      - 若需“按技能文本过滤”，建议在路由层构造子查询，避免计数笛卡尔积。
      - 这里统一支持 type/new_type 过滤，以契合前端“获取途径/可获取”的 UI。
    """
    # 计数子查询（避免 JOIN 计数膨胀）
    base_stmt = select(Monster.id)
    if tag:
        base_stmt = base_stmt.join(Monster.tags).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        base_stmt = base_stmt.where(Monster.name.like(like))

    if element:
        base_stmt = base_stmt.where(Monster.element == element)
    if role:
        base_stmt = base_stmt.where(Monster.role == role)
    if acq_type:
        base_stmt = base_stmt.where(Monster.type == acq_type)
    if isinstance(new_type, bool):
        base_stmt = base_stmt.where(Monster.new_type == new_type)

    sort_col, need_join = _get_sort_target(sort or "updated_at")
    if need_join:
        base_stmt = base_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    subq = base_stmt.subquery()
    total = db.scalar(select(func.count()).select_from(subq)) or 0

    # 取行
    rows_stmt = select(Monster)
    if tag:
        rows_stmt = rows_stmt.join(Monster.tags).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        rows_stmt = rows_stmt.where(Monster.name.like(like))

    if element:
        rows_stmt = rows_stmt.where(Monster.element == element)
    if role:
        rows_stmt = rows_stmt.where(Monster.role == role)
    if acq_type:
        rows_stmt = rows_stmt.where(Monster.type == acq_type)
    if isinstance(new_type, bool):
        rows_stmt = rows_stmt.where(Monster.new_type == new_type)

    if need_join:
        rows_stmt = rows_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    is_asc = (order or "desc").lower() == "asc"
    rows_stmt = rows_stmt.order_by(asc(sort_col) if is_asc else desc(sort_col))
    rows_stmt = rows_stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.scalars(rows_stmt).unique().all()
    return rows, int(total)


# ---- 标签 upsert（保持返回 Tag 实体列表） ----

def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    """
    将一维标签名写入 Tag 表后返回 Tag 实体列表；
    调用方应保证 names 已经是新三类规范化的代码（buf_/deb_/util_）。
    """
    result: List[Tag] = []
    uniq, seen = [], set()
    for s in names or []:
        n = (s or "").strip()
        if not n or n in seen:
            continue
        seen.add(n)
        uniq.append(n)
    for n in uniq:
        tag = db.execute(select(Tag).where(Tag.name == n)).scalar_one_or_none()
        if not tag:
            tag = Tag(name=n)
            db.add(tag)
            db.flush()
        result.append(tag)
    return result


# ---- 设置标签即派生：统一依赖 derive_service，避免旧 infer_role_for_monster ----

def set_tags_and_rederive(
    db: Session,
    monster: Monster,
    names: List[str],
    *,
    commit: bool = True,
) -> None:
    """
    写入规范化标签并立刻调用 recompute_and_autolabel：
      - 会更新 monster.tags
      - 会计算派生五维与定位（monster.role / derived.*）
    """
    from .derive_service import recompute_and_autolabel  # 延迟导入，避免循环依赖
    monster.tags = upsert_tags(db, names or [])
    recompute_and_autolabel(db, monster)
    if commit:
        db.commit()


# ---- 批量“自动匹配”：用正则建议标签 → set_tags_and_rederive ----

def auto_match_monsters(
    db: Session,
    *,
    ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    对给定 id 列表（为空则全量）执行：
      suggest_tags_for_monster -> set_tags_and_rederive
    返回处理统计与前 200 条明细。
    """
    from .tags_service import suggest_tags_for_monster  # 延迟导入，避免循环依赖

    if ids:
        id_list = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
        id_list = list(dict.fromkeys(id_list))
    else:
        id_list = db.scalars(select(Monster.id)).all()

    success = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    for mid in id_list:
        m = db.get(Monster, int(mid))
        if not m:
            failed += 1
            details.append({"id": mid, "ok": False, "error": "monster not found"})
            continue
        try:
            tags = suggest_tags_for_monster(m)
            set_tags_and_rederive(db, m, tags, commit=False)
            success += 1
            details.append({"id": mid, "ok": True, "tags": tags})
        except Exception as e:
            db.rollback()
            failed += 1
            details.append({"id": mid, "ok": False, "error": str(e)})

    db.commit()
    return {
        "ok": True,
        "total": len(id_list),
        "success": success,
        "failed": failed,
        "details": details[:200],
    }