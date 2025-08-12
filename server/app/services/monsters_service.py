from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, func, asc, desc, outerjoin
from ..models import Monster, Tag, MonsterDerived

# 排序字段解析：支持派生五维（pp / pp_pressure 都支持）
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
    if s == "name": return m.name_final, False
    if s == "element": return m.element, False
    if s == "role": return m.role, False
    return m.updated_at, False

def list_monsters(
    db: Session, *, q: str | None, element: str | None, role: str | None,
    tag: str | None, sort: str | None, order: str | None,
    page: int, page_size: int
) -> Tuple[List[Monster], int]:
    """
    列表：可按标签/元素/定位过滤；按派生五维或更新时间排序。
    """
    # 计数子查询（避免笛卡尔计数偏大）
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
        rows_stmt = rows_stmt.where(Monster.name_final.like(like))
    if element:
        rows_stmt = rows_stmt.where(Monster.element == element)
    if role:
        rows_stmt = rows_stmt.where(Monster.role == role)
    if need_join:
        rows_stmt = rows_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )
    is_asc = (order or "desc").lower() == "asc"
    rows_stmt = rows_stmt.order_by(asc(sort_col) if is_asc else desc(sort_col))
    rows_stmt = rows_stmt.offset((page - 1) * page_size).limit(page_size)
    rows = db.scalars(rows_stmt).unique().all()
    return rows, int(total)

def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    """
    将一维标签名写入 Tag 表后返回 Tag 实体列表；调用前应保证 names 已经是新三类规范化的名字。
    """
    result: List[Tag] = []
    uniq, seen = [], set()
    for s in names or []:
        n = (s or "").strip()
        if not n or n in seen:
            continue
        seen.add(n); uniq.append(n)
    for n in uniq:
        tag = db.execute(select(Tag).where(Tag.name == n)).scalar_one_or_none()
        if not tag:
            tag = Tag(name=n)
            db.add(tag); db.flush()
        result.append(tag)
    return result