# server/app/services/warehouse_service.py
from __future__ import annotations

from typing import Iterable, List, Tuple, Optional

from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, asc, desc, or_

from ..models import Monster, MonsterSkill, Skill, Tag, MonsterDerived
from ..services.derive_service import compute_derived_out, compute_and_persist


# -------- 基础操作：加入/移出/批量设置 --------
def add_to_warehouse(db: Session, monster_id: int) -> bool:
    m = db.get(Monster, monster_id)
    if not m:
        return False
    if not getattr(m, "possess", False):
        m.possess = True
        db.flush()
    return True


def remove_from_warehouse(db: Session, monster_id: int) -> bool:
    m = db.get(Monster, monster_id)
    if not m:
        return False
    if getattr(m, "possess", False):
        m.possess = False
        db.flush()
    return True


def bulk_set_warehouse(db: Session, ids: Iterable[int], possess: bool) -> int:
    """
    批量设置 possess；返回实际变更的数量。
    """
    changed = 0
    uniq_ids = list({int(i) for i in (ids or [])})
    if not uniq_ids:
        return 0
    for mid in uniq_ids:
        m = db.get(Monster, mid)
        if not m:
            continue
        if bool(getattr(m, "possess", False)) != possess:
            m.possess = possess
            changed += 1
    if changed:
        db.flush()
    return changed


# -------- 统计 --------
def warehouse_stats(db: Session) -> dict:
    total = db.scalar(select(func.count(Monster.id))) or 0
    owned = db.scalar(select(func.count(Monster.id)).where(Monster.possess.is_(True))) or 0
    not_owned = int(total) - int(owned)
    # 保留兼容字段 in_warehouse
    return {
        "total": int(total),
        "owned_total": int(owned),
        "not_owned_total": int(not_owned),
        "in_warehouse": int(owned),
    }


# -------- 仓库/拥有过滤列表（支持 possess=True/False/None） --------
def list_warehouse(
    db: Session,
    *,
    possess: Optional[bool] = True,         # True=仅已拥有；False=仅未拥有；None=全部
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    tag: Optional[str] = None,
    tags_all: Iterable[str] | None = None,  # 多标签 AND
    type: Optional[str] = None,             # 获取渠道（兼容）
    acq_type: Optional[str] = None,         # 获取渠道（兼容）
    sort: str = "updated_at",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Monster], int]:
    """
    支持按 possess 过滤：
      - possess=True  ：仅返回在仓库中的怪（Monster.possess=True）
      - possess=False ：仅返回未拥有（Monster.possess=False 或 NULL）
      - possess=None  ：不过滤拥有状态（全量）

    其它筛选：
      - q / element / role / tag / tags_all / type(acq_type)
    排序（SQL 层）：
      - 基础列：updated_at / created_at / name / element / role
      - 原生六维：hp / speed / attack / defense / magic / resist / raw_sum（六维总和）
      - 派生五维：offense / survive / control / tempo / pp_pressure（OUTER JOIN MonsterDerived）
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    direction = desc if (order or "").lower() == "desc" else asc

    # 基础查询
    base = select(Monster)

    # 拥有状态过滤
    if possess is True:
        base = base.where(Monster.possess.is_(True))
    elif possess is False:
        base = base.where(or_(Monster.possess.is_(False), Monster.possess.is_(None)))
    # possess is None：不过滤

    # 关键词
    if q:
        like = f"%{q.strip()}%"
        base = base.where(Monster.name.ilike(like))

    # 基础筛选
    if element:
        base = base.where(Monster.element == element)
    if role:
        base = base.where(Monster.role == role)

    # 获取渠道（兼容 type / acq_type），使用包含匹配
    type_value = (type or acq_type or "").strip()
    if type_value:
        base = base.where(Monster.type.ilike(f"%{type_value}%"))

    # 标签筛选
    if tag:
        base = base.where(Monster.tags.any(Tag.name == tag))
    if tags_all:
        uniq = [t for t in {t for t in tags_all if t}]
        for t in uniq:
            base = base.where(Monster.tags.any(Tag.name == t))

    # ---- 排序键解析 ----
    s = (sort or "updated_at").lower()

    # 派生五维
    derived_map = {
        "offense": MonsterDerived.offense,
        "survive": MonsterDerived.survive,
        "control": MonsterDerived.control,
        "tempo": MonsterDerived.tempo,
        "pp": MonsterDerived.pp_pressure,          # 别名
        "pp_pressure": MonsterDerived.pp_pressure,
    }

    # 原生六维
    raw_map = {
        "hp": Monster.hp,
        "speed": Monster.speed,
        "attack": Monster.attack,
        "defense": Monster.defense,
        "magic": Monster.magic,
        "resist": Monster.resist,
    }
    raw_sum_expr = (
        func.coalesce(Monster.hp, 0)
        + func.coalesce(Monster.speed, 0)
        + func.coalesce(Monster.attack, 0)
        + func.coalesce(Monster.defense, 0)
        + func.coalesce(Monster.magic, 0)
        + func.coalesce(Monster.resist, 0)
    )

    if s in derived_map:
        base = base.outerjoin(MonsterDerived, MonsterDerived.monster_id == Monster.id)
        base = base.order_by(direction(derived_map[s]), asc(Monster.id))
    elif s in raw_map:
        base = base.order_by(direction(raw_map[s]), asc(Monster.id))
    elif s == "raw_sum":
        base = base.order_by(direction(raw_sum_expr), asc(Monster.id))
    else:
        if s not in {"updated_at", "created_at", "name", "element", "role"}:
            s = "updated_at"
        col = getattr(Monster, s)
        base = base.order_by(direction(col), asc(Monster.id))

    # ---- 计数（子查询 count）----
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0

    # ---- 分页 + 预加载 ----
    stmt = base.limit(page_size).offset((page - 1) * page_size).options(
        selectinload(Monster.tags),
        selectinload(Monster.derived),
        selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
    )
    items = db.execute(stmt).scalars().all()

    # 可选：确保派生落库最新（不会影响排序，因为排序已在 SQL 完成）
    changed = False
    for m in items:
        fresh = compute_derived_out(m)
        if (not m.derived) or any(
            getattr(m.derived, k) != fresh[k]
            for k in ("offense", "survive", "control", "tempo", "pp_pressure")
        ):
            compute_and_persist(db, m)
            changed = True
    if changed:
        db.flush()

    return items, int(total)