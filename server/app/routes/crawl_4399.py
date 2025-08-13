# server/app/routes/crawl_4399.py
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services.crawler_server import Kabu4399Crawler, MonsterRow
from ..db import SessionLocal
from .. import models as M

router = APIRouter(prefix="/api/v1/crawl/4399", tags=["crawl_4399"])
log = logging.getLogger(__name__)


def _to_payload(m: MonsterRow) -> Dict[str, object]:
    # 仅保留六维 + 精选技能 + 系别（element）
    skills = []
    for s in (m.selected_skills or []):
        n = (s.get("name") or "").strip()
        if not n or n in {"推荐配招", "推荐技能", "推荐配招："}:
            continue
        skills.append({
            "name": n,
            "description": (s.get("description") or "").strip(),
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
        "selected_skills": skills,
    }


@router.get("/samples")
def crawl_samples(limit: int = Query(10, ge=1, le=100)):
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
    crawler = Kabu4399Crawler()
    row = crawler.fetch_detail(url)
    if not row:
        return {"detail": "fetch failed"}
    return _to_payload(row)


# --------- 写库工具（已修复“Skill 没 monster_id”问题） ---------
def _upsert_one(db: Session, mon: MonsterRow, overwrite: bool = False) -> Tuple[bool, int]:
    """
    将 MonsterRow 落库。
    - 唯一键：Monster.name_final（用 mon.name）
    - overwrite=False：已存在则只补齐空字段；True：无条件覆盖六维/元素
    - 技能：
        * Skill 是全局表（无 monster_id）
        * 与 Monster 通过关联（MonsterSkill 或 secondary 表）绑定
        * 描述优先写在关联记录（若无该列，则只在 Skill.description 为空时补齐）
    返回：(is_insert, affected_skills) —— affected_skills 指新增/更新的关联或描述条数
    """
    is_insert = False

    # 1) 怪物 upsert（以 name_final 唯一）
    m = db.query(M.Monster).filter(M.Monster.name_final == mon.name).first()
    if not m:
        m = M.Monster(name_final=mon.name)
        is_insert = True
        db.add(m)
        db.flush()  # 先拿到 id

    def _set(field: str, value: Optional[int | str]):
        if overwrite:
            setattr(m, field, value)
        else:
            cur = getattr(m, field)
            if cur in (None, 0, "") and value not in (None, ""):
                setattr(m, field, value)

    _set("element", mon.element)
    _set("hp", mon.hp)
    _set("speed", mon.speed)
    _set("attack", mon.attack)
    _set("defense", mon.defense)
    _set("magic", mon.magic)
    _set("resist", mon.resist)
    db.flush()

    # 2) 技能 upsert（全局 Skill + 关联 Monster）
    affected = 0

    def _get_or_create_skill(name: str, desc: str):
        sk = db.query(M.Skill).filter(M.Skill.name == name).first()
        if not sk:
            # Skill 无 monster_id，只创建全局技能；描述只在“像描述”或需要留痕时写入
            sk = M.Skill(name=name, description=(desc or "").strip())
            db.add(sk)
            db.flush()
        else:
            # 只在 Skill.description 为空而新抓到有描述时补齐（避免跨怪覆盖）
            if not (sk.description or "").strip() and (desc or "").strip():
                sk.description = (desc or "").strip()
                affected_inc = 1
            else:
                affected_inc = 0
            return sk, affected_inc
        return sk, 1  # 新建技能也算一次变更

    def _link_skill(monster: M.Monster, skill: M.Skill, desc: str) -> int:
        """
        建立 monster-skill 关联；若有 MonsterSkill 模型则把描述写到关联上。
        返回 1 表示有新增/更新，0 表示无变化。
        """
        # 优先使用显式关联模型
        if hasattr(M, "MonsterSkill"):
            ms = (
                db.query(M.MonsterSkill)
                .filter(M.MonsterSkill.monster_id == monster.id, M.MonsterSkill.skill_id == skill.id)
                .first()
            )
            if not ms:
                ms = M.MonsterSkill(monster_id=monster.id, skill_id=skill.id, description=(desc or "").strip())
                db.add(ms)
                return 1
            else:
                if not (getattr(ms, "description", "") or "").strip() and (desc or "").strip():
                    ms.description = (desc or "").strip()
                    return 1
                return 0

        # 否则回退用多对多关系（secondary 表），通过 m.skills 维护关联
        if hasattr(monster, "skills"):
            already = any(getattr(s, "id", None) == skill.id for s in (monster.skills or []))
            changed = 0
            if not already:
                monster.skills.append(skill)
                changed = 1
            # 如果没有关联描述列，只能尽量补齐 Skill.description（为空才填）
            if not (skill.description or "").strip() and (desc or "").strip():
                skill.description = (desc or "").strip()
                changed = 1
            return changed

        # 最后兜底：无法建关联，只能把全局描述补齐（为空才填）
        if not (skill.description or "").strip() and (desc or "").strip():
            skill.description = (desc or "").strip()
            return 1
        return 0

    if mon.selected_skills:
        # 为了避免重复查询，先把已关联的名字做个集合（若能拿到）
        existing_names = set()
        try:
            if hasattr(m, "skills") and m.skills:
                existing_names = { (s.name or "").strip() for s in m.skills if getattr(s, "name", None) }
        except Exception:
            existing_names = set()

        for s in mon.selected_skills:
            name = (s.get("name") or "").strip()
            if not name:
                continue
            desc = (s.get("description") or "").strip()

            # 全局技能
            skill = db.query(M.Skill).filter(M.Skill.name == name).first()
            if not skill:
                skill = M.Skill(name=name, description=desc)
                db.add(skill)
                db.flush()
                affected += 1
            else:
                if not (skill.description or "").strip() and desc:
                    skill.description = desc
                    affected += 1

            # 建立关联
            affected += _link_skill(m, skill, desc)

    return is_insert, affected


class CrawlAllBody(BaseModel):
    limit: Optional[int] = None
    overwrite: bool = False
    skip_existing: bool = True
    slugs: Optional[List[str]] = None


@router.post("/crawl_all")
def crawl_all(body: CrawlAllBody):
    """
    全量/批量爬取：
      - 若 skip_existing=True：库里已存在 name_final 则直接跳过
      - 否则执行 upsert；overwrite=True 时覆盖六维/元素
      - 技能按“全局 Skill + 关联”处理（兼容有无 MonsterSkill 模型）
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

            exists = db.query(M.Monster.id).filter(M.Monster.name_final == mon.name).first()
            if exists and body.skip_existing:
                continue

            is_insert, skills_affected = _upsert_one(db, mon, overwrite=body.overwrite)
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