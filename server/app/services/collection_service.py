# server/app/services/collection_service.py
from __future__ import annotations

from datetime import datetime
from typing import Iterable, List, Optional, Tuple, Dict, Set

from sqlalchemy import select, func, asc, desc, delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from ..models import Monster, Collection, CollectionItem


# ---------------------------
# 工具
# ---------------------------

def _direction(order: str):
    return desc if (order or "").lower() == "desc" else asc


def _uniq_int_ids(ids: Iterable[int]) -> List[int]:
    return list({int(i) for i in (ids or []) if isinstance(i, int) or str(i).isdigit()})


def _now() -> datetime:
    return datetime.utcnow()


# ---------------------------
# 收藏夹：CRUD + 列表
# ---------------------------

def get_collection_by_id(db: Session, collection_id: int) -> Optional[Collection]:
    return db.get(Collection, int(collection_id))


def get_collection_by_name(db: Session, name: str) -> Optional[Collection]:
    if not name:
        return None
    return db.scalar(select(Collection).where(Collection.name == name))


def get_or_create_collection(db: Session, *, name: str, color: Optional[str] = None) -> Tuple[Collection, bool]:
    """
    按名称获取收藏夹；不存在则创建并返回 (collection, created)。
    """
    col = get_collection_by_name(db, name)
    if col:
        return col, False
    col = Collection(name=name.strip(), color=(color or None))
    db.add(col)
    db.flush()
    return col, True


def update_collection(
    db: Session,
    *,
    collection_id: int,
    name: Optional[str] = None,
    color: Optional[str] = None,
) -> Optional[Collection]:
    col = get_collection_by_id(db, collection_id)
    if not col:
        return None
    if name is not None and name.strip():
        col.name = name.strip()
    if color is not None:
        col.color = color or None
    db.flush()
    return col


def delete_collection(db: Session, collection_id: int) -> bool:
    col = get_collection_by_id(db, collection_id)
    if not col:
        return False
    # 由于 Collection.items 关系上已设置 delete-orphan，直接删主表即可级联清理
    db.delete(col)
    db.flush()
    return True


def list_collections(
    db: Session,
    *,
    q: Optional[str] = None,
    sort: str = "updated_at",         # 支持：updated_at / created_at / name / items_count / last_used_at
    order: str = "desc",
    page: int = 1,
    page_size: int = 50,
) -> Tuple[List[Collection], int]:
    """
    返回带 items_count 的收藏夹列表（items_count 为临时属性，便于 Pydantic 输出）。
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    direction = _direction(order)

    # 成员计数子查询
    cnt_sub = (
        select(CollectionItem.collection_id, func.count(CollectionItem.monster_id).label("cnt"))
        .group_by(CollectionItem.collection_id)
        .subquery()
    )

    base = (
        select(
            Collection,
            func.coalesce(cnt_sub.c.cnt, 0).label("items_count"),
        )
        .outerjoin(cnt_sub, cnt_sub.c.collection_id == Collection.id)
    )

    # 过滤
    like = None
    if q:
        like = f"%{q.strip()}%"
        base = base.where(Collection.name.ilike(like))

    # —— 修复总数的笛卡尔积问题：对“仅含过滤条件的 id 列”做子查询，再对其 COUNT(*) —— #
    total_sub = select(Collection.id)
    if like:
        total_sub = total_sub.where(Collection.name.ilike(like))
    total = db.scalar(select(func.count()).select_from(total_sub.subquery())) or 0

    # 排序
    s = (sort or "updated_at").lower()
    if s == "items_count":
        base = base.order_by(direction(func.coalesce(cnt_sub.c.cnt, 0)), asc(Collection.id))
    elif s in {"updated_at", "created_at", "name", "last_used_at"}:
        col = getattr(Collection, s)
        base = base.order_by(direction(col), asc(Collection.id))
    else:
        base = base.order_by(direction(Collection.updated_at), asc(Collection.id))

    rows = db.execute(
        base.limit(page_size).offset((page - 1) * page_size)
    ).all()

    items: List[Collection] = []
    for col, items_count in rows:
        # 注入临时属性，Pydantic(from_attributes=True) 可读取
        setattr(col, "items_count", int(items_count or 0))
        items.append(col)

    return items, int(total)


# ---------------------------
# 成员批量操作：add/remove/set
# ---------------------------

def _existing_member_ids(db: Session, collection_id: int, candidate_ids: Iterable[int]) -> Set[int]:
    """
    返回在该收藏夹中、且属于 candidate_ids 的 monster_id 集合。
    """
    if not candidate_ids:
        return set()
    rows = db.execute(
        select(CollectionItem.monster_id)
        .where(
            CollectionItem.collection_id == collection_id,
            CollectionItem.monster_id.in_(list(candidate_ids)),
        )
    ).scalars().all()
    return set(int(x) for x in rows or [])


def _existing_monster_ids(db: Session, candidate_ids: Iterable[int]) -> Set[int]:
    """
    返回数据库中实际存在的怪物 ID（用于跳过无效 ID）。
    """
    if not candidate_ids:
        return set()
    rows = db.execute(
        select(Monster.id).where(Monster.id.in_(list(candidate_ids)))
    ).scalars().all()
    return set(int(x) for x in rows or [])


def bulk_set_members(
    db: Session,
    *,
    collection_id: Optional[int] = None,
    name: Optional[str] = None,
    ids: Iterable[int],
    action: str = "add",   # add/remove/set
    color_for_new: Optional[str] = None,
) -> Dict[str, int | List[int]]:
    """
    批量加入/移出/覆盖收藏夹成员。

    - 当提供 name 且收藏夹不存在时，会自动创建（满足“惰性建表/创建”的需求）。
    - 会跳过不存在的怪物 ID，并返回 missing_monsters 列表。

    返回：
      {
        "added": n_add,
        "removed": n_remove,
        "skipped": n_skip,
        "missing_monsters": [ ... ],
        "collection_id": 123
      }
    """
    if not collection_id and not (name and name.strip()):
        raise ValueError("must provide collection_id or name")

    # 获取或创建收藏夹
    col: Optional[Collection] = None
    created = False
    if collection_id:
        col = get_collection_by_id(db, int(collection_id))
    if not col and name:
        col, created = get_or_create_collection(db, name=name.strip(), color=color_for_new)

    if not col:
        raise ValueError("collection not found and name not provided")

    want_ids = _uniq_int_ids(ids)
    if not want_ids and action != "set":
        # add/remove 的空 ids 没有意义；set 为空表示“清空”
        return {"added": 0, "removed": 0, "skipped": 0, "missing_monsters": [], "collection_id": col.id}

    # 过滤掉不存在的怪物
    exist_ids = _existing_monster_ids(db, want_ids)
    missing = [i for i in want_ids if i not in exist_ids]

    # 当前已有
    curr_ids = _existing_member_ids(db, col.id, exist_ids)

    added = removed = skipped = 0

    if action == "add":
        to_add = sorted(exist_ids - curr_ids)
        for mid in to_add:
            db.add(CollectionItem(collection_id=col.id, monster_id=mid))
        added = len(to_add)

    elif action == "remove":
        to_remove = sorted(curr_ids & exist_ids)
        if to_remove:
            db.execute(
                delete(CollectionItem).where(
                    CollectionItem.collection_id == col.id,
                    CollectionItem.monster_id.in_(to_remove),
                )
            )
        removed = len(to_remove)

    elif action == "set":
        # 目标 = exist_ids；执行“差异化覆盖”
        to_add = sorted(exist_ids - curr_ids)
        to_del = sorted(curr_ids - exist_ids)
        for mid in to_add:
            db.add(CollectionItem(collection_id=col.id, monster_id=mid))
        if to_del:
            db.execute(
                delete(CollectionItem).where(
                    CollectionItem.collection_id == col.id,
                    CollectionItem.monster_id.in_(to_del),
                )
            )
        added = len(to_add)
        removed = len(to_del)

    else:
        raise ValueError("action must be one of: add/remove/set")

    # 统计“跳过”的条目：对于 add 是已存在；对于 remove 是不存在；对于 set 则不适用
    if action == "add":
        skipped = len(curr_ids & exist_ids)
    elif action == "remove":
        skipped = len(exist_ids - curr_ids)

    # 触摸 last_used_at
    col.last_used_at = _now()

    # 提前 flush 以捕获唯一约束错误（极端并发）
    try:
        db.flush()
    except IntegrityError:
        # 二次扫描去重安全处理（一般不会进来）
        db.rollback()
        # 重新开始一次“幂等”处理
        # 注意：此处简化处理，生产可改为重试块
        return bulk_set_members(
            db,
            collection_id=col.id,
            name=None,
            ids=want_ids,
            action=action,
            color_for_new=color_for_new,
        )

    return {
        "added": int(added),
        "removed": int(removed),
        "skipped": int(skipped),
        "missing_monsters": missing,
        "collection_id": col.id,
    }


# ---------------------------
# （可选）列出收藏夹内成员（分页）
# ---------------------------

def list_collection_members(
    db: Session,
    *,
    collection_id: int,
    page: int = 1,
    page_size: int = 50,
    sort: str = "id",
    order: str = "asc",
) -> Tuple[List[Monster], int]:
    """
    返回某收藏夹内的 Monster 列表及总数。
    仅作为可能的前端“查看收藏夹详情”辅助接口；MVP 可不暴露路由。
    """
    page = max(1, int(page))
    page_size = min(200, max(1, int(page_size)))
    direction = _direction(order)

    # 总数
    total = db.scalar(
        select(func.count())
        .select_from(CollectionItem)
        .where(CollectionItem.collection_id == collection_id)
    ) or 0

    # 排序支持的基础字段
    sort_map = {
        "id": Monster.id,
        "name": Monster.name,
        "element": Monster.element,
        "role": Monster.role,
        "updated_at": Monster.updated_at,
        "created_at": Monster.created_at,
    }
    col = sort_map.get((sort or "id").lower(), Monster.id)

    stmt = (
        select(Monster)
        .join(CollectionItem, CollectionItem.monster_id == Monster.id)
        .where(CollectionItem.collection_id == collection_id)
        .order_by(direction(col), asc(Monster.id))
        .limit(page_size)
        .offset((page - 1) * page_size)
        .options(
            selectinload(Monster.tags),
            selectinload(Monster.derived),
            selectinload(Monster.monster_skills),
        )
    )

    items = db.execute(stmt).scalars().all()
    return items, int(total)