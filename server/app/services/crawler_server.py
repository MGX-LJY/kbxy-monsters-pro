# server/app/services/crawler_server.py
# -*- coding: utf-8 -*-
"""
4399【卡布西游-妖怪大全】爬虫（合并版）
- 解析种族值 / 技能 / 推荐配招 / 系别：完全沿用“原版”（视为正确答案）
- 仅“获取渠道（type/new_type/method）”：替换为强化修复版（表格优先 + 正文兜底 + 打分挑一句 + 有序正则分类 + 新/当期判断）

运行示例（与原版一致，输出前 N 个最高形态的精简 JSON）：
    python server/app/services/crawler_server.py
"""

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
from bs4 import BeautifulSoup, Tag

log = logging.getLogger(__name__)

# ---------- 原版数据模型 ----------
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
    # 获取渠道（强化修复版生成）
    type: Optional[str] = None
    new_type: Optional[bool] = None
    method: Optional[str] = None
    # 其它（原版）
    series_names: List[str] = field(default_factory=list)
    skills: List[SkillRow] = field(default_factory=list)
    recommended_names: List[str] = field(default_factory=list)
    selected_skills: List[SkillRow] = field(default_factory=list)


# ---------- 原版工具 ----------
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
    return bool(href) and '/kabuxiyou/yaoguaidaquan/' in href and href.endswith('.html')


# ---------- 获取渠道（强化修复版：常量 & 正则 & 工具） ----------
# 触发与过滤
ACQ_KEYWORDS = [
    "获得方式","获取方式","获取方法","获得方法","获得渠道","获取渠道","获取途径",
    "获得：","获取：","分布地","获得","获取",
    "捕捉","捕获","参与活动","挑战","BOSS","副本","通关","兑换","商店",
    "寻宝罗盘","罗盘","七星宝图","北斗七星图","神宠之魂","VIP","充值","年费","月费",
    "任务","剧情","点亮","签到","有几率","抽取","抽得","抽奖","幻境","地府","荣耀",
]
POS_WORDS = [
    "获得","获取","可获得","可得","有几率","概率","挑战","副本","通关",
    "活动","兑换","商店","罗盘","寻宝罗盘","七星宝图","北斗七星图","神宠之魂",
    "VIP","年费","充值","任务","剧情","点亮","签到","捕捉","捕获","幻境","地府","仙踪之门",
]
NEGATIVE_TOKENS = ["无","未知","暂无","未开放","暂时未知","敬请期待","？","?",""]
BLOCK_PHRASES = [
    "妖怪获得小技巧请点击","免费获得卡布币","技能表分布地配招","举报反馈","来源：4399.com",
    "红色印记","妖怪性格","资质视频","充值卡布币","视频攻略","太上令","点击查看性格大全",
    "卡布西游红色印记","卡布西游妖怪性格","卡布西游充值卡布币","卡布西游太上令",
]

# 日期/期次特征
DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日?|(\d{4}年\d{1,2}月)|(\d{1,2}月\d{1,2}日)")
DATE_HINT = re.compile(r"\d{4}年\d{1,2}月(?:\d{1,2}日)?|(?:\d{1,2}月\d{1,2}日)")

# 锚点裁剪
ANCHOR_HEAD_RE = re.compile(r"(获得方式|获取方式|获得方法|获取方法|获得[:：]|获取[:：]|分布地[:：])")
TRIM_TAIL_RE = re.compile(r"(极品性格|点击查看性格大全|推荐修为|推荐配招|相关链接|种族值|妖怪名|系别|进化等级|作者|来源)")

def _acq_clean(x: str) -> str:
    if not x: return ""
    x = x.replace("\uFFFD","").replace("\u200b","").replace("\xa0"," ")
    x = re.sub(r"[ \t\r\f\v]+"," ",x)
    x = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+","",x)
    return x.strip()

def _is_negative_value(text: str) -> bool:
    t = _acq_clean(text).strip("：: ")
    return t in NEGATIVE_TOKENS

def _bad_block(text: str) -> bool:
    return any(p in text for p in BLOCK_PHRASES)

def css_like_path(el: Tag) -> str:
    parts, cur = [], el
    while cur and isinstance(cur, Tag) and cur.name not in ("[document]","html"):
        frag = cur.name
        if cur.get("id"): frag += f"#{cur.get('id')}"
        if cur.get("class"): frag += "." + ".".join(cur.get("class")[:2])
        parts.append(frag); cur = cur.parent
        if len(parts) > 6: break
    return " > ".join(reversed(parts))

def pick_main_container(soup: BeautifulSoup) -> Tag:
    for sel in ["#newstext",".article",".news_text",".con",".content","article",".text"]:
        node = soup.select_one(sel)
        if node: return node
    return soup.body or soup

def _trim_acq_phrase(t: str) -> str:
    t = _acq_clean(t)
    if not t: return t
    m = ANCHOR_HEAD_RE.search(t)
    if m: t = t[m.start():]
    t = re.split(r"[。！？!?\n]", t)[0]
    t = TRIM_TAIL_RE.split(t)[0]
    if len(t) > 100:
        m2 = re.search(r".{0,100}?(捕获|捕捉|获得|获取|抽(取|得)|兑换|挑战|通关|罗盘|七星|幻境|地府|VIP|年费)[^，,。！!？\n]*", t)
        if m2: t = t[:m2.end()]
    return t.strip(" ，,;；-—")

def _score_candidate(text: str) -> int:
    t = _acq_clean(text)
    if not t: return -999
    if _bad_block(t): return -500
    if re.search(r"^分布地[:：]\s*(无|未知|暂无|未开放|暂时未知)\s*$", t): return -400
    right = t.split("：", 1)[-1].strip() if ("：" in t or ":" in t) else t
    if _is_negative_value(right): return -350
    if not (re.search(r"(获[得取]|获取|可获得|可得)", t) or re.search(r"^分布地[:：]", t)): return -300
    score = 0
    if re.search(r"(获得方?式|获取方?式|获得渠道|获取渠道|获取途径)", t): score += 20
    if t.startswith(("获得：","获取：")): score += 15
    if t.startswith("分布地："): score += 8
    if DATE_RE.search(t): score += 50
    if ("起" in t) or ("至" in t): score += 8
    for w in POS_WORDS:
        if w in t: score += 12
    ln = len(t)
    if 6 <= ln <= 80: score += 10
    elif ln > 120: score -= 12
    return score

def _collect_candidates_from_tables(scope: Tag) -> List[Dict[str, object]]:
    cands = []
    for tb in scope.find_all("table")[:10]:
        for tr in tb.find_all("tr"):
            line = _acq_clean(tr.get_text(" ", strip=True))
            if not line: continue
            if not any(k in line for k in ["获得","获取","分布地"]): continue
            tds = tr.find_all("td")
            if tds:
                for td in tds:
                    cell = _acq_clean(td.get_text(" ", strip=True))
                    if not cell: continue
                    if not any(k in cell for k in ["获得","获取","分布地"]): continue
                    txt = _trim_acq_phrase(cell)
                    if not txt or _bad_block(txt): continue
                    if any(k in cell for k in ["获得方式","获取方式","获得方法","获取方法","获得：","获取："]):
                        label = "table_acq"
                    elif "分布地" in cell:
                        label = "table_loc"
                    else:
                        label = "table_misc"
                    cands.append({"from":label,"path":css_like_path(td),"text":txt,"score":_score_candidate(txt),"discard":None})
            else:
                txt = _trim_acq_phrase(line)
                if not txt or _bad_block(txt): continue
                label = "table_acq" if any(k in line for k in ["获得方式","获取方式","获得方法","获取方法","获得：","获取："]) \
                        else ("table_loc" if "分布地" in line else "table_misc")
                cands.append({"from":label,"path":css_like_path(tr),"text":txt,"score":_score_candidate(txt),"discard":None})
    return cands

def _collect_candidates_from_text(scope: Tag) -> List[Dict[str, object]]:
    kw_re = re.compile("|".join(re.escape(k) for k in ACQ_KEYWORDS + ["分布地"]))
    cands: List[Dict[str, object]] = []
    for el in scope.find_all(["p","li","div","section","span"])[:400]:
        raw = _acq_clean(el.get_text(" ", strip=True))
        if not raw or _bad_block(raw) or not kw_re.search(raw): continue
        for s in re.split(r"[。！？!?\n]", raw):
            s = _acq_clean(s)
            if not s or not kw_re.search(s): continue
            if not (re.search(r"(获[得取]|获取|可获得|可得)", s) or re.search(r"^分布地[:：]", s)): continue
            s2 = _trim_acq_phrase(s)
            if not s2 or _bad_block(s2): continue
            cands.append({"from":"text","path":css_like_path(el),"text":s2,"score":_score_candidate(s2),"discard":None})
        if len(cands) >= 40: break
    return cands

def pick_acquire_text(soup: BeautifulSoup) -> str:
    scope = pick_main_container(soup)
    candidates: List[Dict[str, object]] = []
    candidates += _collect_candidates_from_tables(scope)
    candidates += _collect_candidates_from_text(scope)
    best_text, best_score = "", -999
    for c in candidates:
        t, sc = str(c["text"]), int(c["score"])
        if re.search(r"^分布地[:：]\s*(无|未知|暂无|未开放|暂时未知)\s*$", t):
            continue
        right = t.split("：",1)[-1] if ("：" in t) else t
        if _is_negative_value(right) or _bad_block(t):
            continue
        if sc > best_score:
            best_score, best_text = sc, t
    return best_text

# —— 分类器（有序正则 + 新/当期判断）——
def _norm(s: str) -> str:
    if not s: return ""
    res = []
    for ch in s:
        o = ord(ch)
        if o == 0x3000: ch = " "
        elif 0xFF01 <= o <= 0xFF5E: ch = chr(o - 0xFEE0)
        res.append(ch)
    s = "".join(res)
    s = s.replace("：",":").replace("，",",").replace("、",",").replace("；",";")
    s = re.sub(r"\s+"," ",s).strip()
    return s

_UNAVAILABLE = re.compile(r"(绝版|已绝版|停止(获取|产出)|已结束|下架|不可获取|无法获得|已停售)")
_AVAILABLE_HINT = re.compile(r"(可捕捉|野外|常驻|长期|周常|日常|兑换(长期)?开放|商店(长期)?开放|随时可|任意时段)")

PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"(?:由[^,，。;；\n]{1,16}(?:进化|升阶|觉醒|融合)[^,，。;；\n]{0,10}?可?得)|"
                r"(?:进化|升阶|觉醒|融合)[^,，。;；\n]{0,12}?后?可?获?得|"
                r"(?:无双印记|无双状态)[^,，。;；\n]{0,12}?(?:战斗中出现|开启无双状态)", re.I),
     "超进化"),
    (re.compile(r"(首次[击打]败|战胜|挑战|通关)[^,，。;；\n]{0,20}?"
                r"(BOSS|首领|家族大厅|之门|内殿|地府|万妖洞|幻境|超能幻境|守护者|元帅|天尊|洞主|宫)", re.I),
     "BOSS宠物"),
    (re.compile(r"(商城|市集|VIP市集|炫光商城|拍卖|兑换所|兑换|礼盒|礼包|宝箱|扭蛋|转盘|抽奖|"
                r"寻宝罗盘|七星宝图|北斗七星图|神宠之魂|宝藏|金元宝|购买|精魄(?:孵化|化形)?|抽取|抽到|抽得)", re.I),
     "兑换/商店"),
    (re.compile(r"(参加|完成|参与|开启|进行)[^》】』\n]{0,18}"
                r"(?:《[^》]{1,24}》|【[^】]{1,24}】|『[^』]{1,24}』)?[^,，。;；\n]{0,10}"
                r"(活动|嘉年华|节|庆|乐园|行动|盛宴|周年|福利)[^,，。;；\n]{0,20}"
                r"(获得|可获得|有几率(?:抽?到|获得)|有机会获得)", re.I),
     "活动获取宠物"),
    (re.compile(r"(完成|通关)[^,，。;；\n]{0,18}(任务|剧情|主线|支线|召集令|点亮|签到|收集)[^,，。;；\n]{0,12}(可获?得|获得)", re.I),
     "任务获取"),
    (re.compile(r"(?:分布地\s*:\s*(?!无|未知|暂无|未开放|暂时未知)"
                r"(?!.*(商城|市集|罗盘|宝图|神宠之魂|VIP|礼盒|礼包)))|"
                r"((可?在|于|在)[^,，。;；\n]{2,16}(海岸|山|谷|洞|窟|林|湾|岛|宫|城|洞穴|大殿|寺|境|殿)[^,，。;；\n]{0,10}"
                r"(捕捉|捕获|出现|刷新|遇到|获得))", re.I),
     "可捕捉宠物"),
    (re.compile(r"(充值|开通|成为|达到)[^,，。;；\n]{0,24}?(VIP|年费|月费|超级VIP|魔界守护者)"
                r"[^,，。;；\n]{0,16}(领取|获得|可得|可获得)", re.I),
     "其它"),
]

def classify_acq_type(acq_text: str) -> Tuple[Optional[str], Optional[bool]]:
    if not acq_text:
        return None, None
    tnorm = _norm(acq_text)
    new_flag: Optional[bool] = None
    if _UNAVAILABLE.search(tnorm): new_flag = False
    elif "起" in tnorm and DATE_HINT.search(tnorm) and "至" not in tnorm and "到" not in tnorm and "—" not in tnorm:
        new_flag = True
    elif _AVAILABLE_HINT.search(tnorm): new_flag = True
    for patt, label in PATTERNS:
        if patt.search(tnorm):
            return label, new_flag
    if DATE_HINT.search(tnorm):
        return "活动获取宠物", new_flag
    return None, new_flag


# ---------- 爬虫主体（原版 + 新获取渠道） ----------
class Kabu4399Crawler:
    BASE = "https://news.4399.com"
    ROOT = "/kabuxiyou/yaoguaidaquan/"
    CANDIDATE_SLUGS = [
        "huoxi","jinxi","muxi","shuixi","tuxi","yixi","guaixi",
        "moxi","yaoxi","fengxi","duxi","leixi","huanxi",
        "bing","lingxi","jixie","huofengxi","mulingxi",
        "shengxi","tuhuanxi","shuiyaoxi","yinxi",
    ]
    SLUG2ELEM: Dict[str, str] = {
        "huoxi": "火系", "jinxi": "金系", "muxi": "木系", "shuixi": "水系", "tuxi": "土系",
        "yixi": "翼系", "guaixi": "怪系", "moxi": "魔系", "yaoxi": "妖系", "fengxi": "风系",
        "duxi": "毒系", "leixi": "雷系", "huanxi": "幻系", "bing": "冰系", "lingxi": "灵系",
        "jixie": "机械",
        "huofengxi": "火风系", "mulingxi": "木灵系", "tuhuanxi": "土幻系",
        "shuiyaoxi": "水妖系", "yinxi": "音系", "shengxi": "圣系",
    }
    ELEM_TOKENS: Dict[str, str] = {
        "风": "风系", "火": "火系", "水": "水系", "土": "土系", "金": "金系",
        "冰": "冰系", "毒": "毒系", "雷": "雷系", "幻": "幻系", "妖": "妖系",
        "翼": "翼系", "怪": "怪系", "灵": "灵系", "音": "音系", "圣": "圣系",
        "机": "机械", "械": "机械",
    }
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

    # ---- 基础 GET（带重试 + 节流）----
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

    # ---- 系别识别（原版）----
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

    # ---- 详情页解析（原版）----
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
            desc = vals[6]
            skills.append(SkillRow(name, level, element, kind, power, desc))
        return skills

    # ---- 获取渠道解析（替换为强化修复版）----
    def _parse_acquisition_info(self) -> Tuple[Optional[str], Optional[bool], Optional[str]]:
        """
        返回 (type, new_type, method)
        - method：从表格/正文候选中打分挑一句（强化修复版）
        - type/new_type：有序正则分类 + 新/当期判断（强化修复版）
        """
        # 用页面 HTML 走 BeautifulSoup 的候选/打分逻辑
        html = self.sp.html or ""
        if not html:
            return None, None, None
        soup = BeautifulSoup(html, "lxml")
        acq_text = pick_acquire_text(soup)
        acq_text = _acq_clean(acq_text)
        acq_type, new_flag = classify_acq_type(acq_text)
        return acq_type, new_flag, (acq_text or None)

    # ---- 推荐配招（原版）----
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
        def norm(s: str) -> str:
            return re.sub(r"\s+", "", s or "")
        skill_map = {norm(s.name): s for s in skills}
        out: List[SkillRow] = []
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
                out.append(s)
            else:
                out.append(SkillRow(name=rec, level=None, element="", kind="", power=None, description=""))
        return out

    @staticmethod
    def _six_sum(m: MonsterRow) -> int:
        return int(m.hp + m.speed + m.attack + m.defense + m.magic + m.resist)

    def _filter_weak(self, s: SkillRow, power_threshold: int = 110) -> bool:
        if (s.kind or "").strip() == "特殊":
            return True
        p = s.power or 0
        if p >= power_threshold:
            return True
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

    # ---------- 输出裁剪（与原版一致） ----------
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
        if not self._get(url):
            return None

        # 原版：种族值/技能/推荐/系别
        monsters = self._parse_stats_table(url)
        if not monsters:
            return None

        skills = self._parse_skills_table()
        rec_names = self._parse_recommended_names()
        selected: List[SkillRow] = self._select_skills_from_recommend(rec_names, skills) if rec_names else []
        if not selected:
            selected = self._all_skills_as_selected(skills, apply_filter=True)

        best = max(monsters, key=self._six_sum)
        elem = self._infer_element(url, skills)
        best.element = elem

        # 新版：获取渠道
        acq_type, acq_now, acq_method = self._parse_acquisition_info()
        best.type = acq_type
        best.new_type = acq_now
        best.method = acq_method

        best.skills = skills
        best.recommended_names = rec_names
        best.selected_skills = selected
        return best

    # ---- 顶层遍历（与原版一致）----
    def crawl_all(self, *, persist: Optional[callable] = None) -> Generator[MonsterRow, None, None]:
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


# ---------- 示例持久化（原版） ----------
def example_persist(mon: MonsterRow) -> None:
    log.info(
        "PERSIST %s [%s] hp=%s atk=%s spd=%s rec=%d sel=%d skills=%d type=%s new=%s",
        mon.name, mon.element or "-", mon.hp, mon.attack, mon.speed,
        len(mon.recommended_names), len(mon.selected_skills), len(mon.skills),
        mon.type or "-", str(mon.new_type)
    )

# ---------- 独立运行（与原版一致） ----------
def _to_public_json(m: MonsterRow) -> Dict[str, object]:
    return Kabu4399Crawler._to_public_json(m)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    crawler = Kabu4399Crawler()

    # 收集前 N 个角色（最高形态）并输出 JSON
    N = 10
    out: List[Dict[str, object]] = []
    for item in crawler.crawl_all(persist=example_persist):
        out.append(_to_public_json(item))
        if len(out) >= N:
            break

    print(json.dumps(out, ensure_ascii=False, indent=2))