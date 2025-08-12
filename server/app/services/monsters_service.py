from typing import List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select, func, asc, desc
from ..models import Monster, Tag
from ..services.rules_engine import calc_scores

def get_sort_col(sort: str):
    m = Monster
    return {
        "offense": m.base_offense,
        "survive": m.base_survive,
        "control": m.base_control,
        "tempo": m.base_tempo,
        "pp": m.base_pp,
        "name": m.name_final,
        "updated_at": m.updated_at,
    }.get(sort or "updated_at", m.updated_at)

def list_monsters(db: Session, *, q: str | None, element: str | None, role: str | None,
                  tag: str | None, sort: str | None, order: str | None,
                  page: int, page_size: int) -> Tuple[List[Monster], int]:
    stmt = select(Monster)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(Monster.name_final.like(like))
    if element:
        stmt = stmt.where(Monster.element == element)
    if role:
        stmt = stmt.where(Monster.role == role)
    if tag:
        stmt = stmt.join(Monster.tags).where(Tag.name == tag)

    total = db.scalar(select(func.count()).select_from(stmt.subquery()))
    sort_col = get_sort_col(sort)
    stmt = stmt.order_by(asc(sort_col) if (order or "desc") == "asc" else desc(sort_col))
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    rows = db.scalars(stmt).all()
    return rows, total or 0

def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    result = []
    for n in set([s.strip() for s in names if s.strip()]):
        tag = db.execute(select(Tag).where(Tag.name == n)).scalar_one_or_none()
        if not tag:
            tag = Tag(name=n)
            db.add(tag)
            db.flush()
        result.append(tag)
    return result

def apply_scores(m: Monster):
    m.explain_json = calc_scores({
        "base_offense": m.base_offense,
        "base_survive": m.base_survive,
        "base_control": m.base_control,
        "base_tempo": m.base_tempo,
        "base_pp": m.base_pp
    }).explain
