# -*- coding: utf-8 -*-
"""
仅抓取“获取渠道”测试版（强化修复版）
- 优先“获取/获得方式”表格行
- 次选“分布地：XXX”（忽略 无/未知/暂无 等）
- 文本候选按“锚点 -> 句末/下一小节标题”裁剪，避免吞入性格/配招/种族值
- 过滤导航/推广段（如：红色印记/性格/资质视频/充值卡布币/视频攻略/太上令 等）
- 使用打分器挑选最像“获取渠道”的一句
- 扩充归类规则（补“首次打败/无双印记/战斗中出现”等）；改进“新/当期”判定
运行示例：
python server/app/services/crawler_server.py -n 100 -o out_acq_100.json
"""

import argparse
import json
import logging
import re
import sys
import time
from typing import List, Dict, Any, Optional, Tuple

import requests
from bs4 import BeautifulSoup, Tag

# -------- 基础设置 --------
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0 Safari/537.36"
    )
}

LIST_SEEDS = [
    # 4399 妖怪大全汇总页（会有分页/大量链接）
    "https://news.4399.com/kabuxiyou/yaoguaidaquan/",
]
TIMEOUT = 18
RETRY = 2
SLEEP_BETWEEN = (0.2, 0.6)  # 抓详情页间隔随机范围（秒），可按需调小/关闭

# 强触发词（优先在表格或段落中搜）
ACQ_KEYWORDS = [
    "获得方式", "获取方式", "获取方法", "获得方法", "获得渠道", "获取渠道", "获取途径",
    "获得：", "获取：", "分布地", "获得", "获取",
    # 常见“类似获取”的线索
    "捕捉", "捕获", "参与活动", "挑战", "BOSS", "副本", "通关", "兑换", "商店",
    "寻宝罗盘", "罗盘", "七星宝图", "北斗七星图", "神宠之魂", "VIP", "充值", "年费", "月费",
    "任务", "剧情", "点亮", "签到", "有几率", "抽取", "抽得", "抽奖", "幻境", "地府", "荣耀",
]

# 评分触发词（越像获取渠道分值越高）
POS_WORDS = [
    "获得", "获取", "可获得", "可得", "有几率", "概率", "挑战", "副本", "通关",
    "活动", "兑换", "商店", "罗盘", "寻宝罗盘", "七星宝图", "北斗七星图", "神宠之魂",
    "VIP", "年费", "充值", "任务", "剧情", "点亮", "签到", "捕捉", "捕获", "幻境", "地府",
    "仙踪之门",
]

# 归类映射（顺序有先后：越靠前越优先）
ACQ_CLASS_RULES = [
    # 活动/挑战/剧情
    (r"(参与|进行).{0,8}(活动|充值好礼|七日送好礼|嘉年华|节|合一|守|战|挑战活动|考验).*(获|可?获得)", "活动获取宠物"),
    (r"(BOSS|首领|地府|内殿|万妖洞|副本|组队|挑战|切磋|通关|荣耀|幻境|超能幻境).*(获|可?获得|首次(击|打)败)", "BOSS宠物"),
    # 罗盘 / 七星宝图 / 抽取 / 神宠之魂
    (r"(寻宝罗盘|罗盘|七星宝图|北斗七星图|神宠之魂|扭蛋|转盘).*(获|可?获得|抽(取|得))", "兑换/商店"),
    # 捕捉/场景定位
    (r"(捕捉|捕获|有几率?获得|在.*(海岸|山|国|区域|地点|洞|谷|林|湾)).*(获|可?获得)", "可捕捉宠物"),
    # 进化/超进化/升阶
    (r"(超进化|进化|觉醒|进阶|升阶).*(后)?获?得|由.*(进化|升阶|觉醒).*可?得", "超进化"),
    # 日常/任务
    (r"(任务|剧情|点亮|签到|每日|周常).*(获|可?获得)", "任务获取"),
    # 兑换/商店/礼盒
    (r"(兑换|商店|碎片|声望|兑换所|礼盒).*(获|可?获得)", "兑换/商店"),
    # VIP/年费/充值
    (r"(VIP|年费|月费|充值|成为.*超级VIP|当月VIP).*(获|可?得)", "其它"),
    # 无双印记/战中变身（单列到“其它”）
    (r"(无双印记|无双状态|印记).*(战斗中出现)", "其它"),
]

# 负面/无效获得文本（命中就丢弃）
NEGATIVE_TOKENS = ["无", "未知", "暂无", "未开放", "暂时未知", "敬请期待", "？", "?", ""]

# 黑名单段落（页面推广/导航常见文案）
BLOCK_PHRASES = [
    "妖怪获得小技巧请点击", "免费获得卡布币", "技能表分布地配招", "举报反馈", "来源：4399.com",
    "红色印记", "妖怪性格", "资质视频", "充值卡布币", "视频攻略", "太上令", "点击查看性格大全",
    "卡布西游红色印记", "卡布西游妖怪性格", "卡布西游充值卡布币", "卡布西游太上令",
]

# 日期/期次特征
DATE_RE = re.compile(r"\d{4}年\d{1,2}月\d{1,2}日?|(\d{4}年\d{1,2}月)|(\d{1,2}月\d{1,2}日)")
NEW_FLAG_RE = re.compile(r"(当期|本期|起|首次|新上线|新出|自\d{4}年|\d{4}年\d{1,2}月\d{0,2}日?起)")

# —— 锚点裁剪：从“获得/获取/分布地”开始，到句末/下一小节标题为止 —— #
ANCHOR_HEAD_RE = re.compile(r"(获得方式|获取方式|获得方法|获取方法|获得[:：]|获取[:：]|分布地[:：])")
TRIM_TAIL_RE = re.compile(r"(极品性格|点击查看性格大全|推荐修为|推荐配招|相关链接|种族值|妖怪名|系别|进化等级|作者|来源)")

# ------- 小工具 -------

def log_setup():
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

def sleep_a_bit():
    import random
    time.sleep(random.uniform(*SLEEP_BETWEEN))

def req_get(url: str) -> Optional[requests.Response]:
    last_exc = None
    for _ in range(RETRY):
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            enc = (r.apparent_encoding or "utf-8").lower()
            r.encoding = enc or "utf-8"
            if r.status_code == 200 and r.text:
                return r
        except Exception as e:
            last_exc = e
            time.sleep(0.5)
    if last_exc:
        logging.warning(f"GET失败 {url} -> {last_exc}")
    return None

def clean_text(x: str) -> str:
    if not x:
        return ""
    x = x.replace("\uFFFD", "").replace("\u200b", "").replace("\xa0", " ")
    x = re.sub(r"[ \t\r\f\v]+", " ", x)
    x = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]+", "", x)
    return x.strip()

def is_detail_link(href: str) -> bool:
    if not href:
        return False
    return href.endswith(".html") and "/kabuxiyou/yaoguaidaquan/" in href

def uniq_order(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out

def css_like_path(el: Tag) -> str:
    parts, cur = [], el
    while cur and isinstance(cur, Tag) and cur.name not in ("[document]", "html"):
        frag = cur.name
        if cur.get("id"):
            frag += f"#{cur.get('id')}"
        if cur.get("class"):
            frag += "." + ".".join(cur.get("class")[:2])
        parts.append(frag)
        cur = cur.parent
        if len(parts) > 6:
            break
    return " > ".join(reversed(parts))

def pick_main_container(soup: BeautifulSoup) -> Tag:
    """
    4399常见正文容器：尽量限定范围，减少抓到导航/推广区块的概率
    """
    for sel in ["#newstext", ".article", ".news_text", ".con", ".content", "article", ".text"]:
        node = soup.select_one(sel)
        if node:
            return node
    return soup.body or soup

# ------- 详情页解析 & 链接收集（注意：collect_detail_links 在此处，位于 main 之前） -------

def collect_detail_links(limit: int) -> List[str]:
    links: List[str] = []
    for seed in LIST_SEEDS:
        r = req_get(seed)
        if not r:
            continue
        soup = BeautifulSoup(r.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if is_detail_link(href):
                if not href.startswith("http"):
                    href = requests.compat.urljoin(r.url, href)
                links.append(href)
        if len(links) >= limit:
            break
    links = uniq_order(links)
    return links[:limit]

def extract_title(soup: BeautifulSoup) -> str:
    og = soup.select_one('meta[property="og:title"]')
    if og and og.get("content"):
        return clean_text(og["content"])
    if soup.title and soup.title.text:
        return clean_text(soup.title.text)
    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))
    return ""

def extract_breadcrumbs(soup: BeautifulSoup) -> List[str]:
    for sel in [".crumb", ".crumbs", ".sitepath", ".c_nav", ".header_crumb", ".head_crumb"]:
        node = soup.select_one(sel)
        if node:
            txts = [clean_text(x) for x in node.stripped_strings if clean_text(x)]
            txts = [t for t in txts if t not in [">", "/", "»", "›", "当前位置："]]
            return txts[:8]
    return []

def summarize_tables(scope: Tag) -> Tuple[bool, List[Dict[str, Any]]]:
    tbls_summary, has_stats = [], False
    for i, tb in enumerate(scope.find_all("table")[:8]):
        rows, has_obtain_row = [], False
        for tr in tb.find_all("tr")[:14]:
            cells = [clean_text(td.get_text(" ", strip=True)) for td in tr.find_all(["th", "td"])]
            if not cells:
                continue
            rows.append(cells)
            line = " ".join(cells)
            if any(kw in line for kw in ["获得方式", "获取方式", "获得方法", "获取方法"]):
                has_obtain_row = True
        if rows:
            if any(len(r) >= 5 for r in rows) and not has_stats:
                has_stats = True
            tbls_summary.append({"idx": i, "rows": rows[:14], "has_obtain_row": has_obtain_row})
    return has_stats, tbls_summary

# —— 裁剪器 —— #
def _trim_acq_phrase(t: str) -> str:
    t = clean_text(t)
    if not t:
        return t
    m = ANCHOR_HEAD_RE.search(t)
    if m:
        t = t[m.start():]
    t = re.split(r"[。！？!?\n]", t)[0]
    t = TRIM_TAIL_RE.split(t)[0]
    if len(t) > 100:
        m2 = re.search(r".{0,100}?(捕获|捕捉|获得|获取|抽(取|得)|兑换|挑战|通关|罗盘|七星|幻境|地府|VIP|年费)[^，,。！!？\n]*", t)
        if m2:
            t = t[:m2.end()]
    return t.strip(" ，,;；-—")

def _is_negative_value(text: str) -> bool:
    t = clean_text(text).strip("：: ")
    return t in NEGATIVE_TOKENS

def _bad_block(text: str) -> bool:
    return any(p in text for p in BLOCK_PHRASES)

def _score_candidate(text: str) -> int:
    t = clean_text(text)
    if not t:
        return -999
    if _bad_block(t):
        return -500
    if re.search(r"^分布地[:：]\s*(无|未知|暂无|未开放|暂时未知)\s*$", t):
        return -400
    right = t.split("：", 1)[-1].strip() if ("：" in t or ":" in t) else t
    if _is_negative_value(right):
        return -350
    if not (re.search(r"(获[得取]|获取|可获得|可得)", t) or re.search(r"^分布地[:：]", t)):
        return -300

    score = 0
    if re.search(r"(获得方?式|获取方?式|获得渠道|获取渠道|获取途径)", t):
        score += 20
    if t.startswith(("获得：", "获取：")):
        score += 15
    if t.startswith("分布地："):
        score += 8
    if DATE_RE.search(t):
        score += 50
    if ("起" in t) or ("至" in t):
        score += 8
    for w in POS_WORDS:
        if w in t:
            score += 12
    ln = len(t)
    if 6 <= ln <= 80:
        score += 10
    elif ln > 120:
        score -= 12
    return score

def _collect_candidates_from_tables(scope: Tag) -> List[Dict[str, Any]]:
    cands = []
    for tb in scope.find_all("table")[:10]:
        for tr in tb.find_all("tr"):
            line = clean_text(tr.get_text(" ", strip=True))
            if not line:
                continue
            # 这行看起来不像“获取/分布地”的，直接跳过
            if not any(k in line for k in ["获得", "获取", "分布地"]):
                continue

            tds = tr.find_all("td")

            # 1) 有 <td>：逐个单元格产出候选（修复只取最后一个<td>的问题）
            if tds:
                for td in tds:
                    cell = clean_text(td.get_text(" ", strip=True))
                    if not cell:
                        continue
                    # 只保留看起来像“获取/分布地”的单元格
                    if not any(k in cell for k in ["获得", "获取", "分布地"]):
                        continue
                    txt = _trim_acq_phrase(cell)
                    if not txt or _bad_block(txt):
                        continue
                    if any(k in cell for k in ["获得方式", "获取方式", "获得方法", "获取方法", "获得：", "获取："]):
                        label = "table_acq"
                    elif "分布地" in cell:
                        label = "table_loc"
                    else:
                        label = "table_misc"

                    cands.append({
                        "from": label,
                        "path": css_like_path(td),   # 记录到具体<td>，便于调试
                        "text": txt,
                        "score": _score_candidate(txt),
                        "discard": None,
                    })
            else:
                # 2) 没有 <td>：回落到整行文本
                txt = _trim_acq_phrase(line)
                if not txt or _bad_block(txt):
                    continue
                label = "table_acq" if any(k in line for k in ["获得方式", "获取方式", "获得方法", "获取方法", "获得：", "获取："]) \
                        else ("table_loc" if "分布地" in line else "table_misc")
                cands.append({
                    "from": label,
                    "path": css_like_path(tr),
                    "text": txt,
                    "score": _score_candidate(txt),
                    "discard": None,
                })
    return cands

def _collect_candidates_from_text(scope: Tag) -> List[Dict[str, Any]]:
    kw_re = re.compile("|".join(re.escape(k) for k in ACQ_KEYWORDS + ["分布地"]))
    cands: List[Dict[str, Any]] = []
    for el in scope.find_all(["p", "li", "div", "section", "span"])[:400]:
        raw = clean_text(el.get_text(" ", strip=True))
        if not raw or _bad_block(raw) or not kw_re.search(raw):
            continue
        for s in re.split(r"[。！？!?\n]", raw):
            s = clean_text(s)
            if not s or not kw_re.search(s):
                continue
            if not (re.search(r"(获[得取]|获取|可获得|可得)", s) or re.search(r"^分布地[:：]", s)):
                continue
            s2 = _trim_acq_phrase(s)
            if not s2 or _bad_block(s2):
                continue
            cands.append({
                "from": "text",
                "path": css_like_path(el),
                "text": s2,
                "score": _score_candidate(s2),
                "discard": None,
            })
        if len(cands) >= 40:
            break
    return cands

def pick_acquire_text(soup: BeautifulSoup) -> Tuple[str, Dict[str, Any]]:
    scope = pick_main_container(soup)
    candidates: List[Dict[str, Any]] = []
    candidates += _collect_candidates_from_tables(scope)
    candidates += _collect_candidates_from_text(scope)

    debug_list = []
    best_text, best_score = "", -999

    for c in candidates:
        t = c["text"]
        sc = c["score"]
        if re.search(r"^分布地[:：]\s*(无|未知|暂无|未开放|暂时未知)\s*$", t):
            c["discard"] = "empty_location"
        else:
            right = t.split("：", 1)[-1] if ("：" in t) else t
            if _is_negative_value(right):
                c["discard"] = "negative_singleton"
            elif _bad_block(t):
                c["discard"] = "blocked_phrase"
            else:
                c["discard"] = None

        debug_list.append({k: c[k] for k in ["from", "path", "text", "score", "discard"]})

        if c["discard"]:
            continue
        if sc > best_score:
            best_score, best_text = sc, t

    return best_text, {"from": "ranked", "candidates": debug_list, "best_score": best_score}

def classify_acq_type(acq_text: str) -> Tuple[Optional[str], Optional[bool]]:
    if not acq_text:
        return None, None
    for patt, label in ACQ_CLASS_RULES:
        if re.search(patt, acq_text):
            new_flag = True if NEW_FLAG_RE.search(acq_text) else None
            return label, new_flag
    if DATE_RE.search(acq_text):
        return "活动获取宠物", True if NEW_FLAG_RE.search(acq_text) else None
    return None, None

def extract_acq_only(url: str) -> Dict[str, Any]:
    r = req_get(url)
    if not r:
        return {
            "url": url, "name": "", "breadcrumbs": [],
            "acq_method": None, "acq_type": None, "acq_new_type": None,
            "debug": {"error": "fetch_failed"}
        }

    soup = BeautifulSoup(r.text, "lxml")

    name = extract_title(soup)
    if name:
        name2 = re.sub(r"[^0-9A-Za-z\u4e00-\u9fa5·—\-\s\|\:\（\）\(\)【】、，,。!！?？]", "", name)
        if 2 <= len(name2) <= len(name) + 4:
            name = name2

    breadcrumbs = extract_breadcrumbs(soup)
    scope = pick_main_container(soup)
    has_stats_table, tbls_summary = summarize_tables(scope)

    acq_text, acq_debug = pick_acquire_text(soup)
    acq_text = clean_text(acq_text)
    acq_type, new_flag = classify_acq_type(acq_text)

    heads = [clean_text(h.get_text(" ", strip=True)) for h in soup.select("h1,h2,h3,h4")][:20]
    tag_counts = {}
    for t in ["table", "p", "li", "section", "article", "div", "span"]:
        tag_counts[t] = len(soup.find_all(t))

    page_structure = {
        "headings": [h for h in heads if h],
        "has_stats_table": has_stats_table,
        "tables": tbls_summary,
        "acq_candidates": acq_debug.get("candidates", []),
        "acq_choice_score": acq_debug.get("best_score"),
        "tag_counts": tag_counts,
    }

    return {
        "url": url,
        "name": name,
        "breadcrumbs": breadcrumbs,
        "acq_method": acq_text or None,
        "acq_type": acq_type,
        "acq_new_type": new_flag,
        "debug": {
            "stats_table_found": has_stats_table,
            "page_structure": page_structure
        }
    }

# ------- 主流程 -------
def main():
    log_setup()
    ap = argparse.ArgumentParser()
    ap.add_argument("-n", "--limit", type=int, default=500, help="只抓前 N 条详情链接（默认100）")
    ap.add_argument("-o", "--out", type=str, default="", help="输出文件路径（JSON）")
    args = ap.parse_args()

    links = collect_detail_links(limit=max(args.limit, 1))
    logging.info(f"list[{LIST_SEEDS[0]}] -> {len(links)} detail links (use first {len(links)})")

    results: List[Dict[str, Any]] = []
    for i, url in enumerate(links, 1):
        item = extract_acq_only(url)
        results.append(item)
        logging.info(
            f"ACQ {item.get('name') or ''} | "
            f"type={item.get('acq_type')} new={item.get('acq_new_type')} | "
            f"method={item.get('acq_method') or ''}"
        )
        sleep_a_bit()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"\nSaved to {args.out}")
    else:
        json.dump(results, sys.stdout, ensure_ascii=False, indent=2)

if __name__ == "__main__":
    main()