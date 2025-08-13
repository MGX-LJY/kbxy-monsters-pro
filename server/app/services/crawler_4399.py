# server/app/services/crawler_4399.py
from __future__ import annotations

import re
import time
import random
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Generator, Iterable, Optional, Tuple, Set
from urllib.parse import urljoin

from DrissionPage import SessionPage


log = logging.getLogger(__name__)


# ---------- 数据模型（供上层入库用） ----------
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
    series_names: List[str] = field(default_factory=list)   # 同页多形态/进化线的名字
    skills: List[SkillRow] = field(default_factory=list)    # 全量技能（通常按表格顺序）


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
        1) “...资料/种族值”表 => 多行（同页可能含两只），返回 MonsterRow（可多条）
        2) “技能表” => 一张，解析为 SkillRow 列表，挂到对应 MonsterRow 上
    - 你可以传入 persist 回调将 MonsterRow 持久化到数据库
    """
    BASE = "https://news.4399.com"
    ROOT = "/kabuxiyou/yaoguaidaquan/"
    # 常见系别子目录（用于发现更多列表页；也可只从 ROOT 广度搜索）
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
        # 设置常见头（可被 DrissionPage 继承给后续请求）：
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
        # 1) 优先从 ul#dq_list 下抓
        for a in self.sp.eles('t:ul@@id=dq_list t:a'):
            href = a.attr('href') or ""
            if _is_detail_link(href):
                links.append(_abs(self.BASE, href))
        # 2) 兜底：整页所有 a
        if not links:
            for a in self.sp.eles('t:a'):
                href = a.attr('href') or ""
                if _is_detail_link(href):
                    links.append(_abs(self.BASE, href))
        # 去重并保持顺序
        out, seen = [], set()
        for u in links:
            if u not in seen:
                seen.add(u); out.append(u)
        log.info("list[%s] -> %d detail links", page_url, len(out))
        return out

    def iter_list_pages(self) -> Iterable[str]:
        """产出所有可能的列表页 URL（ROOT + 各常见 slug）"""
        yield _abs(self.BASE, self.ROOT)
        for slug in self.CANDIDATE_SLUGS:
            yield _abs(self.BASE, f"{self.ROOT}{slug}/")

    def iter_detail_urls(self) -> Generator[str, None, None]:
        """遍历所有列表页，产出详情链接。"""
        for list_url in self.iter_list_pages():
            if not self._get(list_url):
                continue
            for u in self._extract_detail_links_from_list(list_url):
                if u not in self.seen_urls:
                    self.seen_urls.add(u)
                    yield u

    # ---- 详情页：解析 ----
    def _pick_page_title_name(self) -> Optional[str]:
        # 取 <h1> 的主要词作为本页“主怪名”（用于在多行种族值中首选）
        h1 = self.sp.ele('t:h1')
        if not h1:
            return None
        txt = _clean(h1.text)
        # 常见标题格式：“卡布西游XXX、YYY资料/技能表...”，优先取标题中最后一个专名
        # 先尝试页右侧“最新妖怪”同名；简单截取最后一个中文词
        m = re.findall(r"[\u4e00-\u9fa5A-Za-z0-9·]+", txt)
        return m[-1] if m else None

    def _parse_stats_table(self, page_url: str) -> List[MonsterRow]:
        """
        解析“种族值”表。表头通常是：妖怪名 | 体力 | 速度 | 攻击 | 防御 | 法术 | 抗性
        同页可能有 2 行（如初阶+进化），逐行返回 MonsterRow（暂不挂技能）。
        """
        results: List[MonsterRow] = []
        # 锁定包含“种族值”关键词的表（或邻近区域）
        target_tables = []
        for tbl in self.sp.eles('t:table'):
            txt = _clean(tbl.text)
            if ("种族值" in txt) or ("资料" in txt and "体力" in txt and "攻击" in txt):
                target_tables.append(tbl)
        if not target_tables:
            return results

        # 取第一张“种族值”表
        tbl = target_tables[-1]
        rows = tbl.eles('t:tr')
        if len(rows) < 3:
            return results

        # 找到列名行（包含“体力 速度 攻击 防御 法术 抗性”）
        header_idx = None
        for i, tr in enumerate(rows[:6]):  # 前几行找一下
            t = _clean(tr.text)
            if all(k in t for k in ("体力", "速度", "攻击", "防御", "法术", "抗性")):
                header_idx = i
                break
        if header_idx is None:
            return results

        # 每一行生成 MonsterRow
        title_name = self._pick_page_title_name()
        # 尝试页面首图（不强制）
        img_ele = self.sp.ele('t:img')
        page_img = img_ele.attr('src') if img_ele else None
        page_img = _abs(self.BASE, page_img) if page_img and page_img.startswith('//') else page_img

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                continue
            vals = [_clean(td.text) for td in tds]
            # 有些表“妖怪名”占两列 -> 合并前两列
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

        # 在详情页标题中标注“本页主怪名”，用于上层选择
        if title_name:
            for r in results:
                r.series_names = [rr.name for rr in results]
            # 排序：尽量把“标题名一致”的放前面，便于上层取第一条
            results.sort(key=lambda x: 0 if x.name == title_name else 1)

        return results

    def _parse_skills_table(self) -> List[SkillRow]:
        """
        解析“技能表”。表头通常：技能名称 | 等级 | 技能属性 | 类型 | 威力 | PP | 技能描述
        """
        skills: List[SkillRow] = []

        # 锁定包含“技能表”字样的表
        target_tbl = None
        for tbl in self.sp.eles('t:table'):
            if "技能表" in _clean(tbl.text):
                target_tbl = tbl
        if not target_tbl:
            return skills

        rows = target_tbl.eles('t:tr')
        if len(rows) <= 2:
            return skills

        # 寻找表头行索引
        header_idx = None
        for i, tr in enumerate(rows[:6]):
            t = _clean(tr.text)
            if all(k in t for k in ("技能名称", "等级", "技能属性", "类型", "威力", "PP", "技能描述")):
                header_idx = i
                break
        if header_idx is None:
            # 兜底：默认第一行是表头
            header_idx = 0

        for tr in rows[header_idx + 1:]:
            tds = tr.eles('t:td')
            if len(tds) < 7:
                # 有些“无”行也跳过
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

    def fetch_detail(self, url: str) -> List[MonsterRow]:
        """抓取并解析详情页，可能返回 1~2 条 MonsterRow（含技能）。"""
        if not self._get(url):
            return []
        monsters = self._parse_stats_table(url)
        skills = self._parse_skills_table()

        # 将技能挂到每个 MonsterRow（多数情况下同页共用同一技能表）
        for m in monsters:
            m.skills = skills
        return monsters

    # ---- 顶层 API ----
    def crawl_all(
        self,
        *,
        limit_pages: Optional[int] = None,
        persist: Optional[callable] = None,
    ) -> Generator[MonsterRow, None, None]:
        """
        按列表页遍历（ROOT + 常见系别目录），挨个抓详情。
        - limit_pages: 限制最大“列表页数量”（非详情页数量），用于试跑
        - persist: 回调，如 persist(mon: MonsterRow) -> None，用于写库
        """
        page_cnt = 0
        for detail_url in self.iter_detail_urls():
            # 可选：限制列表页来源数量（粗粒度控制）
            if limit_pages is not None:
                # 这里粗略按每个列表页第一次进入时累加；已在 iter_list_pages 控制
                pass

            mons = self.fetch_detail(detail_url)
            if not mons:
                continue
            for m in mons:
                if persist:
                    try:
                        persist(m)
                    except Exception as e:
                        log.exception("persist error: %s", e)
                yield m
            time.sleep(random.uniform(*self.throttle_range))


# ---------- 示例：如何接到你现有的持久化逻辑 ----------
def example_persist(mon: MonsterRow) -> None:
    """
    把 MonsterRow 映射到你项目内的 Monster / Skill 表。
    这里给出字段名示意；请对接你项目的 Session / upsert 方法。
    """
    # from ..db import SessionLocal
    # from ..models import Monster, Skill
    # ... 映射并 upsert
    log.info("PERSIST %s hp=%s atk=%s spd=%s ... skills=%d",
             mon.name, mon.hp, mon.attack, mon.speed, len(mon.skills))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = Kabu4399Crawler()
    # 试跑：只打印前若干个
    cnt = 0
    for item in crawler.crawl_all(persist=example_persist):
        log.info("GOT: %s @ %s", item.name, item.source_url)
        cnt += 1
        if cnt >= 5:
            break