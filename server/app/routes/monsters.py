# server/app/routes/monsters.py
from typing import Optional, List, Tuple, Dict
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, selectinload
from sqlalchemy import select

from ..db import SessionLocal
from ..models import Monster, MonsterSkill
from ..schemas import MonsterIn, MonsterOut, MonsterList
from ..services.monsters_service import list_monsters, upsert_tags
from ..services.skills_service import upsert_skills
from ..services.derive_service import (
    compute_derived_out,
    compute_and_persist,
    recompute_and_autolabel,
)

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


class SkillOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    description: Optional[str] = None


class SkillIn(BaseModel):
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    description: Optional[str] = None
    selected: Optional[bool] = None  # 若模型含此列，则写入；否则忽略


# ---------- 列表 ----------
@router.get("/monsters", response_model=MonsterList)
def list_api(
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
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
    sort: Optional[str] = "updated_at",
    order: Optional[str] = "desc",
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """
    支持三种方式：
    1) 旧参数：tag=xxx（单标签）
    2) 新参数：tags_all=...（可重复，AND）/ tags_any=...（OR）
    3) 组合/分组：buf_tags_* / deb_tags_* / util_tags_*；以及 tags[]=... + tag_mode=and|or
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

    # —— 组装调用参数（尽量向后兼容旧的 list_monsters 签名）—— #
    base_kwargs = dict(
        db=db,
        q=q,
        element=element,
        role=role,
        sort=sort,
        order=order,
        page=page,
        page_size=page_size,
    )

    # 优先使用新多标签；否则回退到旧 tag
    if resolved_tags_all:
        base_kwargs["tags_all"] = resolved_tags_all
    if resolved_tags_any:
        base_kwargs["tags_any"] = resolved_tags_any
    if (not resolved_tags_all and not resolved_tags_any) and tag:
        base_kwargs["tag"] = tag

    # —— 调用服务：若后端未升级签名，降级使用旧参数 —— #
    try:
        items, total = list_monsters(**base_kwargs)  # 新版服务应支持 tags_all/tags_any
    except TypeError:
        # 旧版回退：只能单标签；多标签时尽可能退化为首个标签
        legacy_tag = None
        if resolved_tags_all:
            legacy_tag = resolved_tags_all[0]
        elif resolved_tags_any:
            legacy_tag = resolved_tags_any[0]
        else:
            legacy_tag = tag

        items, total = list_monsters(
            db, q=q, element=element, role=role, tag=legacy_tag,
            sort=sort, order=order, page=page, page_size=page_size
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
                selectinload(Monster.derived),
            )
        ).scalars().all()

    result = []
    changed = False

    for m in items:
        # 缺 role/tags/derived 自动补齐（统一走 recompute_and_autolabel）
        if (not m.role) or (not m.tags) or (not m.derived):
            recompute_and_autolabel(db, m)
            changed = True

        # 保证派生最新（与 compute_derived_out 对齐）
        fresh = compute_derived_out(m)
        need_update = (
            (not m.derived)
            or m.derived.offense != fresh["offense"]
            or m.derived.survive != fresh["survive"]
            or m.derived.control != fresh["control"]
            or m.derived.tempo != fresh["tempo"]
            or m.derived.pp_pressure != fresh["pp_pressure"]
        )
        if need_update:
            compute_and_persist(db, m)
            changed = True

        d = fresh if need_update else {
            "offense": m.derived.offense,
            "survive": m.derived.survive,
            "control": m.derived.control,
            "tempo": m.derived.tempo,
            "pp_pressure": m.derived.pp_pressure,
        }

        result.append(
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

    if changed:
        db.commit()

    etag = f'W/"monsters:{total}"'
    return {"items": result, "total": total, "has_more": page * page_size < total, "etag": etag}


# ---------- 详情 ----------
@router.get("/monsters/{monster_id}", response_model=MonsterOut)
def detail(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster).where(Monster.id == monster_id).options(
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            selectinload(Monster.tags),
            selectinload(Monster.derived),
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 自动补（统一路径）
    if (not m.role) or (not m.tags) or (not m.derived):
        recompute_and_autolabel(db, m)

    fresh = compute_derived_out(m)
    if (not m.derived) or (
        m.derived.offense != fresh["offense"]
        or m.derived.survive != fresh["survive"]
        or m.derived.control != fresh["control"]
        or m.derived.tempo != fresh["tempo"]
        or m.derived.pp_pressure != fresh["pp_pressure"]
    ):
        compute_and_persist(db, m)
        db.commit()

    return MonsterOut(
        id=m.id, name=m.name, element=m.element, role=m.role,
        hp=m.hp, speed=m.speed, attack=m.attack, defense=m.defense, magic=m.magic, resist=m.resist,
        possess=getattr(m, "possess", None),
        new_type=getattr(m, "new_type", None),
        type=getattr(m, "type", None),
        method=getattr(m, "method", None),
        tags=[t.name for t in (m.tags or [])],
        explain_json=m.explain_json or {},
        created_at=getattr(m, "created_at", None),
        updated_at=getattr(m, "updated_at", None),
        derived={
            "offense": m.derived.offense,
            "survive": m.derived.survive,
            "control": m.derived.control,
            "tempo": m.derived.tempo,
            "pp_pressure": m.derived.pp_pressure,
        },
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
        # 关联上的描述优先；否则回退到全局技能描述
        desc = (getattr(ms, "description", None) or s.description or None)
        out.append(SkillOut(
            id=s.id,
            name=s.name,
            element=getattr(s, "element", None),
            kind=getattr(s, "kind", None),
            power=getattr(s, "power", None),
            description=desc
        ))
    return out


# ---------- 覆盖设置怪物技能（唯一键 upsert + 维护关联表） ----------
@router.put("/monsters/{monster_id}/skills")
def put_monster_skills(monster_id: int, payload: List[SkillIn], db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    items = [
        (it.name, it.element or None, it.kind or None, it.power if it.power is not None else None, it.description or "")
        for it in (payload or [])
    ]
    skills = upsert_skills(db, items)  # Skill 列表
    db.flush()

    # 建立 (name,element,kind,power) -> payload 行 的映射，便于拿 selected/描述
    def key_of(n: str, e: Optional[str], k: Optional[str], p: Optional[int]) -> Tuple[str, Optional[str], Optional[str], Optional[int]]:
        return (n or "", e or None, k or None, p if p is not None else None)

    in_map: Dict[Tuple[str, Optional[str], Optional[str], Optional[int]], SkillIn] = {
        key_of(it.name, it.element, it.kind, it.power): it for it in (payload or [])
    }
    sk_map: Dict[Tuple[str, Optional[str], Optional[str], Optional[int]], int] = {
        key_of(getattr(sk, "name", ""), getattr(sk, "element", None), getattr(sk, "kind", None), getattr(sk, "power", None)): sk.id
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
            if hasattr(ms, "description"):
                # 若传了描述则覆盖到关联描述（更贴合“该怪物的该技能”）
                if s_in.description and s_in.description.strip():
                    ms.description = s_in.description.strip()

    # explain_json 快照
    ex = m.explain_json or {}
    ex["skill_names"] = [ms.skill.name for ms in (m.monster_skills or []) if ms.skill]
    m.explain_json = ex

    # 自动定位/标签 + 重算派生（统一入口）
    recompute_and_autolabel(db, m)
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

    # 重算派生（数值变化）
    compute_and_persist(db, m)

    db.commit()
    return {"ok": True, "monster_id": m.id}


# ---------- 派生 + 建议（供前端“填充”） ----------
@router.get("/monsters/{monster_id}/derived")
def derived_suggestions(monster_id: int, db: Session = Depends(get_db)):
    m = db.execute(
        select(Monster)
        .where(Monster.id == monster_id)
        .options(
            selectinload(Monster.monster_skills).selectinload(MonsterSkill.skill),
            selectinload(Monster.tags),
            selectinload(Monster.derived),
        )
    ).scalar_one_or_none()
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 统一通过 derive_service 更新并读取
    recompute_and_autolabel(db, m)
    db.commit()

    derived_now = compute_derived_out(m)
    return {
        "monster_id": m.id,
        "role_suggested": m.role,                     # 统一由 derive_service 产出
        "tags": [t.name for t in (m.tags or [])],     # 当前建议标签（已落库）
        "derived": derived_now,
    }


# ---------- 批量自动匹配 ----------
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
            selectinload(Monster.derived),
        )
    ).scalars().all()

    n = 0
    for m in mons:
        # 统一入口：自动标签 + 定位 + 派生
        recompute_and_autolabel(db, m)
        n += 1

    db.commit()
    return {"ok": True, "processed": n}


# ---------- 创建 ----------
@router.post("/monsters", response_model=MonsterOut)
def create(payload: MonsterIn, db: Session = Depends(get_db)):
    m = Monster(
        name=payload.name,
        element=payload.element,
        role=payload.role,
        hp=payload.hp, speed=payload.speed, attack=payload.attack,
        defense=payload.defense, magic=payload.magic, resist=payload.resist,
        possess=getattr(payload, "possess", None),
        new_type=getattr(payload, "new_type", None),
        type=getattr(payload, "type", None),
        method=getattr(payload, "method", None),
        explain_json=getattr(payload, "explain_json", None),
    )
    m.tags = upsert_tags(db, payload.tags or [])
    db.add(m); db.flush()

    # skills（可选，走唯一键 upsert + 写 MonsterSkill）
    if getattr(payload, "skills", None):
        items = [
            (s.name, s.element or None, s.kind or None, s.power if s.power is not None else None, s.description or "")
            for s in payload.skills
        ]
        skills = upsert_skills(db, items)
        db.flush()

        # 建立 key -> (skill, payload) 映射
        def key_of(n, e, k, p): return (n or "", e or None, k or None, p if p is not None else None)
        in_map = {key_of(s.name, s.element, s.kind, s.power): s for s in payload.skills}
        for sk in skills:
            key = key_of(getattr(sk, "name", ""), getattr(sk, "element", None), getattr(sk, "kind", None), getattr(sk, "power", None))
            s_in = in_map.get(key)
            ms = MonsterSkill(monster_id=m.id, skill_id=sk.id)
            # 关联级字段
            if s_in and hasattr(ms, "selected") and (s_in.selected is not None):
                ms.selected = bool(s_in.selected)
            if s_in and hasattr(ms, "description") and (s_in.description or "").trim():
                ms.description = s_in.description.strip()
            db.add(ms)

        # explain 快照
        ex = m.explain_json or {}
        ex["skill_names"] = [s.name for s in skills]
        m.explain_json = ex

    # 初次自动打标 + 派生（统一入口）
    recompute_and_autolabel(db, m)
    db.commit(); db.refresh(m)
    return detail(m.id, db)


# ---------- 更新（显式提供 skills 才改技能） ----------
@router.put("/monsters/{monster_id}", response_model=MonsterOut)
def update(monster_id: int, payload: MonsterIn, db: Session = Depends(get_db)):
    m = db.get(Monster, monster_id)
    if not m:
        raise HTTPException(status_code=404, detail="not found")

    # 写基础字段
    for k in ["name", "element", "role", "hp", "speed", "attack", "defense", "magic", "resist",
              "possess", "new_type", "type", "method"]:
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
                if hasattr(ms, "description") and (s_in.description or "").strip():
                    ms.description = s_in.description.strip()

        # explain 快照
        ex = m.explain_json or {}
        ex["skill_names"] = [ms.skill.name for ms in (m.monster_skills or []) if ms.skill]
        m.explain_json = ex

    # 更新后：重打标+重算派生（统一入口）
    recompute_and_autolabel(db, m)
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

    db.delete(m)  # MonsterDerived 通过 delete-orphan 一并删除
    db.commit()
    return {"ok": True}