# server/app/routes/crawl.py
from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..db import SessionLocal
from .. import models as M
from ..services.crawler_server import Kabu4399Crawler, MonsterRow, SkillRow
from ..services.skills_service import upsert_skills  # Skill 去重 + 批量 upsert（唯一键：name/element/kind/power）
from ..services.derive_service import recompute_and_autolabel

router = APIRouter(prefix="/api/v1/crawl", tags=["crawl_4399"])
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
        n = (s.name or "").strip()
        # 过滤站内“推荐配招”等非技能行
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
        * 在同一次 flush/commit 中，显式“去重 + 本地集合防重复 + 数据库查询兜底”，避免唯一约束冲突
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
        # 2.0 输入去噪：过滤空名/推荐行，按唯一键去重（最后一次出现覆盖前面）
        def _key_from_sr(sr: SkillRow) -> tuple:
            return (
                (sr.name or "").strip(),
                sr.element or None,
                sr.kind or None,
                sr.power if sr.power is not None else None,
            )

        uniq_map: Dict[tuple, SkillRow] = {}
        for s in selected_list:
            n = (s.name or "").strip()
            if not n or n in {"推荐配招", "推荐技能", "推荐配招："}:
                continue
            uniq_map[_key_from_sr(s)] = s  # 后出现的覆盖前者（level/desc 以此为准）

        if uniq_map:
            # 2.1 先批量 upsert 全部技能（唯一：name, element, kind, power）
            items = [
                (k[0], k[1], k[2], k[3], uniq_map[k].description)
                for k in uniq_map.keys()
            ]
            skills = upsert_skills(db, items)  # 返回对应的 Skill 记录
            db.flush()

            # 2.2 建立 MonsterSkill 关联（显式去重 + 查询兜底）
            linked_local = set()  # (monster_id, skill_id) 本次循环内去重
            for sk in skills:
                if not sk:  # 防御式
                    continue

                # 还原 SkillRow（拿 level/description）
                sr = uniq_map.get((sk.name, sk.element, sk.kind, sk.power))
                rel_desc = (sr.description or "").strip() if sr else ""
                rel_level = sr.level if sr else None

                pair_key = (m.id, sk.id)
                if pair_key in linked_local:
                    continue

                # 数据库兜底检查：避免同事务内重复插入
                ms = (
                    db.query(M.MonsterSkill)
                    .filter(
                        M.MonsterSkill.monster_id == m.id,
                        M.MonsterSkill.skill_id == sk.id,
                    )
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
                    # 立刻 flush，确保后续同事务查询能看到，避免唯一约束
                    db.flush()
                    linked_local.add(pair_key)
                    affected += 1
                else:
                    changed = False
                    if ms.selected is not True:
                        ms.selected = True
                        changed = True
                    if ms.level is None and rel_level is not None:
                        ms.level = rel_level
                        changed = True
                    if (not (ms.description or "").strip()) and rel_desc:
                        ms.description = rel_desc
                        changed = True
                    if changed:
                        db.flush()
                        affected += 1

    # 3) 可选：重算派生 + 自动定位/标签
    if do_derive:
        recompute_and_autolabel(db, m)
        db.flush()

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
      - 同事务内对 MonsterSkill 关联显式去重并 flush，彻底规避 UNIQUE 约束冲突
      - 可选：导入后调用 recompute_and_autolabel()
    """
    crawler = Kabu4399Crawler()

    if body.slugs:
        # 可定向拉取指定条目
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

            # 跳过已存在
            exists = db.query(M.Monster.id).filter(M.Monster.name == mon.name).first()
            if exists and body.skip_existing:
                continue

            is_insert, n_aff = _upsert_one(
                db,
                mon,
                overwrite=body.overwrite,
                do_derive=body.derive,
            )

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