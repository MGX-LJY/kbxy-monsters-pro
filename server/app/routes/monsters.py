# server/app/routes/monsters.py
from typing import Optional, List, Tuple, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select, func, or_, and_

from ..db import SessionLocal
from ..models import Monster, MonsterSkill, Skill, Tag, CollectionItem
from ..schemas import MonsterIn, MonsterOut, MonsterList
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------- 请求体验证 ----------
class RawStatsIn(BaseModel):
    hp: float = Field(..., description="体力")
    speed: float = Field(..., description="速度")
    attack: float = Field(..., description="攻击")
    defense: float = Field(..., description="防御")
    magic: float = Field(..., description="法术")
    resist: float = Field(..., description="抗性")


class AutoMatchIdsIn(BaseModel):
    ids: List[int]


class BulkDeleteIn(BaseModel):
    ids: List[int]


class SkillSelectionIn(BaseModel):
    skill_id: int
    selected: bool


class BulkSkillSelectionIn(BaseModel):
    selections: List[SkillSelectionIn]


class SkillOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    pp: Optional[int] = None
    description: Optional[str] = None
    selected: Optional[bool] = None


class SkillIn(BaseModel):
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    pp: Optional[int] = None
    description: Optional[str] = None
    selected: Optional[bool] = None  # 若模型含此列，则写入；否则忽略


# ---------- 列表 ----------
@router.get("/monsters", response_model=MonsterList)
def list_api(
    q: Optional[str] = None,
    element: Optional[str] = None,
    # 旧：单标签
    tag: Optional[str] = None,
    # 新：多标签筛选（向后兼容）
    tags_all: Optional[List[str]] = Query(None, description="AND：必须同时包含的标签（可重复）"),
    tags_any: Optional[List[str]] = Query(None, description="OR：任意包含的标签之一（可重复）"),
    tag_mode: Optional[str] = None,  # 当仅提供 tags（数组）时的模式 and/or
    # 预留分组（当前每组单选也兼容）
    buf_tags_all: Optional[List[str]] = Query(None),
    buf_tags_any: Optional[List[str]] = Query(None),
    deb_tags_all: Optional[List[str]] = Query(None),
    deb_tags_any: Optional[List[str]] = Query(None),
    util_tags_all: Optional[List[str]] = Query(None),
    util_tags_any: Optional[List[str]] = Query(None),
    # 可选：如果前端以后直接传 tags=[]
    tags: Optional[List[str]] = Query(None),
    # 获取途径 / 是否当前可获取
    acq_type: Optional[str] = Query(None, description="获取途径（包含匹配）")
    ,
    type_: Optional[str] = Query(None, alias="type", description="获取途径别名（与 acq_type 等价）"),
    # ✅ 新增：按收藏分组筛选
    collection_id: Optional[int] = Query(None, description="收藏分组 ID"),
    sort: Optional[str] = "updated_at",
    order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
    # ✅ 新增：前端点击“修复妖怪”时会传 need_fix=true
    need_fix: Optional[bool] = Query(None, description="仅返回需要修复的怪物（技能数为 0 或 > 5）"),
    db: Session = Depends(get_db),
):
    """
    支持三种标签方式：
    1) 旧：tag=xxx（单标签）
    2) 新：tags_all（AND，可重复） / tags_any（OR）
    3) 分组：buf_/deb_/util_ 的 *_all / *_any；以及 tags[]=... + tag_mode=and|or

    其他：
    - 获取途径 acq_type 或 type（等价，包含匹配）
    - collection_id 过滤收藏分组（JOIN CollectionItem）
    - need_fix=true 时筛“技能名非空”的技能数为 0 或 >5
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    # —— 汇总多标签参数（兼容分组）—— #
    resolved_tags_all: List[str] = []
    resolved_tags_any: List[str] = []

    for arr in (tags_all, buf_tags_all, deb_tags_all, util_tags_all):
        if arr:
            resolved_tags_all.extend([t for t in arr if isinstance(t, str) and t])

    for arr in (tags_any, buf_tags_any, deb_tags_any, util_tags_any):
        if arr:
            resolved_tags_any.extend([t for t in arr if isinstance(t, str) and t])

    # 若仅提供了 tags=[]，根据 tag_mode 落到 AND/OR
    if tags and not (resolved_tags_all or resolved_tags_any):
        if (tag_mode or "").lower() == "or":
            resolved_tags_any.extend(tags)
        else:
            resolved_tags_all.extend(tags)

    # 统一获取途径
    acq = (acq_type or type_ or "").strip() or None

    # —— 组装调用参数（尽量向后兼容旧的 list_monsters 签名）—— #
    base_kwargs = dict(
        db=db,
        q=q,
        element=element,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )
    if resolved_tags_all:
        base_kwargs["tags_all"] = resolved_tags_all
    if resolved_tags_any:
        base_kwargs["tags_any"] = resolved_tags_any
    if (not resolved_tags_all and not resolved_tags_any) and tag:
        base_kwargs["tag"] = tag
    if acq is not None:
        base_kwargs["acq_type"] = acq  # service 侧使用 acq_type/type_ 任一
    if need_fix is not None:
        base_kwargs["need_fix"] = need_fix
    if collection_id is not None:
        base_kwargs["collection_id"] = int(collection_id)

    # —— 优先调用服务层；若签名较旧则回退到本地实现 —— #
    try:
        items, total = list_monsters(**base_kwargs)  # 若服务层支持 collection_id，会直接生效
    except TypeError:
        # 服务层较旧：本地实现（含获取途径 / need_fix / collection_id）
        query = db.query(Monster)

        # 按收藏分组过滤（JOIN + DISTINCT 防重复）
        if collection_id:
            query = (
                query.join(CollectionItem, CollectionItem.monster_id == Monster.id)
                     .filter(CollectionItem.collection_id == int(collection_id))
                     .distinct(Monster.id)
            )

        # 基础筛选
        if q:
            like = f"%{q.strip()}%"
            query = query.filter(Monster.name.ilike(like))
        if element:
            query = query.filter(Monster.element == element)
        if acq:
            query = query.filter(Monster.type.ilike(f"%{acq}%"))

        # 标签筛选（与服务层保持语义一致）
        if resolved_tags_all:
            for t in resolved_tags_all:
                query = query.filter(Monster.tags.any(Tag.name == t))
        if resolved_tags_any:
            query = query.filter(Monster.tags.any(Tag.name.in_(resolved_tags_any)))
        if (not resolved_tags_all and not resolved_tags_any) and tag:
            query = query.filter(Monster.tags.any(Tag.name == tag))

        if need_fix:
            # 统计每只怪“名字非空”的技能数量
            skill_cnt_sub = (
                db.query(
                    MonsterSkill.monster_id.label("mid"),
                    func.count(MonsterSkill.skill_id).label("cnt"),
                )
                .join(Skill, Skill.id == MonsterSkill.skill_id)
                .filter(func.trim(func.coalesce(Skill.name, "")) != "")
                .group_by(MonsterSkill.monster_id)
                .subquery()
            )
            query = (
                query.outerjoin(skill_cnt_sub, skill_cnt_sub.c.mid == Monster.id)
                     .filter(or_(skill_cnt_sub.c.cnt.is_(None),
                                 skill_cnt_sub.c.cnt == 0,
                                 skill_cnt_sub.c.cnt > 5))
            )

        # 排序（默认为 updated_at）
        sort_col = getattr(Monster, sort, getattr(Monster, "updated_at", None))
        if sort_col is None:
            sort_col = getattr(Monster, "updated_at")
        query = query.order_by(sort_col.asc() if (order or "").lower() == "asc" else sort_col.desc())

        # 计数需与查询同条件；若 join 过，distinct 防重复
        total = query.order_by(None).count()
        items = (
            query
            .offset((page - 1) * page_size)
            .limit(page_size)
            .all()
        )

    # 预加载集合（注意：不能对 association_proxy 做 loader）
    ids = [m.id for m in items]
    if ids:
        _ = db.execute(
            select(Monster)
            .where(Monster.id.in_(ids))
            .options(
                selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
                selectinload(Monster.tags),
            )
        ).scalars().all()

    result = []

    for m in items:
        result.append(
            MonsterOut(
                id=m.id,
                name=m.name,
                element=m.element,
                hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
                possess=getattr(m, "possess", None),
                type=getattr(m, "type", None),
                method=getattr(m, "method", None),
                tags=[t.name for t in (m.tags or [])],
                explain_json=getattr(m, "explain_json", {}),
                created_at=getattr(m, "created_at", None),
                updated_at=getattr(m, "updated_at", None),
            )
        )

    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}


# ---------- 详情 ----------
@router.get("/monsters/{monster_id}", response_model=MonsterOut)
def detail(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster).where(Monster.id == monster_id).options(
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            selectinload(Monster.tags),
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    return MonsterOut(
        id=m.id, name=m.name, element=m.element,
        hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
        possess=getattr(m, "possess", None),
        new_type=getattr(m, "new_type", None),
        type=getattr(m, "type", None),
        method=getattr(m, "method", None),
        tags=[t.name for t in (m.tags or [])],
        explain_json=m.explain_json or {},
        created_at=getattr(m, "created_at", None),
        updated_at=getattr(m, "updated_at", None),
    )


# ---------- 只读：当前怪物的技能列表 ----------
@router.get("/monsters/{monster_id}/skills", response_model=List[SkillOut])
def monster_skills(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill))
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    out: List[SkillOut] = []
    for ms in (m.monster_skills or []):
        s = ms.skill
        if not s:
            continue
        # 使用全局技能描述
        desc = (s.description or None)
        out.append(SkillOut(
            id=s.id,
            name=s.name,
            element=getattr(s, "element", None),
            kind=getattr(s, "kind", None),
            power=getattr(s, "power", None),
            pp=getattr(s, "pp", None),
            description=desc,
            selected=getattr(ms, "selected", None)
        ))
    return out


# ---------- 覆盖设置怪物技能（唯一键 upsert + 维护关联表） ----------
@router.put("/monsters/{monster_id}/skills")
def put_monster_skills(monster_id: int, payload: List[SkillIn], db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    items = [
        (it.name, it.element or None, it.kind or None, it.power if it.power is not None else None, it.pp if it.pp is not None else None, it.description or "")
        for it in (payload or [])
    ]
    skills = upsert_skills(db, items)  # Skill 列表
    db.flush()

    # 建立 (name,element,kind,power,pp) -> payload 行 的映射，便于拿 selected/描述
    def key_of(n: str, e: Optional[str], k: Optional[str], p: Optional[int], pp: Optional[int]):
        return (n or "", e or None, k or None, p if p is not None else None, pp if pp is not None else None)

    in_map: Dict[Tuple[str, Optional[str], Optional[str], Optional[int], Optional[int]], SkillIn] = {
        key_of(it.name, it.element, it.kind, it.power, it.pp): it for it in (payload or [])
    }
    sk_map: Dict[Tuple[str, Optional[str], Optional[str], Optional[int], Optional[int]], int] = {
        key_of(getattr(sk, "name", ""), getattr(sk, "element", None), getattr(sk, "kind", None), getattr(sk, "power", None), getattr(sk, "pp", None)): sk.id
        for sk in skills
    }

    # 现有关联
    existing: Dict[int, MonsterSkill] = {ms.skill_id: ms for ms in (m.monster_skills or [])}

    # 需要的 skill_id 集合
    desired_ids = set(sk_map.values())

    # 删除多余关联
    for sid, ms in list(existing.items()):
        if sid not in desired_ids:
            db.delete(ms)

    # 新增/更新关联
    for key, sid in sk_map.items():
        ms = existing.get(sid)
        if not ms:
            ms = MonsterSkill(monster_id=m.id, skill_id=sid)
            db.add(ms)
        # 更新关联级字段
        s_in = in_map.get(key)
        if s_in:
            if hasattr(ms, "selected") and (s_in.selected is not None):
                ms.selected = bool(s_in.selected)

    # explain_json 快照
    ex = m.explain_json or {}
    ex["skill_names"] = [ms.skill.name for ms in (m.monster_skills or []) if ms.skill]
    m.explain_json = ex

    db.commit()
    return {"ok": True, "monster_id": m.id, "skills": ex["skill_names"]}


# ---------- 保存原始六维 ----------
@router.put("/monsters/{monster_id}/raw_stats")
def save_raw_stats(monster_id: int, payload: RawStatsIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 写列
    m.hp = float(payload.hp)
    m.speed = float(payload.speed)
    m.attack = float(payload.attack)
    m.defense = float(payload.defense)
    m.magic = float(payload.magic)
    m.resist = float(payload.resist)

    # explain_json.raw_stats
    ex = m.explain_json or {}
    ex["raw_stats"] = {
        "hp": float(payload.hp),
        "speed": float(payload.speed),
        "attack": float(payload.attack),
        "defense": float(payload.defense),
        "magic": float(payload.magic),
        "resist": float(payload.resist),
        "sum": float(payload.hp + payload.speed + payload.attack + payload.defense + payload.magic + payload.resist),
    }
    m.explain_json = ex


    db.commit()
    return {"ok": True, "monster_id": m.id}




# ---------- 批量自动匹配（仅保留接口，内部不做定位） ----------
@router.post("/monsters/auto_match")
def auto_match(body: AutoMatchIdsIn, db: Session = Depends(get_db)):
    if not body.ids:
        return {"ok": True, "processed": 0}

    mons = db.execute(
        select(Monster)
        .where(Monster.id.in_(body.ids))
        .options(
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            selectinload(Monster.tags),
        )
    ).scalars().all()

    n = 0
    for m in mons:
        pass  # No longer computing derived values
        n += 1

    db.commit()
    return {"ok": True, "processed": n}


# ---------- 创建 ----------
@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    m = Monster(
        name=payload.name,
        element=payload.element,
        hp=payload.hp, speed=payload.speed, attack=payload.attack,
        defense=payload.defense, magic=payload.magic, resist=payload.resist,
        possess=getattr(payload, "possess", None),
        type=getattr(payload, "type", None),
        method=getattr(payload, "method", None),
        explain_json=getattr(payload, "explain_json", None),
    )
    m.tags = upsert_tags(db, payload.tags or [])
    db.add(m); db.flush()

    # skills（可选，走唯一键 upsert + 写 MonsterSkill）
    if getattr(payload, "skills", None):
        items = [
            (s.name, s.element or None, s.kind or None, s.power if s.power is not None else None, s.pp if s.pp is not None else None, s.description or "")
            for s in payload.skills
        ]
        skills = upsert_skills(db, items)
        db.flush()

        # 建立 key -> (skill, payload) 映射
        def key_of(n, e, k, p, pp): return (n or "", e or None, k or None, p if p is not None else None, pp if pp is not None else None)
        in_map = {key_of(s.name, s.element, s.kind, s.power, s.pp): s for s in payload.skills}
        for sk in skills:
            key = key_of(getattr(sk, "name", ""), getattr(sk, "element", None), getattr(sk, "kind", None), getattr(sk, "power", None), getattr(sk, "pp", None))
            s_in = in_map.get(key)
            ms = MonsterSkill(monster_id=m.id, skill_id=sk.id)
            # 关联级字段
            if s_in and hasattr(ms, "selected") and (s_in.selected is not None):
                ms.selected = bool(s_in.selected)
            db.add(ms)

        # explain 快照
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in skills]
        m.explain_json = ex

    db.commit(); db.refresh(m)
    return detail(m.id, db)


# ---------- 更新（显式提供 skills 才改技能） ----------
@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 写基础字段
    for k in ["name", "element", "hp", "speed", "attack", "defense", "magic", "resist",
              "possess", "type", "method"]:
        if hasattr(payload, k):
            setattr(m, k, getattr(payload, k))

    # explain_json（可整体替换）
    if hasattr(payload, "explain_json") and (payload.explain_json is not None):
        m.explain_json = payload.explain_json

    # 标签
    m.tags = upsert_tags(db, payload.tags or [])

    # 只有显式包含 skills 字段才更新技能集合
    skills_field_provided = hasattr(payload, "model_fields_set") and ("skills" in payload.model_fields_set)
    if skills_field_provided:
        # 目标 skills
        items = [
            (s.name, s.element or None, s.kind or None, s.power if s.power is not None else None, s.description or "")
            for s in (payload.skills or [])
        ]
        skills = upsert_skills(db, items)
        db.flush()

        # 建映射
        def key_of(n, e, k, p): return (n or "", e or None, k or None, p if p is not None else None)
        in_map = {key_of(s.name, s.element, s.kind, s.power): s for s in (payload.skills or [])}
        sk_map = {key_of(getattr(sk, "name", ""), getattr(sk, "element", None), getattr(sk, "kind", None), getattr(sk, "power", None)): sk.id for sk in skills}

        # 现有关联
        existing: Dict[int, MonsterSkill] = {ms.skill_id: ms for ms in (m.monster_skills or [])}
        desired_ids = set(sk_map.values())

        # 删除多余
        for sid, ms in list(existing.items()):
            if sid not in desired_ids:
                db.delete(ms)

        # 新增/更新
        for key, sid in sk_map.items():
            ms = existing.get(sid)
            if not ms:
                ms = MonsterSkill(monster_id=m.id, skill_id=sid)
                db.add(ms)
            s_in = in_map.get(key)
            if s_in:
                if hasattr(ms, "selected") and (s_in.selected is not None):
                    ms.selected = bool(s_in.selected)

        # explain 快照
        ex = m.explain_json or {}
        ex["skill_names"] = [ms.skill.name for ms in (m.monster_skills or []) if ms.skill]
        m.explain_json = ex

    db.commit()
    return detail(monster_id, db)


# ---------- 删除 ----------
@router.delete("/monsters/{monster_id}")
def delete(monster_id: int, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 关系清理由 delete-orphan & 外键 ondelete 兜底；这里显式清空更稳妥
    for ms in (m.monster_skills or []):
        db.delete(ms)
    if m.tags is not None:
        m.tags.clear()
    db.flush()

    db.delete(m)
    db.commit()
    return {"ok": True}


# ---------- 批量删除 ----------
@router.delete("/monsters/bulk_delete")
def bulk_delete(payload: BulkDeleteIn, db: Session = Depends(get_db)):
    if not payload.ids:
        return {"ok": True, "deleted": 0}
    
    # 查找需要删除的妖怪
    monsters = db.execute(
        select(Monster).where(Monster.id.in_(payload.ids))
    ).scalars().all()
    
    deleted_count = 0
    for m in monsters:
        # 清理关系
        for ms in (m.monster_skills or []):
            db.delete(ms)
        if m.tags is not None:
            m.tags.clear()
        db.flush()
        
        # 删除妖怪本身
        db.delete(m)
        deleted_count += 1
    
    db.commit()
    return {"ok": True, "deleted": deleted_count}


# ---------- 批量删除 (POST方法兼容) ----------
@router.post("/monsters/bulk_delete")
def bulk_delete_post(payload: BulkDeleteIn, db: Session = Depends(get_db)):
    return bulk_delete(payload, db)


# ---------- 批量更新技能推荐状态 ----------
@router.put("/monsters/{monster_id}/skills/selections")
def update_skill_selections(monster_id: int, payload: BulkSkillSelectionIn, db: Session = Depends(get_db)):
    """
    批量更新怪物技能的推荐状态（selected字段）
    """
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="Monster not found")

    # 获取现有的技能关联
    existing_ms = {ms.skill_id: ms for ms in (m.monster_skills or [])}
    
    updated_count = 0
    for selection in payload.selections:
        ms = existing_ms.get(selection.skill_id)
        if ms:
            ms.selected = selection.selected
            updated_count += 1
    
    db.commit()
    return {"ok": True, "monster_id": monster_id, "updated_count": updated_count}