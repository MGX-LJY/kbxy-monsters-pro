# server/app/services/warehouse_service.py
from __future__ import annotations

from typing import Iterable, List, Tuple
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import select, func

from ..models import Monster, MonsterSkill, Tag
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
    in_wh = db.scalar(select(func.count(Monster.id)).where(Monster.possess.is_(True))) or 0
    return {"total": int(total), "in_warehouse": int(in_wh)}


# -------- 仓库列表（仅 possess=True） --------
def list_warehouse(
    db: Session,
    *,
    q: str | None = None,
    element: str | None = None,
    role: str | None = None,
    tag: str | None = None,
    tags_all: Iterable[str] | None = None,  # 多标签 AND
    type: str | None = None,                # 获取渠道（兼容）
    acq_type: str | None = None,            # 获取渠道（兼容）
    sort: str = "updated_at",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Monster], int]:
    """
    仅返回在仓库中的怪（Monster.possess=True）。

    支持筛选：
      - q                   : 模糊匹配 name / explain_json.skill_names
      - element / role      : 基础属性
      - tag                 : 单标签
      - tags_all            : 多标签 AND（每个都必须命中）
      - type / acq_type     : 获取渠道（任取其一）
    排序：
      - updated_at / created_at 直接在 SQL 层排序
      - offense/survive/control/tempo/pp_pressure：先按 updated_at 排序分页，再对当前页内存排序
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    stmt = select(Monster).where(Monster.possess.is_(True))

    # 关键词（轻量）
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(
            (Monster.name.ilike(like)) |
            (Monster.explain_json["skill_names"].as_string().ilike(like))  # type: ignore
        )

    # 基础筛选
    if element:
        stmt = stmt.where(Monster.element == element)
    if role:
        stmt = stmt.where(Monster.role == role)

    # 获取渠道（兼容 type / acq_type）
    type_value = type or acq_type
    if type_value:
        stmt = stmt.where(Monster.type == type_value)

    # 标签筛选（基于关系表，精确匹配）
    if tag:
        stmt = stmt.where(Monster.tags.any(Tag.name == tag))

    if tags_all:
        uniq = [t for t in {t for t in tags_all if t}]
        for t in uniq:
            stmt = stmt.where(Monster.tags.any(Tag.name == t))

    # 排序白名单
    sort_whitelist = {"updated_at", "created_at", "offense", "survive", "control", "tempo", "pp_pressure"}
    sort_key = sort if sort in sort_whitelist else "updated_at"

    if sort_key in {"updated_at", "created_at"}:
        col = getattr(Monster, sort_key)
        stmt = stmt.order_by(col.desc() if order == "desc" else col.asc())
    else:
        # 派生维度：按更新时间稳定分页
        stmt = stmt.order_by(Monster.updated_at.desc())

    # 计数（对当前条件取子查询再 count）
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # 分页 + 预加载
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)
    stmt = stmt.options(
        selectinload(Monster.tags),
        selectinload(Monster.derived),
        selectinload(Monster.monster_skills).joinedload(MonsterSkill.skill),
    )

    items = db.execute(stmt).scalars().all()

    # 内存排序（派生维度）
    if sort_key in {"offense", "survive", "control", "tempo", "pp_pressure"}:
        def key_fn(m: Monster):
            d = compute_derived_out(m)
            return d.get(sort_key, 0)
        items.sort(key=key_fn, reverse=(order == "desc"))

    # 可选：确保派生落库最新
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