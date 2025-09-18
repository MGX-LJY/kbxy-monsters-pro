# server/app/services/tags_service.py
from __future__ import annotations

import json
import os
import re
import time
import uuid
import threading
from dataclasses import dataclass, field
from functools import lru_cache
from datetime import datetime, timezone
from typing import List, Set, Dict, Tuple, Any, Optional, Callable
from pathlib import Path

try:
    import httpx  # 仅 AI 接口需要；未安装也不影响正则路径
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

from sqlalchemy import select
    # noqa: E402
from sqlalchemy.orm import selectinload

from ..models import Monster

# ======================
# 目录加载 / 热更新
# ======================

# 以本文件为基准，稳健找到 config/tags_catalog.json
_DEFAULT_CATALOG_PATH = str((Path(__file__).resolve().parent / "config" / "tags_catalog.json"))
TAGS_CATALOG_PATH: str = os.getenv("TAGS_CATALOG_PATH", "").strip() or _DEFAULT_CATALOG_PATH
TAGS_CATALOG_TTL: float = float(os.getenv("TAGS_CATALOG_TTL", "5"))  # 秒

# 写库策略（仅用于选择最终标签来源）
TAG_WRITE_STRATEGY: str = os.getenv("TAG_WRITE_STRATEGY", "ai").strip().lower()  # ai | regex | repair_union
TAG_AI_REPAIR_VERIFY: bool = os.getenv("TAG_AI_REPAIR_VERIFY", "1") not in {"0", "false", "False"}

# DeepSeek
DEEPSEEK_API_URL = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "sk-7a1c5bc1d84240dcbb754ca169dbf741").strip()

# 运行期缓存
class _CatalogCache:
    data: Dict[str, Any] = {}
    mtime: float = 0.0
    loaded_at: float = 0.0
    code2cn: Dict[str, str] = {}
    code2en: Dict[str, str] = {}
    categories: Dict[str, List[str]] = {"buff": [], "debuff": [], "special": []}
    all_codes: Set[str] = set()
    patterns_by_code: Dict[str, List[str]] = {}
    compiled_by_code: Dict[str, List[re.Pattern]] = {}
    keywords_by_code: Dict[str, List[str]] = {}
    macros: Dict[str, str] = {}

    lock = threading.RLock()

_CACHE = _CatalogCache()

# ============
# 基础工具
# ============

def _now() -> float:
    return time.time()

def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0

# ======================
# 读目录（兼容旧/新结构）
# ======================

def _safe_get_i18n(i18n: Dict[str, Any]) -> Tuple[Dict[str, str], Dict[str, str]]:
    zh_map = i18n.get("zh") or i18n.get("zh_CN") or i18n.get("zh-CN") or {}
    en_map = i18n.get("en") or i18n.get("en_US") or i18n.get("en-US") or {}
    return dict(zh_map), dict(en_map)

def _merge_categories(data: Dict[str, Any]) -> Dict[str, List[str]]:
    cat = data.get("categories") or data.get("groups") or {}
    return {
        "buff": list(cat.get("buff", []) or []),
        "debuff": list(cat.get("debuff", []) or []),
        "special": list(cat.get("special", []) or []),
    }

def _gather_by_code(data: Dict[str, Any]) -> Tuple[Dict[str, List[str]], Dict[str, str]]:
    """
    返回 (by_code, macros)
    - 旧结构：patterns.global_macros + patterns.by_code
    - 新结构：fragments + patterns.{buff,debuff,special}
    """
    patt = data.get("patterns") or {}
    fragments = data.get("fragments") or {}
    macros = (patt.get("global_macros") or {}) or fragments or {}

    by_code = patt.get("by_code")
    if isinstance(by_code, dict):  # 旧结构
        return {k: list(v or []) for k, v in by_code.items()}, macros

    by_code = {}
    for cat in ("buff", "debuff", "special"):
        sub = patt.get(cat) or {}
        if isinstance(sub, dict):
            for code, arr in sub.items():
                by_code.setdefault(code, []).extend(list(arr or []))
    return by_code, macros

def _schema_is_old(data: Dict[str, Any]) -> bool:
    patt = data.get("patterns") or {}
    return isinstance(patt.get("by_code"), dict)

def load_catalog(force: bool = False) -> Dict[str, Any]:
    with _CACHE.lock:
        need_reload = force
        if not need_reload:
            if (_now() - _CACHE.loaded_at) >= TAGS_CATALOG_TTL:
                need_reload = True
            cur_mtime = _file_mtime(TAGS_CATALOG_PATH)
            if cur_mtime != _CACHE.mtime:
                need_reload = True
        if not need_reload and _CACHE.data:
            return _CACHE.data

        try:
            with open(TAGS_CATALOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"加载标签目录失败：{TAGS_CATALOG_PATH}，{e}")

        i18n = data.get("i18n", {}) or {}
        zh_map, en_map = _safe_get_i18n(i18n)
        categories = _merge_categories(data)
        by_code, macros = _gather_by_code(data)
        kws = data.get("keywords", {}) or {}

        all_codes: Set[str] = set(categories["buff"]) | set(categories["debuff"]) | set(categories["special"])

        code2cn = {c: zh_map.get(c, c) for c in all_codes}
        code2en = {c: en_map.get(c, c) for c in all_codes}

        patterns_by_code: Dict[str, List[str]] = {}
        compiled_by_code: Dict[str, List[re.Pattern]] = {}
        for code in all_codes:
            arr = list(by_code.get(code, []) or [])
            expanded = [str(p).format(**macros) if "{" in str(p) else str(p) for p in arr]
            patterns_by_code[code] = expanded
            comps: List[re.Pattern] = []
            for s in expanded:
                try:
                    comps.append(re.compile(s))
                except Exception:
                    pass
            compiled_by_code[code] = comps

        keywords_by_code = {c: list(kws.get(c, []) or []) for c in all_codes}

        _CACHE.data = data
        _CACHE.mtime = _file_mtime(TAGS_CATALOG_PATH)
        _CACHE.loaded_at = _now()
        _CACHE.code2cn = code2cn
        _CACHE.code2en = code2en
        _CACHE.categories = categories
        _CACHE.all_codes = all_codes
        _CACHE.patterns_by_code = patterns_by_code
        _CACHE.compiled_by_code = compiled_by_code
        _CACHE.keywords_by_code = keywords_by_code
        _CACHE.macros = macros

        return data

# 便捷获取
def get_i18n_map(lang: str = "zh") -> Dict[str, str]:
    data = load_catalog()
    i18n = data.get("i18n", {}) or {}
    zh_map, en_map = _safe_get_i18n(i18n)
    m = {"zh": zh_map, "en": en_map}.get(lang) or \
        i18n.get(lang) or i18n.get(f"{lang}_CN") or i18n.get(f"{lang}-CN") or {}
    if not m:
        return dict(_CACHE.code2cn)
    return {c: m.get(c, c) for c in _CACHE.all_codes}

def get_all_codes() -> Set[str]:
    load_catalog()
    return set(_CACHE.all_codes)

def get_patterns_from_catalog(compiled: bool = True) -> Dict[str, Dict[str, List[Any]]]:
    load_catalog()
    out: Dict[str, Dict[str, List[Any]]] = {"buff": {}, "debuff": {}, "special": {}}
    for cat in ("buff", "debuff", "special"):
        codes = _CACHE.categories.get(cat, []) or []
        d: Dict[str, List[Any]] = {}
        for code in codes:
            d[code] = _CACHE.compiled_by_code[code] if compiled else _CACHE.patterns_by_code[code]
        out[cat] = d
    return out

def get_keywords_map() -> Dict[str, List[str]]:
    load_catalog()
    return dict(_CACHE.keywords_by_code)

# 静态只读导出
def _init_static_exports():
    load_catalog(force=True)
    globals()["CODE2CN"] = dict(_CACHE.code2cn)
    globals()["CN2CODE"] = {v: k for k, v in _CACHE.code2cn.items()}
    globals()["ALL_CODES"] = set(_CACHE.all_codes)

_init_static_exports()

# ======================
# 文本工具
# ======================

def _skills_iter(monster: Monster, selected_only: bool = True):
    if getattr(monster, "skills", None):
        for s in monster.skills:
            yield getattr(s, "id", None), getattr(s, "name", None), getattr(s, "description", None)
        return
    if getattr(monster, "monster_skills", None):
        for ms in monster.monster_skills:
            # 如果启用了只使用推荐技能，且该技能未被选择为推荐，则跳过
            if selected_only and not getattr(ms, "selected", False):
                continue
            s = getattr(ms, "skill", None)
            if s is None:
                yield None, None, None
            else:
                desc = getattr(s, "description", None)
                yield getattr(s, "id", None), getattr(s, "name", None), desc

def _skill_texts(monster: Monster, selected_only: bool = True) -> List[Tuple[Optional[int], str, str]]:
    out = []
    for sid, name, desc in _skills_iter(monster, selected_only):
        name = str(name) if name else ""
        desc = str(desc) if desc else ""
        if (name or desc):
            out.append((sid, name, (name + " " + desc).strip()))
    return out

def _text_of_skills(monster: Monster, selected_only: bool = True) -> str:
    parts: List[str] = []
    for _, n, d in _skill_texts(monster, selected_only):
        if n: parts.append(n)
        if d: parts.append(d)
    return " ".join(parts).strip()

def _hit_any(patterns: List[Any], text: str) -> bool:
    for p in patterns:
        if isinstance(p, re.Pattern):
            if p.search(text):
                return True
        else:
            if re.search(str(p), text):
                return True
    return False

# ======================
# PP压制严格守卫
# ======================

# 只有**明确描述**“减少/降低/扣/削减 对手 技能使用次数 / PP”才算
def _pp_drain_strict(text: str) -> bool:
    if not text:
        return False
    t = str(text)
    M = _CACHE.macros or {}
    ENEMY = M.get("ENEMY", r"(?:对方|对手|敌(?:人|方))")
    ONE_OR_TWO = M.get("ONE_OR_TWO", r"(?:一|1|两|2|一或两|1或2|1-2|1～2|1~2)")
    rules = [
        rf"(?:随机)?(?:减少|降低|扣|削减)\s*{ENEMY}.*?(?:所有)?(?:技能|招式).*(?:使用)?次数(?:{ONE_OR_TWO})?次",
        r"(?:减少|降低|扣|削减)\s*PP(?:值|点|點)?",
        r"PP(?:值)?\s*(?:减少|降低|扣|削减)",
        rf"使\s*{ENEMY}.*?(?:技能|招式).*(?:次数|使用次数).*(?:减少|降低|扣|削减)"
    ]
    for r in rules:
        try:
            if re.search(r, t):
                # 排除 “PP为0/等于0/耗尽则…” 的叙述（非动作）
                if re.search(r"PP.*?(?:为|等于)\s*0|PP.*?耗尽", t):
                    continue
                return True
        except Exception:
            continue
    return False

# ======================
# 正则标签建议
# ======================

def suggest_tags_grouped(monster: Monster, selected_only: bool = True) -> Dict[str, List[str]]:
    text = _text_of_skills(monster, selected_only)
    patt = get_patterns_from_catalog(compiled=True)
    out: Dict[str, List[str]] = {"buff": [], "debuff": [], "special": []}
    for cat in ("buff", "debuff", "special"):
        codes = []
        for code, pats in patt[cat].items():
            if _hit_any(pats, text):
                codes.append(code)
        out[cat] = sorted(set(codes))

    # —— PP压制严格守卫：只在严格条件成立时保留/补标
    has = "util_pp_drain" in out["special"]
    strict = _pp_drain_strict(text)
    if strict and not has:
        out["special"].append("util_pp_drain")
    if (not strict) and has:
        out["special"] = [c for c in out["special"] if c != "util_pp_drain"]
    out["special"] = sorted(set(out["special"]))
    return out

def suggest_tags_for_monster(monster: Monster, selected_only: bool = True) -> List[str]:
    g = suggest_tags_grouped(monster, selected_only)
    flat: List[str] = []
    for cat in ("buff", "debuff", "special"):
        flat.extend(g.get(cat, []))
    seen: Set[str] = set(); res: List[str] = []
    for c in flat:
        if c not in seen:
            seen.add(c); res.append(c)
    return res

# ======================
# v2 信号（派生依赖）
# ======================

def extract_signals(monster: Monster, selected_only: bool = True) -> Dict[str, object]:
    text = _text_of_skills(monster, selected_only)
    g = suggest_tags_grouped(monster, selected_only)
    deb = set(g["debuff"]); buf = set(g["buff"]); util = set(g["special"])

    patt_text = get_patterns_from_catalog(compiled=False)

    def _p(code: str) -> List[str]:
        for cat in ("buff", "debuff", "special"):
            if code in patt_text[cat]:
                return list(patt_text[cat][code])
        return []

    # 进攻
    crit_up = ("buf_crit_up" in buf) or re.search(r"必定暴击|命中时必定暴击", text) is not None
    ignore_def = ("util_penetrate" in util) or re.search(r"无视防御|穿透(护盾|防御)", text) is not None
    armor_break = re.search(r"破防|护甲破坏", text) is not None
    def_down = ("deb_def_down" in deb)
    res_down = ("deb_res_down" in deb)
    mark = re.search(r"标记|易伤|(暴|曝)露|破绽", text) is not None
    has_multi_hit = ("util_multi" in util)

    # 生存
    heal = ("buf_heal" in buf) or re.search(r"(回复|治疗|恢复)", text) is not None
    shield = re.search(r"护盾|庇护|保护|结界|护体", text) is not None
    dmg_reduce = re.search(r"(所受|受到).*(法术|物理)?伤害.*(减少|降低|减半|减免)|伤害(减少|降低|减半|减免)", text) is not None
    cleanse_self = ("buf_purify" in buf)
    immunity = ("buf_immunity" in buf) or re.search(r"免疫(异常|控制|不良)", text) is not None
    life_steal = re.search(r"吸血|造成伤害.*(回复|恢复).*(自身|自我|HP)", text) is not None
    def_up_sig = ("buf_def_up" in buf)
    res_up_sig = ("buf_res_up" in buf)

    # 控制
    hard_cc_set = {"deb_stun","deb_sleep","deb_freeze","deb_bind"}
    soft_cc_set = {"deb_confuse_seal","deb_suffocate"}
    hard_cc = sum(1 for c in hard_cc_set if c in deb)
    soft_cc = sum(1 for c in soft_cc_set if c in deb)

    # 节奏
    first_strike = ("util_first" in util)
    speed_up = ("buf_spd_up" in buf)
    extra_turn = re.search(r"(追加|额外|再度|再动|再次|连续).*(行动|回合)|再行动(一次)?|额外回合", text) is not None
    action_bar = re.search(r"行动条|行动值|先手值|(推进|提升|增加|降低|减少).*行动(条|值)|(推条|拉条)", text) is not None

    # 压制
    pp_hits = 0
    for p in _p("util_pp_drain"):
        try:
            pp_hits += len(re.findall(p, text))
        except Exception:
            pass
    if pp_hits == 0 and re.search(r"PP|使用次数", text) and _pp_drain_strict(text):
        pp_hits = 1
    dispel_enemy = ("deb_dispel" in deb)
    skill_seal = re.search(r"封印|禁技|无法使用技能|禁止使用技能", text) is not None
    buff_steal = re.search(r"(偷取|窃取|夺取).*(增益|强化|护盾)", text) is not None
    mark_expose = mark

    return {
        "crit_up": bool(crit_up),
        "ignore_def": bool(ignore_def),
        "armor_break": bool(armor_break),
        "def_down": bool(def_down),
        "res_down": bool(res_down),
        "mark": bool(mark),
        "has_multi_hit": bool(has_multi_hit),

        "heal": bool(heal),
        "shield": bool(shield),
        "dmg_reduce": bool(dmg_reduce),
        "cleanse_self": bool(cleanse_self),
        "immunity": bool(immunity),
        "life_steal": bool(life_steal),
        "def_up_sig": bool(def_up_sig),
        "res_up_sig": bool(res_up_sig),

        "hard_cc": int(hard_cc),
        "soft_cc": int(soft_cc),

        "first_strike": bool(first_strike),
        "speed_up": bool(speed_up),
        "extra_turn": bool(extra_turn),
        "action_bar": bool(action_bar),

        "pp_hits": int(pp_hits),
        "dispel_enemy": bool(dispel_enemy),
        "skill_seal": bool(skill_seal),
        "buff_steal": bool(buff_steal),
        "mark_expose": bool(mark_expose),
    }

# ======================
# AI（仅分类）
# ======================

AI_SYSTEM_PROMPT = (
    "你是一个标签分类器。根据输入的宠物技能文本，"
    "只在以下固定标签集合中做多选，输出 JSON 对象（严格 JSON）：\n\n"
    "三类：\n"
    "- buff: {buff_codes}\n"
    "- debuff: {debuff_codes}\n"
    "- special: {special_codes}\n\n"
    "判定口径补充（务必遵守）：\n"
    "• util_pp_drain：文本**明确**出现“减少/降低/扣/削减 对手 技能（或‘所有技能’）使用次数/PP”，"
    "含“随机减少…一或两次”；“使用次数”和“PP”视为同义可互换。仅‘PP为0/耗尽则…’之类条件描述**不算**。\n"
    "• util_first：出现“先手/先制/优先行动”。\n"
    "• util_reflect：出现“反击/反伤/反弹/反射伤害”。\n"
    "• buf_shield：出现“护盾/减伤/伤害减半/保护/结界”。\n"
    "• deb_dot：出现“流血/灼伤/中毒/燃烧/持续伤害/每回合伤害”等持续掉血效果。\n"
    "• deb_dispel：对方（敌方）增益/强化被“消除/驱散/清除”。\n"
    "若无法从文本中**明确**判断，应保持保守不标注。\n\n"
    "要求：\n"
    "1) 只返回以上代码，不要新增标签或返回中文；\n"
    "2) 按语义判断是否存在该效果，有就包含到对应数组；\n"
    "3) 若没有则留空数组；\n"
    "4) 仅输出形如 {\"buff\":[],\"debuff\":[],\"special\":[]} 的 JSON；不要任何额外解释；\n"
    "5) 输入可能含中文描述与技能名。"
)

def _build_ai_payload(text: str) -> Dict[str, Any]:
    load_catalog()
    bc = ", ".join(_CACHE.categories.get("buff", []) or [])
    dc = ", ".join(_CACHE.categories.get("debuff", []) or [])
    sc = ", ".join(_CACHE.categories.get("special", []) or [])
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]
    system = (
        AI_SYSTEM_PROMPT
        .replace("{buff_codes}", bc)
        .replace("{debuff_codes}", dc)
        .replace("{special_codes}", sc)
    )
    return {
        "url": DEEPSEEK_API_URL,
        "payload": {
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"技能文本：\n{txt}\n\n请输出 JSON。"},
            ],
        },
    }

def _validate_ai_result(obj: Any) -> Dict[str, List[str]]:
    def _pick(arr: Any, allow: Set[str]) -> List[str]:
        if not isinstance(arr, list):
            return []
        seen: Set[str] = set(); out: List[str] = []
        for x in arr:
            if isinstance(x, str) and x in allow and x not in seen:
                seen.add(x); out.append(x)
        return sorted(out)
    return {
        "buff":   _pick((obj or {}).get("buff", []),   set(_CACHE.categories["buff"])),
        "debuff": _pick((obj or {}).get("debuff", []), set(_CACHE.categories["debuff"])),
        "special":_pick((obj or {}).get("special", []),set(_CACHE.categories["special"])),
    }

@lru_cache(maxsize=8192)
def _ai_classify_cached(text: str) -> Dict[str, List[str]]:
    if not _HAS_HTTPX:
        raise RuntimeError("AI 标签识别需要 httpx，请先安装依赖：pip install httpx")
    if not DEEPSEEK_API_KEY:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法进行 AI 标签识别")
    conf = _build_ai_payload(text)
    headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
    with httpx.Client(timeout=20) as client:
        resp = client.post(conf["url"], headers=headers, json=conf["payload"])
    resp.raise_for_status()
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
    return _validate_ai_result(obj)

def ai_classify_text(text: str) -> Dict[str, List[str]]:
    txt = (text or "").strip()
    if not txt:
        return {"buff": [], "debuff": [], "special": []}
    return _ai_classify_cached(txt)

def ai_suggest_tags_grouped(monster: Monster, selected_only: bool = True) -> Dict[str, List[str]]:
    return ai_classify_text(_text_of_skills(monster, selected_only))

# ======================
# 修复/并集策略（可选）
# ======================

def _find_keyword_snippet(code: str, text: str) -> Tuple[bool, Optional[str]]:
    kws = get_keywords_map().get(code, [])
    if not text or not kws:
        return False, None
    for kw in kws:
        pattern = re.escape(kw).replace("\\ ", r"\s*")
        m = re.search(pattern, text)
        if m:
            i = max(0, m.start() - 18)
            j = min(len(text), m.end() + 18)
            return True, text[i:j]
    return False, None

def _repair_union(text: str, re_flat: List[str], ai_flat: List[str]) -> Tuple[List[str], Dict[str, Any]]:
    base = list(re_flat)
    ai_only = [t for t in ai_flat if t not in base]
    verified: Dict[str, Any] = {}
    for code in ai_only:
        ok, snip = (True, None)
        if TAG_AI_REPAIR_VERIFY:
            ok, snip = _find_keyword_snippet(code, text)
        verified[code] = {"accepted": bool(ok), "snippet": snip}
        if ok:
            base.append(code)
    seen: Set[str] = set(); res: List[str] = []
    for c in base:
        if c not in seen:
            seen.add(c); res.append(c)
    return res, verified

def ai_suggest_tags_for_monster(monster: Monster, selected_only: bool = True) -> List[str]:
    text = _text_of_skills(monster, selected_only)
    ai_g = ai_classify_text(text)
    re_g = suggest_tags_grouped(monster, selected_only)

    # 拍平
    ai_flat = sorted(set(sum([ai_g.get(k, []) for k in ("buff","debuff","special")], [])))
    re_flat = sorted(set(sum([re_g.get(k, []) for k in ("buff","debuff","special")], [])))

    # 选择策略
    strategy = TAG_WRITE_STRATEGY if TAG_WRITE_STRATEGY in {"ai", "regex", "repair_union"} else "ai"
    if strategy == "ai":
        chosen = ai_flat
    elif strategy == "regex":
        chosen = re_flat
    else:
        chosen, _ = _repair_union(text, re_flat, ai_flat)

    # 去重保持顺序
    seen: Set[str] = set(); res: List[str] = []
    for c in chosen:
        if c not in seen:
            seen.add(c); res.append(c)
    return res

# ======================
# 批量 AI 打标签（含进度）
# ======================

@dataclass
class BatchJobState:
    job_id: str
    total: int
    done: int = 0
    failed: int = 0
    running: bool = True
    canceled: bool = False
    errors: List[Dict[str, Any]] = field(default_factory=list)
    started_at: float = field(default_factory=lambda: time.time())
    updated_at: float = field(default_factory=lambda: time.time())

    def to_dict(self) -> Dict[str, Any]:
        processed = self.done + self.failed
        pct = (processed / self.total) if self.total > 0 else 1.0
        elapsed = time.time() - self.started_at
        speed = (processed / elapsed) if elapsed > 0 else 0.0
        eta = int((self.total - processed) / speed) if speed > 0 else None
        def _iso(ts: float) -> str:
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        return {
            "job_id": self.job_id,
            "total": self.total,
            "done": self.done,
            "failed": self.failed,
            "processed": processed,
            "percent": round(pct * 100, 2),
            "running": self.running,
            "canceled": self.canceled,
            "started_at": _iso(self.started_at),
            "updated_at": _iso(self.updated_at),
            "eta_seconds": eta,
            "errors": self.errors[-20:],
        }

class _BatchRegistry:
    def __init__(self):
        self._jobs: Dict[str, BatchJobState] = {}
        self._lock = threading.Lock()
    def create(self, total: int) -> BatchJobState:
        with self._lock:
            job_id = uuid.uuid4().hex[:12]
            st = BatchJobState(job_id=job_id, total=int(total or 0))
            self._jobs[job_id] = st
            return st
    def get(self, job_id: str) -> Optional[BatchJobState]:
        with self._lock:
            return self._jobs.get(job_id)
    def update(self, job_id: str, *, done_inc: int = 0, failed_inc: int = 0,
               error: Optional[Dict[str, Any]] = None, running: Optional[bool] = None,
               canceled: Optional[bool] = None) -> None:
        with self._lock:
            st = self._jobs.get(job_id)
            if not st:
                return
            st.done += int(done_inc)
            st.failed += int(failed_inc)
            if error:
                st.errors.append(error)
            if running is not None:
                st.running = bool(running)
            if canceled is not None:
                st.canceled = bool(canceled)
            st.updated_at = time.time()
    def cancel(self, job_id: str) -> bool:
        with self._lock:
            st = self._jobs.get(job_id)
            if not st:
                return False
            st.canceled = True
            st.updated_at = time.time()
            return True
    def cleanup(self, older_than_seconds: int = 3600) -> int:
        now = time.time()
        removed = 0
        with self._lock:
            for k in list(self._jobs.keys()):
                st = self._jobs[k]
                if (not st.running) and (now - st.updated_at > older_than_seconds):
                    self._jobs.pop(k, None); removed += 1
        return removed

_registry = _BatchRegistry()

def get_ai_batch_progress(job_id: str) -> Optional[Dict[str, Any]]:
    st = _registry.get(job_id)
    return st.to_dict() if st else None

def cancel_ai_batch(job_id: str) -> bool:
    return _registry.cancel(job_id)

def cleanup_finished_jobs(older_than_seconds: int = 3600) -> int:
    return _registry.cleanup(older_than_seconds)

def start_ai_batch_tagging(ids: List[int], db_factory: Callable[[], Any]) -> str:
    """
    后台线程：对给定 monster id 列表执行 AI/正则 打标签（根据策略选择），并落库 tags。
    """
    ids = [int(x) for x in (ids or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    ids = list(dict.fromkeys(ids))
    st = _registry.create(total=len(ids))
    job_id = st.job_id

    def _worker(_ids: List[int], _job_id: str):
        from .monsters_service import upsert_tags  # 避免循环依赖
        try:
            for mid in _ids:
                cur = _registry.get(_job_id)
                if cur and cur.canceled:
                    _registry.update(_job_id, running=False); return
                try:
                    session = db_factory()
                    try:
                        m = session.execute(
                            select(Monster)
                            .where(Monster.id == mid)
                            .options(selectinload(Monster.skills), selectinload(Monster.tags))
                        ).scalar_one_or_none()
                        if not m:
                            _registry.update(_job_id, failed_inc=1, error={"id": mid, "error": "monster not found"})
                            continue
                        from ..config import settings
                        tags = ai_suggest_tags_for_monster(m, selected_only=settings.tag_use_selected_only)
                        m.tags = upsert_tags(session, tags)
                        session.commit()
                        _registry.update(_job_id, done_inc=1)
                    finally:
                        session.close()
                except Exception as e:
                    _registry.update(_job_id, failed_inc=1, error={"id": mid, "error": str(e)})
            _registry.update(_job_id, running=False)
        except Exception as e:
            _registry.update(_job_id, error={"id": -1, "error": f"worker crash: {e}"}, running=False)

    th = threading.Thread(target=_worker, args=(ids, job_id), name=f"ai-batch-{job_id}", daemon=True)
    th.start()
    return job_id

# ======================
# 兼容转发（定位/派生）
# ======================

def infer_role_for_monster(monster: Monster) -> str:
    """Role inference functionality has been removed."""
    return ""

def derive(monster: Monster) -> Dict[str, int]:
    """Derived stats functionality has been removed."""
    return {}

__all__ = [
    # 目录接口
    "load_catalog", "get_patterns_from_catalog", "get_i18n_map", "get_all_codes", "get_keywords_map",
    # 默认（正则）接口
    "suggest_tags_grouped", "suggest_tags_for_monster",
    "extract_signals",
    # 兼容（转发到 derive_service）
    "infer_role_for_monster", "derive",
    # AI 独立接口（单个/文本）
    "ai_classify_text", "ai_suggest_tags_grouped", "ai_suggest_tags_for_monster",
    # 批量 AI 打标签（进度）
    "start_ai_batch_tagging", "get_ai_batch_progress", "cancel_ai_batch", "cleanup_finished_jobs",
    # 为向后兼容保留
    "CODE2CN", "CN2CODE", "ALL_CODES",
]