# server/app/routes/collections.py
from __future__ import annotations

from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Body, Query
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from ..db import SessionLocal
from ..models import Collection, CollectionItem, Monster, MonsterSkill
from ..schemas import (
    CollectionCreateIn, CollectionUpdateIn,
    CollectionOut, CollectionList,
    BulkSetMembersIn, BulkSetMembersOut,
    MonsterOut, MonsterList,
)
from ..services.collection_service import (
    list_collections, get_or_create_collection, update_collection, delete_collection,
    bulk_set_members, list_collection_members, get_collection_by_id,
)
from ..services.derive_service import compute_derived_out


router = APIRouter(prefix="/collections", tags=["collections"])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# 收藏夹：列表
# -----------------------------
@router.get("", response_model=CollectionList)
def api_list_collections(
    q: Optional[str] = Query(None),
    sort: Optional[str] = Query("updated_at", description="updated_at / created_at / name / items_count / last_used_at"),
    order: Optional[str] = Query("desc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    cols, total = list_collections(
        db,
        q=q,
        sort=sort or "updated_at",
        order=order or "desc",
        page=page,
        page_size=page_size,
    )
    out = [
        CollectionOut(
            id=c.id,
            name=c.name,
            color=getattr(c, "color", None),
            created_at=getattr(c, "created_at", None),
            updated_at=getattr(c, "updated_at", None),
            last_used_at=getattr(c, "last_used_at", None),
            items_count=int(getattr(c, "items_count", 0) or 0),
        )
        for c in cols
    ]
    etag = f'W/"collections:{total}"'
    return {"items": out, "total": total, "has_more": page * page_size < total, "etag": etag}


# -----------------------------
# 收藏夹：创建（名称唯一）
# -----------------------------
@router.post("", response_model=CollectionOut, status_code=201)
def api_create_collection(payload: CollectionCreateIn = Body(...), db: Session = Depends(get_db)):
    name = (payload.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    col, created = get_or_create_collection(db, name=name, color=payload.color)
    if not created:
        raise HTTPException(status_code=409, detail="collection already exists")

    db.commit()
    return CollectionOut(
        id=col.id,
        name=col.name,
        color=getattr(col, "color", None),
        created_at=getattr(col, "created_at", None),
        updated_at=getattr(col, "updated_at", None),
        last_used_at=getattr(col, "last_used_at", None),
        items_count=0,
    )


# -----------------------------
# 收藏夹：更新（名称/颜色）
# -----------------------------
@router.patch("/{collection_id}", response_model=CollectionOut)
def api_update_collection(
    collection_id: int,
    payload: CollectionUpdateIn = Body(...),
    db: Session = Depends(get_db),
):
    col = update_collection(
        db,
        collection_id=collection_id,
        name=payload.name,
        color=payload.color,
    )
    if not col:
        raise HTTPException(status_code=404, detail="collection not found")
    db.commit()

    # 统计当前 items_count
    cnt = db.scalar(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id).count()
    )
    items_count = int(cnt or 0)

    return CollectionOut(
        id=col.id,
        name=col.name,
        color=getattr(col, "color", None),
        created_at=getattr(col, "created_at", None),
        updated_at=getattr(col, "updated_at", None),
        last_used_at=getattr(col, "last_used_at", None),
        items_count=items_count,
    )


# -----------------------------
# 收藏夹：删除
# -----------------------------
@router.delete("/{collection_id}")
def api_delete_collection(collection_id: int, db: Session = Depends(get_db)):
    ok = delete_collection(db, collection_id)
    if not ok:
        raise HTTPException(status_code=404, detail="collection not found")
    db.commit()
    return {"ok": True, "id": collection_id}


# -----------------------------
# 收藏夹：批量加入/移出/覆盖 成员
# -----------------------------
@router.post("/bulk_set", response_model=BulkSetMembersOut)
def api_bulk_set_members(
    payload: BulkSetMembersIn = Body(...),
    db: Session = Depends(get_db),
):
    try:
        res = bulk_set_members(
            db,
            collection_id=payload.collection_id,
            name=payload.name,
            ids=payload.ids,
            action=(payload.action or "add"),
            color_for_new=getattr(payload, "color_for_new", None),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.commit()
    return {
        "collection_id": int(res["collection_id"]),          # type: ignore
        "added": int(res["added"]),                          # type: ignore
        "removed": int(res["removed"]),                      # type: ignore
        "skipped": int(res["skipped"]),                      # type: ignore
        "missing_monsters": list(res["missing_monsters"]),   # type: ignore
    }


# -----------------------------
# （可选）收藏夹详情：返回收藏夹元信息
# -----------------------------
@router.get("/{collection_id}", response_model=CollectionOut)
def api_get_collection(collection_id: int, db: Session = Depends(get_db)):
    col = get_collection_by_id(db, collection_id)
    if not col:
        raise HTTPException(status_code=404, detail="collection not found")

    # 统计 items_count
    total_items = db.scalar(
        select(CollectionItem).where(CollectionItem.collection_id == collection_id).count()
    )
    return CollectionOut(
        id=col.id,
        name=col.name,
        color=getattr(col, "color", None),
        created_at=getattr(col, "created_at", None),
        updated_at=getattr(col, "updated_at", None),
        last_used_at=getattr(col, "last_used_at", None),
        items_count=int(total_items or 0),
    )


# -----------------------------
# 收藏夹成员：列表（分页）
# -----------------------------
@router.get("/{collection_id}/members", response_model=MonsterList)
def api_list_collection_members(
    collection_id: int,
    sort: Optional[str] = Query("id", description="id/name/element/role/updated_at/created_at"),
    order: Optional[str] = Query("asc"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    # 存在性检查
    if not get_collection_by_id(db, collection_id):
        raise HTTPException(status_code=404, detail="collection not found")

    items, total = list_collection_members(
        db,
        collection_id=collection_id,
        sort=sort or "id",
        order=order or "asc",
        page=page,
        page_size=page_size,
    )

    # 预加载（避免 N+1）
    ids = [m.id for m in items]
    if ids:
        _ = db.execute(
            select(Monster)
            .where(Monster.id.in_(ids))
            .options(
                selectinload(Monster.tags),
                selectinload(Monster.derived),
                selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            )
        ).scalars().all()

    out: List[MonsterOut] = []
    for m in items:
        d = compute_derived_out(m)
        out.append(
            MonsterOut(
                id=m.id,
                name=m.name,
                element=m.element,
                role=m.role,
                hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
                possess=getattr(m, "possess", None),
                new_type=getattr(m, "new_type", None),
                type=getattr(m, "type", None),
                method=getattr(m, "method", None),
                tags=[t.name for t in (m.tags or [])],
                explain_json=m.explain_json or {},
                created_at=getattr(m, "created_at", None),
                updated_at=getattr(m, "updated_at", None),
                derived=d,
            )
        )

    etag = f'W/"collection:{collection_id}:{total}"'
    return {"items": out, "total": total, "has_more": page * page_size < total, "etag": etag}