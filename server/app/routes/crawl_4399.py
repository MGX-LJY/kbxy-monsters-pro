from __future__ import annotations

from typing import Dict, List, Optional
from fastapi import APIRouter, Query
from .deps import get_logger
from ..services.crawler_server import Kabu4399Crawler, MonsterRow

router = APIRouter(prefix="/api/v1/crawl/4399", tags=["crawl_4399"])
log = get_logger(__name__)


def _six_sum(m: MonsterRow) -> int:
    return int(m.hp) + int(m.speed) + int(m.attack) + int(m.defense) + int(m.magic) + int(m.resist)


def _pick_highest(monsters: List[MonsterRow]) -> Optional[MonsterRow]:
    return max(monsters, key=_six_sum) if monsters else None


def _to_payload(m: MonsterRow) -> Dict[str, object]:
    # 仅保留六维 + 精选技能（去掉“推荐配招”等噪声项）
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
    动态抓取 4399 妖怪详情，返回含“推荐配招”的最高形态 N 条。
    仅输出：name、hp、speed、attack、defense、magic、resist、selected_skills[{name,description}]
    """
    crawler = Kabu4399Crawler()
    results: List[Dict[str, object]] = []

    for list_url in crawler.iter_list_pages():
        if not crawler._get(list_url):
            continue
        for detail_url in crawler._extract_detail_links_from_list(list_url):
            mons = crawler.fetch_detail(detail_url)
            if not mons:
                continue
            top = _pick_highest(mons)
            if not top:
                continue
            payload = _to_payload(top)
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
    mons = crawler.fetch_detail(url)
    top = _pick_highest(mons)
    if not top:
        return {}
    payload = _to_payload(top)
    return payload