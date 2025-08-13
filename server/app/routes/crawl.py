# server/app/routes/crawl.py
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services.crawler_server import Kabu4399Crawler, MonsterRow
from ..services.skills_service import upsert_skill  # 按 (name, element, kind, power) 唯一写技能
from ..services.derive_service import recompute_and_autolabel
from ..db import SessionLocal
from .. import models as M

router = APIRouter(prefix="/api/v1/crawl/4399", tags=["crawl_4399"])
log = logging.getLogger(__name__)


def _to_payload(m: MonsterRow) -> Dict[str, object]:
    """
    API 对外样例/单抓输出：
    - 六维与 element
    - selected_skills：带 element/kind/power/description（与导入唯一键一致）
    - 附带获取渠道：type/new_type/method（便于前端查看）
    """
    skills = []
    for s in (m.selected_skills or []):
        # s 为 SkillRow 数据类
        n = (s.name or "").strip()
        if not n or n in {"推荐配招", "推荐技能", "推荐配招："}:
            continue
        skills.append({
            "name": n,
            "element": (s.element or "").strip(),
            "kind": (s.kind or "").strip(),
            "power": s.power,
            "description": (s.description or "").strip(),
        })
    return {
        "name": m.name,
        "element": m.element,
        "hp": m.hp,
        "speed": m.speed,
        "attack": m.attack,
        "defense": m.defense,
        "magic": m.magic,
        "resist": m.resist,
        "type": m.type,
        "new_type": m.new_type,
        "method": m.method,
        "selected_skills": skills,
    }


@router.get("/samples")
def crawl_samples(limit: int = Query(10, ge=1, le=100)):
    """
    抓取若干详情，返回“精选技能”完整字段（element/kind/power/description）。
    """
    crawler = Kabu4399Crawler()
    results: List[Dict[str, object]] = []

    for list_url in crawler.iter_list_pages():
        if not crawler._get(list_url):
            continue
        for detail_url in crawler._extract_detail_links_from_list(list_url):
            mon = crawler.fetch_detail(detail_url)
            if not mon:
                continue
            payload = _to_payload(mon)
            if payload["selected_skills"]:
                results.append(payload)
                if len(results) >= limit:
                    return results
    return results


@router.get("/fetch_one")
def fetch_one(url: str):
    """
    单个详情抓取，输出与 samples 一致的完整字段。
    """
    crawler = Kabu4399Crawler()
    row = crawler.fetch_detail(url)
    if not row:
        return {"detail": "fetch failed"}
    return _to_payload(row)


# --------- 写库工具（Monster 按 name 唯一；Skill 按 (name, element, kind, power) 唯一） ---------
def _upsert_one(db: Session, mon: MonsterRow, *, overwrite: bool = False, do_recompute: bool = True) -> Tuple[bool, int]:
    """
    将 MonsterRow 落入业务库：
      1) Monster upsert（唯一键 name）：
         写入 element/hp/speed/attack/defense/magic/resist 及获取渠道 method/type/new_type
         possess 由业务默认；如模型存在该列且新建时未设值，可在此保持默认（不强行覆盖）
      2) Skill upsert（唯一键 (name, element, kind, power)）：
         仅当新描述“更像描述或更长”时覆盖旧描述（由 skills_service.upsert_skill 处理）
      3) MonsterSkill 关联（若已存在跳过；将 selected=True；如有关联描述列且为空则补 s.description）
      4) 可选 recompute_and_autolabel()
    返回：(is_insert, affected_count) —— 受影响计入新增/更新的技能与关联变更条数
    """
    is_insert = False

    # 1) 怪物 upsert（以 name 唯一）
    m = db.query(M.Monster).filter(M.Monster.name == mon.name).first()
    if not m:
        m = M.Monster(name=mon.name)
        is_insert = True
        db.add(m)
        db.flush()  # 先拿到 id

    def _set(field: str, value: Optional[int | str | bool]):
        # 覆盖策略：overwrite=True 则无条件覆盖；否则仅在现值为空/0/"" 时写入
        if not hasattr(m, field):
            return
        if overwrite:
            setattr(m, field, value)
        else:
            cur = getattr(m, field)
            if cur in (None, 0, "", False) and value not in (None, ""):
                setattr(m, field, value)

    # 六维与 element
    _set("element", mon.element)
    _set("hp", mon.hp)
    _set("speed", mon.speed)
    _set("attack", mon.attack)
    _set("defense", mon.defense)
    _set("magic", mon.magic)
    _set("resist", mon.resist)

    # 获取渠道（method / type / new_type）
    _set("method", mon.method)
    _set("type", mon.type)           # 注意：你的模型若将列名定义为 type_，则相应改为 "type_"
    _set("new_type", mon.new_type)

    db.flush()

    # 2) 技能写库 + 3) 关联
    affected = 0
    if mon.selected_skills:
        for s in mon.selected_skills:
            name = (s.name or "").strip()
            if not name:
                continue
            element = (s.element or "").strip()
            kind = (s.kind or "").strip()
            power = s.power
            desc = (s.description or "").strip()

            # 2) upsert Skill（以四元组唯一）
            skill = upsert_skill(db, name=name, element=element, kind=kind, power=power, description=desc)
            db.flush()

            # 3) 建立 MonsterSkill 关联（并将 selected=True）
            if hasattr(M, "MonsterSkill"):
                ms = (
                    db.query(M.MonsterSkill)
                    .filter(M.MonsterSkill.monster_id == m.id, M.MonsterSkill.skill_id == skill.id)
                    .first()
                )
                if not ms:
                    # 若模型上有 selected/description 等列，尽可能写入
                    kwargs = {"monster_id": m.id, "skill_id": skill.id}
                    if hasattr(M.MonsterSkill, "selected"):
                        kwargs["selected"] = True
                    if hasattr(M.MonsterSkill, "description"):
                        kwargs["description"] = desc
                    ms = M.MonsterSkill(**kwargs)  # type: ignore
                    db.add(ms)
                    affected += 1
                else:
                    changed = False
                    if hasattr(ms, "selected") and not bool(getattr(ms, "selected")):
                        ms.selected = True  # type: ignore
                        changed = True
                    if hasattr(ms, "description"):
                        curd = (getattr(ms, "description") or "").strip()
                        if (not curd) and desc:
                            ms.description = desc  # type: ignore
                            changed = True
                    if changed:
                        affected += 1
            else:
                # 若没有显式关联模型，尝试通过多对多关系维护（secondary）
                if hasattr(m, "skills"):
                    already = any(getattr(s2, "id", None) == skill.id for s2 in (m.skills or []))
                    if not already:
                        m.skills.append(skill)  # type: ignore
                        affected += 1
                    # 无处写 selected/描述，只能依赖 Skill.description 已在 upsert_skill 中按策略更新
                else:
                    # 实在没有关联关系，只能略过（不计入 affected）
                    pass

    # 4) 可选：派生五维 + 自动标签
    if do_recompute:
        try:
            recompute_and_autolabel(db, m)
        except Exception as e:
            log.exception("recompute_and_autolabel failed for %s: %s", m.name, e)

    return is_insert, affected


class CrawlAllBody(BaseModel):
    limit: Optional[int] = None          # 最多处理多少只；不填全量
    overwrite: bool = False              # 是否覆盖怪物已有字段
    skip_existing: bool = True           # 已存在则跳过
    slugs: Optional[List[str]] = None    # 限定目录
    recompute: bool = True               # 导入后是否重算派生/标签


@router.post("/crawl_all")
def crawl_all(body: CrawlAllBody):
    """
    批量抓取并导入：
      - Monster 以 name 为唯一键；写 element/hp/.../method/type/new_type
      - Skill 以 (name, element, kind, power) 唯一；按“更像描述/更长”策略更新 description
      - 写 MonsterSkill 关联；若有 selected 字段则置 True
      - 可选导入后重算派生五维与建议标签
    """
    crawler = Kabu4399Crawler()

    if body.slugs:
        crawler.CANDIDATE_SLUGS = body.slugs

    seen = 0
    inserted = 0
    updated = 0
    skill_changes = 0

    with SessionLocal() as db:
        for detail_url in crawler.iter_detail_urls():
            mon = crawler.fetch_detail(detail_url)
            if not mon:
                continue
            seen += 1

            # 已有就跳过（按 name）
            exists = db.query(M.Monster.id).filter(M.Monster.name == mon.name).first()
            if exists and body.skip_existing:
                continue

            is_insert, skills_affected = _upsert_one(db, mon, overwrite=body.overwrite, do_recompute=body.recompute)
            if is_insert:
                inserted += 1
            else:
                updated += 1
            skill_changes += skills_affected
            db.commit()

            if body.limit and (inserted + updated) >= body.limit:
                break

    return {
        "ok": True,
        "seen": seen,
        "inserted": inserted,
        "updated": updated,
        "skills_changed": skill_changes,
    }