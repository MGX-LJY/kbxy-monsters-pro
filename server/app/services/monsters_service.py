# server/app/services/monsters_service.py
from __future__ import annotations

from typing import List, Tuple, Optional, Dict, Any

from sqlalchemy.orm import Session
from sqlalchemy import (
    select, func, asc, desc, outerjoin, case, distinct, or_
)

from ..models import Monster, Tag, MonsterDerived, MonsterSkill, Skill


# ---- 排序字段解析：支持派生五维（pp / pp_pressure 都支持） ----
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
    if s == "name":
        return m.name, False
    if s == "element":
        return m.element, False
    if s == "role":
        return m.role, False
    return m.updated_at, False


# ---- 构造“多标签（AND/OR）”子查询：返回满足条件的 Monster.id 集合 ----
def _subq_ids_for_multi_tags(
    tags_all: Optional[List[str]],
    tags_any: Optional[List[str]],
) -> Optional[Any]:
    """
    返回一个子查询（仅含一列 id），包含满足：
      - AND：必须同时包含 tags_all 里所有标签（distinct）
      - OR ：至少包含 tags_any 里的任意一个
    的 Monster.id。
    若两者皆空，返回 None。
    """
    names_all = [t for t in (tags_all or []) if isinstance(t, str) and t.strip()]
    names_any = [t for t in (tags_any or []) if isinstance(t, str) and t.strip()]
    if not names_all and not names_any:
        return None

    # 统一在“标签域”内聚合，然后 HAVING 条件判断
    stmt = (
        select(Monster.id)
        .select_from(Monster)
        .join(Monster.tags)  # -> Tag
        .group_by(Monster.id)
    )

    if names_all:
        cnt_all = func.count(
            distinct(
                case(
                    (Tag.name.in_(list(set(names_all))), Tag.name),
                    else_=None
                )
            )
        )
        stmt = stmt.having(cnt_all == len(set(names_all)))

    if names_any:
        cnt_any = func.count(
            distinct(
                case(
                    (Tag.name.in_(list(set(names_any))), Tag.name),
                    else_=None
                )
            )
        )
        stmt = stmt.having(cnt_any >= 1)

    return stmt.subquery()


# ---- “需要修复”子查询：统计名字非空技能数量 ----
def _subq_skill_count_nonempty():
    return (
        select(
            MonsterSkill.monster_id.label("mid"),
            func.count(Skill.id).label("cnt"),
        )
        .join(Skill, Skill.id == MonsterSkill.skill_id)
        .where(func.trim(func.coalesce(Skill.name, "")) != "")
        .group_by(MonsterSkill.monster_id)
        .subquery()
    )


# ---- 列表查询：可按标签(单/多)/元素/定位/获取途径/是否可获取/是否需修复 过滤；按派生或更新时间排序 ----
def list_monsters(
    db: Session,
    *,
    q: Optional[str] = None,
    element: Optional[str] = None,
    role: Optional[str] = None,
    # 旧：单标签
    tag: Optional[str] = None,
    # 新：多标签（优先于 tag）
    tags_all: Optional[List[str]] = None,
    tags_any: Optional[List[str]] = None,
    # 获取途径 / 是否当前可获取
    acq_type: Optional[str] = None,      # Monster.type（包含匹配）
    type_: Optional[str] = None,         # 路由层 alias 透传
    new_type: Optional[bool] = None,     # Monster.new_type
    # 修复筛选（技能名非空的技能数为 0 或 >5）
    need_fix: Optional[bool] = None,
    sort: Optional[str] = None,
    order: Optional[str] = None,
    page: int = 1,
    page_size: int = 20,
) -> Tuple[List[Monster], int]:
    """
    说明：
      - 多标签（全库级）：
          AND：tags_all=...&tags_all=...
          OR ：tags_any=...&tags_any=...
          同时给出时表示“必须同时满足 AND 且满足 OR”。
      - 若提供了 tags_all/any，则忽略旧参数 tag（向后兼容）。
      - 获取途径（acq_type/type_）为包含匹配（ILIKE），更宽松。
      - need_fix=True：筛选出“技能名非空的技能数为 0 或 >5”的怪。
      - 排序字段支持派生五维；分页/计数在过滤后执行。
    """
    page = max(1, page)
    page_size = min(max(1, page_size), 200)

    use_multi = bool((tags_all and len(tags_all) > 0) or (tags_any and len(tags_any) > 0))
    multi_subq = _subq_ids_for_multi_tags(tags_all, tags_any) if use_multi else None
    acq = (acq_type or type_ or "").strip()  # 统一获取途径

    # 预备 need_fix 的技能计数子查询
    skills_cnt_subq = _subq_skill_count_nonempty() if need_fix else None

    # ---------- 计数 ----------
    base_stmt = select(Monster.id)

    # 文本/基础条件
    if q:
        like = f"%{q}%"
        base_stmt = base_stmt.where(Monster.name.ilike(like))
    if element:
        base_stmt = base_stmt.where(Monster.element == element)
    if role:
        base_stmt = base_stmt.where(Monster.role == role)
    if acq:
        base_stmt = base_stmt.where(getattr(Monster, "type").ilike(f"%{acq}%"))
    if isinstance(new_type, bool):
        base_stmt = base_stmt.where(Monster.new_type == new_type)

    # 标签条件
    if use_multi and multi_subq is not None:
        base_stmt = base_stmt.where(Monster.id.in_(select(multi_subq.c.id)))
    elif tag:
        base_stmt = base_stmt.join(Monster.tags).where(Tag.name == tag)

    # need_fix 条件
    if need_fix and skills_cnt_subq is not None:
        base_stmt = (
            base_stmt
            .outerjoin(skills_cnt_subq, skills_cnt_subq.c.mid == Monster.id)
            .where(
                or_(
                    skills_cnt_subq.c.cnt.is_(None),
                    skills_cnt_subq.c.cnt == 0,
                    skills_cnt_subq.c.cnt > 5,
                )
            )
        )

    # 排序依赖（仅影响 SELECT FROM 的 JOIN，计数不需要 order_by）
    sort_col, need_join = _get_sort_target(sort or "updated_at")
    if need_join:
        base_stmt = base_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    subq = base_stmt.subquery()
    total = db.scalar(select(func.count()).select_from(subq)) or 0

    # ---------- 取行 ----------
    rows_stmt = select(Monster)

    if q:
        like = f"%{q}%"
        rows_stmt = rows_stmt.where(Monster.name.ilike(like))
    if element:
        rows_stmt = rows_stmt.where(Monster.element == element)
    if role:
        rows_stmt = rows_stmt.where(Monster.role == role)
    if acq:
        rows_stmt = rows_stmt.where(getattr(Monster, "type").ilike(f"%{acq}%"))
    if isinstance(new_type, bool):
        rows_stmt = rows_stmt.where(Monster.new_type == new_type)

    if use_multi and multi_subq is not None:
        rows_stmt = rows_stmt.where(Monster.id.in_(select(multi_subq.c.id)))
    elif tag:
        rows_stmt = rows_stmt.join(Monster.tags).where(Tag.name == tag)

    if need_fix and skills_cnt_subq is not None:
        rows_stmt = (
            rows_stmt
            .outerjoin(skills_cnt_subq, skills_cnt_subq.c.mid == Monster.id)
            .where(
                or_(
                    skills_cnt_subq.c.cnt.is_(None),
                    skills_cnt_subq.c.cnt == 0,
                    skills_cnt_subq.c.cnt > 5,
                )
            )
        )

    # 排序（派生排序需要 OUTER JOIN）
    if need_join:
        rows_stmt = rows_stmt.select_from(
            outerjoin(Monster, MonsterDerived, MonsterDerived.monster_id == Monster.id)
        )

    is_asc = (order or "desc").lower() == "asc"
    rows_stmt = rows_stmt.order_by(asc(sort_col) if is_asc else desc(sort_col))
    rows_stmt = rows_stmt.offset((page - 1) * page_size).limit(page_size)

    rows = db.scalars(rows_stmt).unique().all()
    return rows, int(total)


# ---- 标签 upsert（保持返回 Tag 实体列表） ----
def upsert_tags(db: Session, names: List[str]) -> List[Tag]:
    """
    将一维标签名写入 Tag 表后返回 Tag 实体列表；
    调用方应保证 names 已经是新三类规范化的代码（buf_/deb_/util_）。
    """
    result: List[Tag] = []
    uniq, seen = [], set()
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


# ---- 设置标签即派生：统一依赖 derive_service，避免旧 infer_role_for_monster ----
def set_tags_and_rederive(
    db: Session,
    monster: Monster,
    names: List[str],
    *,
    commit: bool = True,
) -> None:
    """
    写入规范化标签并立刻调用 recompute_and_autolabel：
      - 会更新 monster.tags
      - 会计算派生五维与定位（monster.role / derived.*）
    """
    from .derive_service import recompute_and_autolabel  # 延迟导入，避免循环依赖
    monster.tags = upsert_tags(db, names or [])
    recompute_and_autolabel(db, monster)
    if commit:
        db.commit()


# ---- 批量“自动匹配”：用正则建议标签 → set_tags_and_rederive ----
def auto_match_monsters(
    db: Session,
    *,
    ids: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    对给定 id 列表（为空则全量）执行：
      suggest_tags_for_monster -> set_tags_and_rederive
    返回处理统计与前 200 条明细。
    """
    from .tags_service import suggest_tags_for_monster  # 延迟导入，避免循环依赖

    if ids:
        id_list = [int(i) for i in ids if isinstance(i, (int, str)) and str(i).isdigit()]
        id_list = list(dict.fromkeys(id_list))
    else:
        id_list = db.scalars(select(Monster.id)).all()

    success = 0
    failed = 0
    details: List[Dict[str, Any]] = []

    for mid in id_list:
        m = db.get(Monster, int(mid))
        if not m:
            failed += 1
            details.append({"id": mid, "ok": False, "error": "monster not found"})
            continue
        try:
            tags = suggest_tags_for_monster(m)
            set_tags_and_rederive(db, m, tags, commit=False)
            success += 1
            details.append({"id": mid, "ok": True, "tags": tags})
        except Exception as e:
            db.rollback()
            failed += 1
            details.append({"id": mid, "ok": False, "error": str(e)})

    db.commit()
    return {
        "ok": True,
        "total": len(id_list),
        "success": success,
        "failed": failed,
        "details": details[:200],
    }