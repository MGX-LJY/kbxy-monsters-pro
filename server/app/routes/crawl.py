# server/app/routes/crawl.py
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple
from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..services.crawler_server import Kabu4399Crawler, MonsterRow, SkillRow
from ..services.skills_service import upsert_skills  # 修复：导入正确的 upsert_skills
from ..services.derive_service import recompute_and_autolabel
from ..db import SessionLocal
from .. import models as M

router = APIRouter(prefix="/api/v1/crawl/4399", tags=["crawl_4399"])
log = logging.getLogger(__name__)


def _skill_public(s: SkillRow) -> Dict[str, object]:
    """对外输出的技能字段：name/element/kind/power/description/level。"""
    return {
        "name": s.name,
        "element": s.element,
        "kind": s.kind,
        "power": s.power,
        "description": s.description,
        "level": s.level,
    }


def _to_payload(m: MonsterRow) -> Dict[str, object]:
    """
    仅保留：
      - 最高形态：name, element, hp, speed, attack, defense, magic, resist
      - 获取渠道：type, new_type, method
      - selected_skills: 完整字段（便于前端/导入）
    """
    skills = []
    for s in (m.selected_skills or []):
        # SkillRow 是 dataclass，用属性访问而不是 dict.get
        n = (s.name or "").strip()
        if not n or n in {"推荐配招", "推荐技能", "推荐配招："}:
            continue
        skills.append(_skill_public(s))

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
    从 4399 图鉴抓若干条样本，输出带 element/kind/power/description/level 的精选技能。
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
    抓取单个详情页；输出带 element/kind/power/description/level 的精选技能。
    """
    crawler = Kabu4399Crawler()
    row = crawler.fetch_detail(url)
    if not row:
        return {"detail": "fetch failed"}
    return _to_payload(row)


# --------- 写库工具（Monster 以 name 唯一；Skill 唯一键为 (name, element, kind, power)） ---------
def _upsert_one(db: Session, mon: MonsterRow, overwrite: bool = False, do_derive: bool = True) -> Tuple[bool, int]:
    """
    将 MonsterRow 落库。
    - 唯一键：Monster.name（使用 mon.name）
    - overwrite=False：已存在则只补齐空字段；True：覆盖基础字段
    - 技能：
        * Skill 全局去重，唯一 (name, element, kind, power)
        * 通过 MonsterSkill 关联，记录 selected/level/description
    返回：(is_insert, affected_skills)
    """
    is_insert = False

    # 1) 怪物 upsert（以 name 唯一）
    m = db.query(M.Monster).filter(M.Monster.name == mon.name).first()
    if not m:
        m = M.Monster(name=mon.name)
        is_insert = True
        db.add(m)
        db.flush()  # 先拿到 id

    def _set(field: str, value):
        if overwrite:
            setattr(m, field, value)
        else:
            cur = getattr(m, field)
            # 仅在当前字段空/None/0 时补齐
            if cur in (None, "", 0) and value not in (None, ""):
                setattr(m, field, value)

    # 基础属性/获取渠道/原始六维
    _set("element", mon.element)
    _set("hp", mon.hp)
    _set("speed", mon.speed)
    _set("attack", mon.attack)
    _set("defense", mon.defense)
    _set("magic", mon.magic)
    _set("resist", mon.resist)
    _set("type", mon.type)
    if mon.new_type is not None:
        _set("new_type", mon.new_type)
    _set("method", mon.method)
    db.flush()

    # 2) 技能 upsert + 关联
    affected = 0
    selected_list: List[SkillRow] = mon.selected_skills or []

    if selected_list:
        # 2.1 先批量 upsert 全部技能（唯一：name, element, kind, power）
        items = [
            (s.name, s.element, s.kind, s.power, s.description)
            for s in selected_list
            if (s.name or "").strip()
        ]
        skills = upsert_skills(db, items)

        # 为了快速找到对应 Skill -> SkillRow 的 level/selected/rel-desc
        # 构建一个键：(name, element, kind, power)
        def _key(sr: SkillRow) -> tuple:
            return (sr.name or "", sr.element or None, sr.kind or None, sr.power if sr.power is not None else None)

        sr_map = { _key(s): s for s in selected_list }

        # 2.2 逐一建立 MonsterSkill 关联（若已存在则跳过；空描述时可补）
        for sk in skills:
            # 找回对应 SkillRow 以拿 level/description
            sr = sr_map.get((sk.name, sk.element, sk.kind, sk.power))
            rel_desc = (sr.description or "").strip() if sr else ""
            rel_level = sr.level if sr else None

            ms = (
                db.query(M.MonsterSkill)
                .filter(M.MonsterSkill.monster_id == m.id, M.MonsterSkill.skill_id == sk.id)
                .first()
            )
            if not ms:
                ms = M.MonsterSkill(
                    monster_id=m.id,
                    skill_id=sk.id,
                    selected=True,
                    level=rel_level,
                    description=rel_desc or None,
                )
                db.add(ms)
                affected += 1
            else:
                changed = False
                if ms.selected is not True:
                    ms.selected = True; changed = True
                if ms.level is None and rel_level is not None:
                    ms.level = rel_level; changed = True
                if (not (ms.description or "").strip()) and rel_desc:
                    ms.description = rel_desc; changed = True
                if changed:
                    affected += 1

    # 3) 可选：重算派生 + 自动定位/标签
    if do_derive:
        recompute_and_autolabel(db, m)

    return is_insert, affected


class CrawlAllBody(BaseModel):
    limit: Optional[int] = None
    overwrite: bool = False
    skip_existing: bool = True
    slugs: Optional[List[str]] = None
    derive: bool = True  # 是否在导入后立即派生/自动标签（默认开启）


@router.post("/crawl_all")
def crawl_all(body: CrawlAllBody):
    """
    全量/批量爬取：
      - 若 skip_existing=True：库里已存在 name 则跳过
      - 否则执行 upsert；overwrite=True 时覆盖基础字段
      - 技能按“全局 Skill + MonsterSkill 关联”处理（唯一键为 name/element/kind/power）
      - 可选：导入后调用 recompute_and_autolabel()
    """
    crawler = Kabu4399Crawler()

    if body.slugs:
        crawler.CANDIDATE_SLUGS = body.slugs

    seen = 0
    inserted = 0
    updated = 0
    skills_changed = 0

    with SessionLocal() as db:
        for detail_url in crawler.iter_detail_urls():
            mon = crawler.fetch_detail(detail_url)
            if not mon:
                continue
            seen += 1

            # 是否跳过
            exists = db.query(M.Monster.id).filter(M.Monster.name == mon.name).first()
            if exists and body.skip_existing:
                continue

            is_insert, n_aff = _upsert_one(db, mon, overwrite=body.overwrite, do_derive=body.derive)
            if is_insert:
                inserted += 1
            else:
                updated += 1
            skills_changed += n_aff
            db.commit()

            if body.limit and (inserted + updated) >= body.limit:
                break

    return {
        "ok": True,
        "fetched": seen,
        "inserted": inserted,
        "updated": updated,
        "skills_changed": skills_changed,
        "skipped": max(0, seen - inserted - updated),
    }