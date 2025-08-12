# server/app/services/monsters_service.py
from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, func, asc, desc, outerjoin
from ..models import Monster, Tag, MonsterDerived

# —— 排序字段解析：支持按派生五维或基础信息排序 —— #
def _get_sort_target(sort: str):
    """
    返回 (column, needs_derived_join)。
    - offense/survive/control/tempo/pp_pressure -> MonsterDerived.*
    - name/updated_at -> Monster.*
    其他 -> 默认 updated_at
    """
    s = (sort or "updated_at").lower()
    md = MonsterDerived
    m = Monster
    derived_map = {
        "offense": md.offense,
        "survive": md.survive,
        "control": md.control,
        "tempo": md.tempo,
        "pp_pressure": md.pp_pressure,
        # 兼容老前端里偶尔传的 'pp'
        "pp": md.pp_pressure,
    }
    if s in derived_map:
        return derived_map[s], True
    if s == "name":
        return m.name_final, False
    if s == "element":
        return m.element, False
    if s == "role":
        return m.role, False
    # 默认
    return m.updated_at, False


def list_monsters(
    db: Session,
    *,
    q: str | None,
    element: str | None,
    role: str | None,
    tag: str | None,
    sort: str | None,
    order: str | None,
    page: int,
    page_size: int,
) -> Tuple[List[Monster], int]:
    """
    统一列表查询：
    - 过滤：q(名称模糊)、element、role、tag
    - 排序：若按派生五维排序，LEFT JOIN MonsterDerived；否则只用 Monster
    - 分页
    - 计数用 DISTINCT(monster.id)，避免 join/tag 导致的重复行
    """
    # 过滤条件（基础 SELECT，用于计数）
    base_stmt = select(Monster.id)
    if tag:
        base_stmt = base_stmt.join(Monster.tags).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        base_stmt = base_stmt.where(Monster.name_final.like(like))
    if element:
        base_stmt = base_stmt.where(Monster.element == element)
    if role:
        base_stmt = base_stmt.where(Monster.role == role)

    # 如果要按派生排序，计数层也需要包含到同样的 FROM 结构（否则某些方言会报未知列）
    sort_col, need_join = _get_sort_target(sort or "updated_at")
    if need_join:
        base_stmt = base_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    # 计数
    subq = base_stmt.subquery()
    total = db.scalar(select(func.count()).select_from(subq)) or 0

    # 取行（真正查询 Monster 实体）
    rows_stmt = select(Monster)
    if tag:
        rows_stmt = rows_stmt.join(Monster.tags).where(Tag.name == tag)
    if q:
        like = f"%{q}%"
        rows_stmt = rows_stmt.where(Monster.name_final.like(like))
    if element:
        rows_stmt = rows_stmt.where(Monster.element == element)
    if role:
        rows_stmt = rows_stmt.where(Monster.role == role)

    if need_join:
        rows_stmt = rows_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    # 排序方向
    is_asc = (order or "desc").lower() == "asc"
    rows_stmt = rows_stmt.order_by(asc(sort_col) if is_asc else desc(sort_col))

    # 分页
    rows_stmt = rows_stmt.offset((page - 1) * page_size).limit(page_size)

    # 提取
    rows = db.scalars(rows_stmt).unique().all()
    return rows, int(total)


def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    """
    去重 + Upsert 标签
    """
    result: List[Tag] = []
    uniq = []
    seen = set()
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