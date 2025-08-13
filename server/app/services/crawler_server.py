# server/app/services/crawler_server.py
from __future__ import annotations

import re
import time
import random
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Generator, Iterable, Optional, Tuple, Set
from urllib.parse import urljoin

from DrissionPage import SessionPage


log = logging.getLogger(__name__)


# ---------- 数据模型 ----------
@dataclass
class SkillRow:
    name: str
    level: Optional[int]
    element: str
    kind: str         # 物理 / 法术 / 特殊
    power: Optional[int]
    pp: Optional[int]
    description: str

@dataclass
class MonsterRow:
    name: str
    hp: int
    speed: int
    attack: int
    defense: int
    magic: int
    resist: int
    source_url: str
    img_url: Optional[str] = None
    series_names: List[str] = field(default_factory=list)            # 同页多形态名字
    skills: List[SkillRow] = field(default_factory=list)             # 全量技能
    recommended_names: List[str] = field(default_factory=list)       # “推荐配招”解析出的技能名
    selected_skills: List[Dict[str, str]] = field(default_factory=list)  # 依据推荐筛出的技能（仅 name/description）


# ---------- 工具 ----------
_INT = re.compile(r"-?\d+")
_WS = re.compile(r"\s+")
def _to_int(s: str | None) -> Optional[int]:
    if not s:
        return None
    m = _INT.search(s)
    return int(m.group()) if m else None

def _clean(s: str | None) -> str:
    if not s:
        return ""
    return _WS.sub(" ", s).strip()

def _abs(base: str, href: str) -> str:
    return urljoin(base, href)

def _is_detail_link(href: str) -> bool:
    # /kabuxiyou/yaoguaidaquan/<slug>/YYYYMM-??-ID.html 或 /.../ID.html
    return bool(href) and '/kabuxiyou/yaoguaidaquan/' in href and href.endswith('.html')


# ---------- 爬虫主体 ----------
class Kabu4399Crawler:
    """
    4399【卡布西游-妖怪大全】爬虫（requests 模式）
    - 列表页：抽取 ul#dq_list 下 li > a 的详情链接
    - 详情页：解析两张表：
        1) “资料/种族值”表 => 可能多行（同页多形态），先全取，最终只保留“最高形态”
        2) “技能表” => 解析为 SkillRow 列表
    - 额外：解析“推荐配招”，并在技能表中匹配出对应技能（仅 name/description）
    """
    BASE = "https://news.4399.com"
    ROOT = "/kabuxiyou/yaoguaidaquan/"
    CANDIDATE_SLUGS = [
        "huoxi","jinxi","muxi","shuixi","tuxi","yixi","guaixi",
        "moxi","yaoxi","fengxi","duxi","leixi","huanxi",
        "bing","lingxi","jixie","huofengxi","mulingxi",
        "shengxi","tuhuanxi","shuiyaoxi","yinxi",
    ]

    def __init__(
        self,
        *,
        throttle_range: Tuple[float, float] = (0.6, 1.2),
        max_retries: int = 3,
        timeout: float = 15.0,
        headers: Optional[Dict[str, str]] = None,
    ) -> None:
        self.sp = SessionPage()
        self.sp.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/123.0 Safari/537.36"
            ),
            "Accept-Language": "zh-CN,zh;q=0.9",
        })
        if headers:
            self.sp.session.headers.update(headers)
        self.throttle_range = throttle_range
        self.max_retries = max_retries
        self.timeout = timeout
        self.seen_urls: Set[str] = set()

    # ---- 基础 GET（带重试 + 随机节流） ----
    def _get(self, url: str) -> bool:
        for i in range(self.max_retries):
            try:
                self.sp.get(url, timeout=self.timeout)
                if self.sp.response and self.sp.response.ok:
                    return True
            except Exception as e:
                log.warning("GET fail (%s/%s) %s -> %s", i+1, self.max_retries, url, e)
            time.sleep(random.uniform(*self.throttle_range))
        return False

    # ---- 列表页：抽取详情链接 ----
    def _extract_detail_links_from_list(self, page_url: str) -> List[str]:
        links: List[str] = []
        for a in self.sp.eles('t:ul@@id=dq_list t:a'):
            href = a.attr('href') or ""
            if _is_detail_link(href):
                links.append(_abs(self.BASE, href))
        if not links:
            for a in self.sp.eles('t:a'):
                href = a.attr('href') or ""
                if _is_detail_link(href):
                    links.append(_abs(self.BASE, href))
        out, seen = [], set()
        for u in links:
            if u not in seen:
                seen.add(u); out.append(u)
        log.info("list[%s] -> %d detail links", page_url, len(out))
        return out

    def iter_list_pages(self) -> Iterable[str]:
        yield _abs(self.BASE, self.ROOT)
        for slug in self.CANDIDATE_SLUGS:
            yield _abs(self.BASE, f"{self.ROOT}{slug}/")

    def iter_detail_urls(self) -> Generator[str, None, None]:
        for list_url in self.iter_list_pages():
            if not self._get(list_url):
                continue
            for u in self._extract_detail_links_from_list(list_url):
                if u not in self.seen_urls:
                    self.seen_urls.add(u)
                    yield u

    # ---- 详情页解析 ----
    def _pick_page_title_name(self) -> Optional[str]:
        h1 = self.sp.ele('t:h1')
        if not h1:
            return None
        txt = _clean(h1.text)
        m = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·]+", txt)
        return m[-1] if m else None

    def _parse_stats_table(self, page_url: str) -> List[MonsterRow]:
        results: List[MonsterRow] = []
        target_tables = []
        for tbl in self.sp.eles('t:table'):
            txt = _clean(tbl.text)
            if ("种族值" in txt) or ("资料" in txt and "体力" in txt and "攻击" in txt):
                target_tables.append(tbl)
        if not target_tables:
            return results

        tbl = target_tables[-1]
        rows = tbl.eles('t:tr')
        if len(rows) < 3:
            return results

        header_idx = None
        for i, tr in enumerate(rows[:6]):
            t = _clean(tr.text)
            if all(k in t for k in ("体力", "速度", "攻击", "防御", "法术", "抗性")):
                header_idx = i
                break
        if header_idx is None:
            return results

        title_name = self._pick_page_title_name()
        img_ele = self.sp.ele('t:img')
        page_img = img_ele.attr('src') if img_ele else None
        if page_img and page_img.startswith('//'):
            page_img = _abs(self.BASE, page_img)

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                continue
            vals = [_clean(td.text) for td in tds]
            if len(vals) >= 8:
                name = vals[0] or vals[1]
                cols = vals[2:8]
            else:
                name = vals[0]
                cols = vals[1:7]
            if len(cols) != 6:
                continue
            m = MonsterRow(
                name=_clean(name),
                hp=_to_int(cols[0]) or 0,
                speed=_to_int(cols[1]) or 0,
                attack=_to_int(cols[2]) or 0,
                defense=_to_int(cols[3]) or 0,
                magic=_to_int(cols[4]) or 0,
                resist=_to_int(cols[5]) or 0,
                source_url=page_url,
                img_url=page_img,
            )
            results.append(m)

        if title_name:
            for r in results:
                r.series_names = [rr.name for rr in results]
            # 仅用于信息参考，不参与最终输出选择
        return results

    def _parse_skills_table(self) -> List[SkillRow]:
        skills: List[SkillRow] = []
        target_tbl = None
        for tbl in self.sp.eles('t:table'):
            if "技能表" in _clean(tbl.text):
                target_tbl = tbl
        if not target_tbl:
            return skills

        rows = target_tbl.eles('t:tr')
        if len(rows) <= 2:
            return skills

        header_idx = None
        for i, tr in enumerate(rows[:6]):
            t = _clean(tr.text)
            if all(k in t for k in ("技能名称", "等级", "技能属性", "类型", "威力", "PP", "技能描述")):
                header_idx = i
                break
        if header_idx is None:
            header_idx = 0

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                continue
            vals = [_clean(td.text) for td in tds[:7]]
            name = vals[0]
            if not name or name == "无":
                continue
            level = _to_int(vals[1])
            element = vals[2]
            kind = vals[3]
            power = _to_int(vals[4])
            pp = _to_int(vals[5])
            desc = vals[6]
            skills.append(SkillRow(name, level, element, kind, power, pp, desc))
        return skills

    # ---- 推荐配招：解析 + 精选 ----
    def _parse_recommended_names(self) -> List[str]:
        for tbl in self.sp.eles('t:table'):
            for tr in tbl.eles('t:tr'):
                tds = tr.eles('t:td')
                if not tds:
                    continue
                first = _clean(tds[0].text)
                if "推荐配招" in first:
                    raw = _clean(" ".join((td.text or "") for td in tds[1:])) if len(tds) > 1 else _clean(tr.text)
                    raw = raw.replace("：", " ").replace("&nbsp;", " ").replace("\u3000", " ")
                    parts = re.split(r"[+＋、/，,；;|\s]+", raw)
                    names, seen = [], set()
                    for p in parts:
                        n = _clean(p)
                        if not n or n == "无":
                            continue
                        if n not in seen:
                            seen.add(n); names.append(n)
                    return names
        return []

    def _select_skills_from_recommend(self, rec_names: List[str], skills: List[SkillRow]) -> List[Dict[str, str]]:
        """按推荐名在已解析技能中匹配，返回 [{name, description}, ...]（不含 PP）。"""
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "")

        skill_map = {norm(s.name): s for s in skills}
        out: List[Dict[str, str]] = []
        for rec in rec_names:
            key = norm(rec)
            s = skill_map.get(key)
            if not s:
                for cand in skills:
                    n = norm(cand.name)
                    if key and (key in n or n in key):
                        s = cand
                        break
            if s:
                out.append({"name": s.name, "description": s.description})
            else:
                out.append({"name": rec, "description": ""})
        return out

    @staticmethod
    def _six_sum(m: MonsterRow) -> int:
        return int(m.hp + m.speed + m.attack + m.defense + m.magic + m.resist)

    def fetch_detail(self, url: str) -> Optional[MonsterRow]:
        """
        抓取并解析详情页，只返回“最高形态”一条 MonsterRow：
        - 以六维和的最大值为最高形态（更稳妥兼容不同页顺序）
        - 解析推荐配招，并在技能表中筛选出对应技能（仅 name/description）
        """
        if not self._get(url):
            return None

        monsters = self._parse_stats_table(url)
        if not monsters:
            return None

        skills = self._parse_skills_table()
        rec_names = self._parse_recommended_names()
        selected = self._select_skills_from_recommend(rec_names, skills) if rec_names else []

        # 仅保留最高形态
        best = max(monsters, key=self._six_sum)
        best.skills = skills
        best.recommended_names = rec_names
        best.selected_skills = selected
        return best

    # ---- 顶层 API ----
    def crawl_all(
        self,
        *,
        persist: Optional[callable] = None,
    ) -> Generator[MonsterRow, None, None]:
        """遍历所有列表页，产出各详情页的“最高形态”记录。"""
        for detail_url in self.iter_detail_urls():
            m = self.fetch_detail(detail_url)
            if not m:
                continue
            if persist:
                try:
                    persist(m)
                except Exception as e:
                    log.exception("persist error: %s", e)
            yield m
            time.sleep(random.uniform(*self.throttle_range))


# ---------- 示例持久化（可接你自己的入库逻辑） ----------
def example_persist(mon: MonsterRow) -> None:
    log.info(
        "PERSIST %s hp=%s atk=%s spd=%s rec=%d sel=%d skills=%d",
        mon.name, mon.hp, mon.attack, mon.speed,
        len(mon.recommended_names), len(mon.selected_skills), len(mon.skills)
    )


# ---------- 输出裁剪 ----------
def _to_public_json(m: MonsterRow) -> Dict[str, object]:
    """
    仅保留：
      - 最高形态：name, hp, speed, attack, defense, magic, resist
      - selected_skills: [{name, description}]
    """
    return {
        "name": m.name,
        "hp": m.hp,
        "speed": m.speed,
        "attack": m.attack,
        "defense": m.defense,
        "magic": m.magic,
        "resist": m.resist,
        "selected_skills": m.selected_skills,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = Kabu4399Crawler()

    # 收集前 10 个含“推荐配招”的角色（最高形态）并输出 JSON
    N = 10
    out: List[Dict[str, object]] = []
    for item in crawler.crawl_all(persist=example_persist):
        if item.selected_skills:  # 只要能解析出推荐配招
            out.append(_to_public_json(item))
            if len(out) >= N:
                break

    print(json.dumps(out, ensure_ascii=False, indent=2))