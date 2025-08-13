# server/app/routes/crawl_4399.py
from __future__ import annotations

from typing import Dict, List, Optional
from fastapi import APIRouter, Query
from .deps import get_logger
from ..services.crawler_server import Kabu4399Crawler, MonsterRow

router = APIRouter(prefix="/api/v1/crawl/4399", tags=["crawl_4399"])
log = get_logger(__name__)


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
        "element": m.element,  # 新增：系别
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
    """
    动态抓取 4399 妖怪详情（最高形态），返回含“推荐配招”的前 N 条。
    仅输出：name、element、hp、speed、attack、defense、magic、resist、selected_skills[{name,description}]
    """
    crawler = Kabu4399Crawler()
    results: List[Dict[str, object]] = []

    for list_url in crawler.iter_list_pages():
        if not crawler._get(list_url):
            continue
        for detail_url in crawler._extract_detail_links_from_list(list_url):
            mon = crawler.fetch_detail(detail_url)  # 已返回最高形态
            if not mon:
                continue
            payload = _to_payload(mon)
            # 必须有有效精选技能才纳入
            if payload["selected_skills"]:
                results.append(payload)
                if len(results) >= limit:
                    return results
    return results


@router.get("/fetch_one")
def fetch_one(url: str):
    """
    针对单个详情页抓取，返回最高形态裁剪后的结果。
    """
    crawler = Kabu4399Crawler()
    # 有库就命中缓存，无库就纯抓取
    row = crawler.get_or_fetch(url)
    return _to_payload(row)
