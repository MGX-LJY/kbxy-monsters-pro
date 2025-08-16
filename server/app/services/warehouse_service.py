# server/app/services/warehouse_service.py
from __future__ import annotations

from typing import Iterable, List, Tuple
from sqlalchemy.orm import Session, selectinload, joinedload
from sqlalchemy import select, func

from ..models import Monster, MonsterSkill  # 注意：MonsterSkill 仅用于预加载其 .skill
from ..services.derive_service import compute_derived_out, compute_and_persist
from ..services.tags_service import infer_role_for_monster, suggest_tags_for_monster


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
    n = 0
    uniq_ids = list({int(i) for i in (ids or [])})
    if not uniq_ids:
        return 0
    for mid in uniq_ids:
        m = db.get(Monster, mid)
        if not m:
            continue
        if bool(getattr(m, "possess", False)) != possess:
            m.possess = possess
            n += 1
    if n:
        db.flush()
    return n


# -------- 统计 --------
def warehouse_stats(db: Session) -> dict:
    total = db.scalar(select(func.count(Monster.id))) or 0
    in_wh = db.scalar(select(func.count(Monster.id)).where(Monster.possess.is_(True))) or 0
    return {"total": int(total), "in_warehouse": int(in_wh)}


# -------- 列表（仅 possess=True），带轻量筛选与派生刷新 --------
def list_warehouse(
    db: Session,
    *,
    q: str | None = None,
    element: str | None = None,
    role: str | None = None,
    tag: str | None = None,
    sort: str = "updated_at",
    order: str = "desc",
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Monster], int]:
    """
    仅返回在仓库中的怪（Monster.possess=True）。
    筛选项尽量贴合 /monsters 的常用参数；排序默认 updated_at。
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))

    stmt = select(Monster).where(Monster.possess.is_(True))

    if q:
        like = f"%{q.strip()}%"
        # 仅按 name / explain_json.skill_names 做简单 LIKE；如需按技能描述/标签全文可扩展
        stmt = stmt.where(
            (Monster.name.ilike(like)) |
            (Monster.explain_json["skill_names"].as_string().ilike(like))  # type: ignore
        )
    if element:
        stmt = stmt.where(Monster.element == element)
    if role:
        stmt = stmt.where(Monster.role == role)
    if tag:
        # 简单通过 ANY JSON -> LIKE 的方式过滤；若需要精准基于联结表过滤可改为 join Tag
        like_tag = f"%{tag}%"
        stmt = stmt.where(Monster.explain_json["tags"].as_string().ilike(like_tag))  # type: ignore

    # 排序：仅允许白名单
    sort_whitelist = {"updated_at", "created_at", "offense", "survive", "control", "tempo", "pp_pressure"}
    sort_key = sort if sort in sort_whitelist else "updated_at"

    if sort_key in {"updated_at", "created_at"}:
        order_col = getattr(Monster, sort_key)
        stmt = stmt.order_by(order_col.desc() if order == "desc" else order_col.asc())
    else:
        # 若按派生五维排序：先按更新时间排，以免无派生导致异常
        stmt = stmt.order_by(Monster.updated_at.desc())

    # 计数
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0

    # 分页
    stmt = stmt.limit(page_size).offset((page - 1) * page_size)

    # 预加载（注意不要对 association_proxy 使用 selectinload）
    stmt = stmt.options(
        selectinload(Monster.tags),
        selectinload(Monster.derived),
        selectinload(Monster.monster_skills).joinedload(MonsterSkill.skill),
    )

    items = db.execute(stmt).scalars().all()

    # 若是按派生维度排序，需要补一个内存排序（避免 SQL 侧 join monster_derived）
    if sort_key in {"offense", "survive", "control", "tempo", "pp_pressure"}:
        def key_fn(m: Monster):
            d = compute_derived_out(m)
            return d.get(sort_key, 0)
        items.sort(key=key_fn, reverse=(order == "desc"))

    # 确保派生落库最新（可选）
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