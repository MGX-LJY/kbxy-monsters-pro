# server/app/services/crawler_server.py
from __future__ import annotations

import re
import time
import random
import json
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Generator, Iterable, Optional, Tuple, Set
from urllib.parse import urljoin, urlparse

from DrissionPage import SessionPage

log = logging.getLogger(__name__)

# ---------- 抓取结果数据模型 ----------
@dataclass
class SkillRow:
    name: str
    level: Optional[int]
    element: str
    kind: str         # 物理 / 法术 / 特殊
    power: Optional[int]
    description: str

@dataclass
class MonsterRow:
    name: str
    element: Optional[str]  # 妖怪系别（风系/火系/.../复合系/机械）
    hp: int
    speed: int
    attack: int
    defense: int
    magic: int
    resist: int
    source_url: str
    img_url: Optional[str] = None
    # 获取渠道（新增）
    type: Optional[str] = None          # 如：可捕捉宠物 / BOSS宠物 / 活动获取宠物 / 兑换 / 商店 / 任务 / 合成...
    new_type: Optional[bool] = None     # 当前是否可获取（启发式）
    method: Optional[str] = None        # 获取细节原文
    # 其它
    series_names: List[str] = field(default_factory=list)   # 同页多形态名字
    skills: List[SkillRow] = field(default_factory=list)    # 全量技能
    recommended_names: List[str] = field(default_factory=list)      # “推荐配招”解析出的技能名
    selected_skills: List[SkillRow] = field(default_factory=list)   # 推荐命中或回退（完整字段）


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
        1) “资料/种族值”表 => 可能多行（同页多形态），最终仅保留“最高形态”
        2) “技能表” => 解析为 SkillRow 列表
    - 额外：解析“推荐配招”（精选技能），并识别“妖怪系别 element”
    - 新增：解析“获取渠道”（type/new_type/method）
    - ⚠️ 已移除任何数据库缓存/ORM 定义，不会创建本地表。
    """
    BASE = "https://news.4399.com"
    ROOT = "/kabuxiyou/yaoguaidaquan/"
    CANDIDATE_SLUGS = [
        "huoxi","jinxi","muxi","shuixi","tuxi","yixi","guaixi",
        "moxi","yaoxi","fengxi","duxi","leixi","huanxi",
        "bing","lingxi","jixie","huofengxi","mulingxi",
        "shengxi","tuhuanxi","shuiyaoxi","yinxi",
    ]

    # URL 目录到“系别中文”的映射（常见+复合）
    SLUG2ELEM: Dict[str, str] = {
        "huoxi": "火系", "jinxi": "金系", "muxi": "木系", "shuixi": "水系", "tuxi": "土系",
        "yixi": "翼系", "guaixi": "怪系", "moxi": "魔系", "yaoxi": "妖系", "fengxi": "风系",
        "duxi": "毒系", "leixi": "雷系", "huanxi": "幻系", "bing": "冰系", "lingxi": "灵系",
        "jixie": "机械",
        "huofengxi": "火风系", "mulingxi": "木灵系", "tuhuanxi": "土幻系",
        "shuiyaoxi": "水妖系", "yinxi": "音系", "shengxi": "圣系",
    }

    # 技能表里的“技能属性”常见取值（用于投票推断）
    ELEM_TOKENS: Dict[str, str] = {
        "风": "风系", "火": "火系", "水": "水系", "土": "土系", "金": "金系",
        "冰": "冰系", "毒": "毒系", "雷": "雷系", "幻": "幻系", "妖": "妖系",
        "翼": "翼系", "怪": "怪系", "灵": "灵系", "音": "音系", "圣": "圣系",
        # 技能里一般不会写“机械”，但留作兜底
        "机": "机械", "械": "机械",
    }

    # —— 筛弱技能关键词（无推荐时使用） —— #
    SPECIAL_KEYWORDS = re.compile(
        r"(提高|降低|回复|恢复|免疫|护盾|屏障|减伤|回合|命中|几率|概率|状态|"
        r"先手|多段|PP|耗PP|反击|反伤|穿透|无视防御|标记|易伤|封印|禁技|"
        r"追加回合|再行动|行动条|推进|偷取|驱散|净化|吸血)"
    )

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

    # ---- 基础 GET（带重试 + 随机节流）----
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

    # ---- 系别识别 ----
    def _infer_element_from_url(self, page_url: str) -> Optional[str]:
        try:
            path = urlparse(page_url).path.strip("/")
            parts = path.split("/")
            if len(parts) >= 3 and parts[1] == "yaoguaidaquan":
                slug = parts[2]
                return self.SLUG2ELEM.get(slug)
        except Exception:
            pass
        return None

    def _infer_element_from_breadcrumb(self) -> Optional[str]:
        for a in self.sp.eles('t:div@@class=dq t:a'):
            txt = (_clean(a.text) or "").strip()
            if not txt:
                continue
            if txt.endswith("系") or txt == "机械":
                return txt
        return None

    def _infer_element_from_skills(self, skills: List[SkillRow]) -> Optional[str]:
        counter: Dict[str, int] = {}
        for s in skills or []:
            raw = (_clean(s.element) or "")
            if not raw or raw in {"无", "特殊"}:
                continue
            for ch in raw:
                if ch in self.ELEM_TOKENS:
                    elem = self.ELEM_TOKENS[ch]
                    counter[elem] = counter.get(elem, 0) + 1
                    break
        if not counter:
            return None
        return max(counter.items(), key=lambda kv: kv[1])[0]

    def _infer_element(self, page_url: str, skills: List[SkillRow]) -> Optional[str]:
        return (
            self._infer_element_from_url(page_url)
            or self._infer_element_from_breadcrumb()
            or self._infer_element_from_skills(skills)
        )

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
                element=None,
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
            # vals[5] 是 PP，已弃用
            desc = vals[6]
            skills.append(SkillRow(name, level, element, kind, power, desc))
        return skills

    # ---- 获取渠道解析（启发式）----
    def _parse_acquisition_info(self) -> Tuple[Optional[str], Optional[bool], Optional[str]]:
        """
        返回 (type, new_type, method)
        - type：归类（可捕捉宠物 / BOSS宠物 / 活动获取宠物 / 兑换 / 商店 / 任务 / 合成 / 其它）
        - new_type：当前是否可获取（True/False/None 不确定）
        - method：页面原文（“获得方式/分布地/捕捉地点/活动”行或段落）
        """
        # 先拼出整页可读文本
        page_texts: List[str] = []
        for ele in self.sp.eles('t:table, t:p, t:div, t:li'):
            txt = _clean(ele.text)
            if txt:
                page_texts.append(txt)
        page_txt = "  ".join(page_texts)

        # 在表格里优先找“获得/获取/分布地/捕捉”行
        method = None
        for tbl in self.sp.eles('t:table'):
            for tr in tbl.eles('t:tr'):
                cells = [_clean(td.text) for td in tr.eles('t:td')]
                if not cells:
                    continue
                row_txt = " ".join(cells)
                if re.search(r"(获得|获取|获得方式|获得途径|分布地|捕捉|抓捕|如何获得)", row_txt):
                    # 取该行除标题的剩余文本
                    if len(cells) >= 2:
                        method = " ".join(cells[1:])
                    else:
                        method = row_txt
                    break
            if method:
                break
        # 若表格没找到，就退化到整页关键句
        if not method:
            m = re.search(r"(获得方式[:：].{0,80}|分布地[:：].{0,80}|捕捉.{0,80}|活动.{0,80})", page_txt)
            if m:
                method = _clean(m.group())

        method = method or None

        # 分类规则（粗粒度）
        t = None
        if method:
            if re.search(r"(寻宝罗盘|野外|地图|出现|刷新|遇|捕)", method):
                t = "可捕捉宠物"
            elif re.search(r"(BOSS|副本|挑战|试炼|首领|战斗掉落)", method, re.I):
                t = "BOSS宠物"
            elif re.search(r"(活动|节日|限时|联动|抽取|扭蛋)", method):
                t = "活动获取宠物"
            elif re.search(r"(兑换|商店|购买|礼盒|礼包|拍卖)", method):
                t = "兑换/商店"
            elif re.search(r"(任务|剧情|主线|支线)", method):
                t = "任务获取"
            elif re.search(r"(合成|融合|进化|无双)", method):
                t = "超进化"
            else:
                t = "其它"

        # 是否当前可获得：明显“绝版/下架/已结束/未开放”等为 False；常驻/可捕捉类趋向 True；其余 None
        new_flag: Optional[bool] = None
        text_for_judge = (method or "") + "  " + page_txt
        if re.search(r"(绝版|已绝版|停止(获取|产出)|下架|已结束|未开放|不可获取|无法获得)", text_for_judge):
            new_flag = False
        elif re.search(r"(可捕捉|野外|常驻|长期|周常|日常|兑换(长期)?开放|商店(长期)?开放|随时可|任意时段)", text_for_judge):
            new_flag = True
        elif t in {"可捕捉宠物", "兑换/商店", "任务获取"}:
            new_flag = True
        elif t == "活动获取宠物" and re.search(r"(进行中|长期活动|常驻活动)", text_for_judge):
            new_flag = True

        return t, new_flag, method

    # ---- 推荐配招：解析 + 精选 ----
    def _parse_recommended_names(self) -> List[str]:
        for tbl in self.sp.eles('t:table'):
            for tr in tbl.eles('t:tr'):
                tds = tr.eles('t:td')
                if not tds:
                    continue
                first = _clean(tds[0].text)
                if "推荐配招" in first or "推荐技能" in first:
                    raw = _clean(" ".join((td.text or "") for td in tds[1:])) if len(tds) > 1 else _clean(tr.text)
                    raw = raw.replace("：", " ").replace("&nbsp;", " ").replace("\u3000", " ")
                    parts = re.split(r"[+＋、/，,；;|\s]+", raw)
                    names, seen = [], set()
                    for p in parts:
                        n = _clean(p)
                        if (not n) or (n == "无") or ("推荐" in n) or ("配招" in n):
                            continue
                        if n not in seen:
                            seen.add(n); names.append(n)
                    return names
        return []

    def _select_skills_from_recommend(self, rec_names: List[str], skills: List[SkillRow]) -> List[SkillRow]:
        """
        按推荐名在已解析技能中匹配，返回完整 SkillRow；没命中时保留一个只有 name 的占位 SkillRow。
        """
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "")

        skill_map = {norm(s.name): s for s in skills}
        out: List[SkillRow] = []
        for rec in rec_names:
            key = norm(rec)
            s = skill_map.get(key)
            if not s:
                # 宽松包含
                for cand in skills:
                    n = norm(cand.name)
                    if key and (key in n or n in key):
                        s = cand
                        break
            if s:
                out.append(s)
            else:
                # 未匹配到时，也保留一个占位，方便后续人工核对
                out.append(SkillRow(name=rec, level=None, element="", kind="", power=None, description=""))
        return out

    @staticmethod
    def _six_sum(m: MonsterRow) -> int:
        return int(m.hp + m.speed + m.attack + m.defense + m.magic + m.resist)

    def _filter_weak(self, s: SkillRow, power_threshold: int = 70) -> bool:
        """
        无推荐时的“弱技能过滤”：
        - 若 kind ∈ {物理, 法术} 且 power < 阈值 且 文案不含任何特殊关键词 => 过滤
        - kind == 特殊 一律保留
        """
        if (s.kind or "").strip() == "特殊":
            return True
        p = s.power or 0
        if p >= power_threshold:
            return True
        # 威力低，看描述是否有特殊效果
        if s.description and self.SPECIAL_KEYWORDS.search(s.description):
            return True
        return False

    def _all_skills_as_selected(self, skills: List[SkillRow], apply_filter: bool = True) -> List[SkillRow]:
        out: List[SkillRow] = []
        for s in skills or []:
            n = (s.name or "").strip()
            if not n or n == "无":
                continue
            if (not apply_filter) or self._filter_weak(s):
                out.append(s)
        return out

    # ---------- 输出裁剪（对下游导入/调试友好） ----------
    @staticmethod
    def _skill_public(s: SkillRow) -> Dict[str, object]:
        return {
            "name": s.name,
            "level": s.level,
            "element": s.element,
            "kind": s.kind,
            "power": s.power,
            "description": s.description,
        }

    @staticmethod
    def _to_public_json(m: MonsterRow) -> Dict[str, object]:
        """
        仅保留：
          - 最高形态：name, element, hp, speed, attack, defense, magic, resist
          - 获取渠道：type, new_type, method
          - selected_skills: 完整字段（便于后续按 (name, element, kind, power) 做唯一）
        """
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
            "selected_skills": [Kabu4399Crawler._skill_public(s) for s in (m.selected_skills or [])],
        }

    # ---- 页面抓取（不触库）----
    def fetch_detail(self, url: str) -> Optional[MonsterRow]:
        """
        仅抓取解析，不访问数据库；返回“最高形态” MonsterRow：
        - 以六维和的最大值为最高形态
        - 解析推荐配招，精选技能包含完整字段；推荐缺失时回退“全部技能精简+弱技过滤”
        - 识别妖怪“系别 element”
        - 解析“获取渠道”三件套（type/new_type/method）
        """
        if not self._get(url):
            return None

        monsters = self._parse_stats_table(url)
        if not monsters:
            return None

        skills = self._parse_skills_table()
        rec_names = self._parse_recommended_names()
        selected: List[SkillRow] = self._select_skills_from_recommend(rec_names, skills) if rec_names else []

        # 若无推荐或推荐匹配为空：回退为“全部技能精简 + 弱技过滤”
        if not selected:
            selected = self._all_skills_as_selected(skills, apply_filter=True)

        # 仅保留最高形态
        best = max(monsters, key=self._six_sum)

        # 系别识别（URL -> 面包屑 -> 技能表）
        elem = self._infer_element(url, skills)
        best.element = elem

        # 获取渠道
        acq_type, acq_now, acq_method = self._parse_acquisition_info()
        best.type = acq_type
        best.new_type = acq_now
        best.method = acq_method

        best.skills = skills
        best.recommended_names = rec_names
        best.selected_skills = selected
        return best

    # ---- 顶层 API：遍历列表，仅网络抓取 ----
    def crawl_all(
        self,
        *,
        persist: Optional[callable] = None,
    ) -> Generator[MonsterRow, None, None]:
        """
        遍历所有详情页：
        - 不再使用任何数据库缓存
        - 若提供 persist 回调，则在每次抓取完成后调用 persist(mon)（例如把数据写你的业务库）
        """
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
        "PERSIST %s [%s] hp=%s atk=%s spd=%s rec=%d sel=%d skills=%d type=%s new=%s",
        mon.name, mon.element or "-", mon.hp, mon.attack, mon.speed,
        len(mon.recommended_names), len(mon.selected_skills), len(mon.skills),
        mon.type or "-", str(mon.new_type)
    )


# ---------- 独立运行：输出前 N 个角色的 JSON（不触库） ----------
def _to_public_json(m: MonsterRow) -> Dict[str, object]:
    return Kabu4399Crawler._to_public_json(m)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = Kabu4399Crawler()

    # 收集前 10 个角色（最高形态）并输出 JSON
    N = 10
    out: List[Dict[str, object]] = []
    for item in crawler.crawl_all(persist=example_persist):
        out.append(_to_public_json(item))
        if len(out) >= N:
            break

    print(json.dumps(out, ensure_ascii=False, indent=2))