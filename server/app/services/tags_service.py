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
from sqlalchemy.orm import selectinload

from ..models import Monster

# ======================
# 目录加载 / 热更新
# ======================

# 以本文件为基准，稳健找到 config/tags_catalog.json
_DEFAULT_CATALOG_PATH = str((Path(__file__).resolve().parent / "config" / "tags_catalog.json"))
TAGS_CATALOG_PATH: str = os.getenv("TAGS_CATALOG_PATH", "").strip() or _DEFAULT_CATALOG_PATH
TAGS_CATALOG_TTL: float = float(os.getenv("TAGS_CATALOG_TTL", "5"))  # 秒

# —— 自动合并阈值
TAGS_AUTOPROMOTE_THRESHOLD: int = int(os.getenv("TAGS_AUTOPROMOTE_THRESHOLD", "5"))  # 现有 code 的规则补强
TAGS_AUTOPROMOTE_ENABLE: bool = os.getenv("TAGS_AUTOPROMOTE_ENABLE", "1") not in {"0", "false", "False"}  # 默认开

# —— 新标签自动合并阈值（需求：超过5只）
NEW_TAGS_PROMOTE_THRESHOLD: int = int(os.getenv("NEW_TAGS_PROMOTE_THRESHOLD", "6"))  # ≥6只妖怪

# 审计与候选
TAG_AUDIT_ENABLE: bool = os.getenv("TAG_AUDIT_ENABLE", "1") not in {"0", "false", "False"}
TAG_AUDIT_DIR: str = os.getenv("TAG_AUDIT_DIR", "storage/tag_audit").strip()
TAG_WRITE_STRATEGY: str = os.getenv("TAG_WRITE_STRATEGY", "ai").strip().lower()  # ai | regex | repair_union
TAG_AI_REPAIR_VERIFY: bool = os.getenv("TAG_AI_REPAIR_VERIFY", "1") not in {"0", "false", "False"}
TAG_FREEFORM_ENABLE: bool = os.getenv("TAG_FREEFORM_ENABLE", "1") not in {"0", "false", "False"}

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

def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _now() -> float:
    return time.time()

def _file_mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except Exception:
        return 0.0

def _iso_now() -> str:
    return datetime.utcnow().replace(tzinfo=timezone.utc).isoformat()

def _backup_file(path: str) -> Optional[str]:
    """在写入任何 JSON 前，做一份带时间戳的 .bak 备份"""
    try:
        p = Path(path)
        if not p.exists():
            return None
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        bak = p.with_suffix(p.suffix + f".bak-{ts}")
        bak.write_bytes(p.read_bytes())
        return str(bak)
    except Exception:
        return None

def _write_json_with_backup(path: str, data: Any) -> None:
    _ensure_dir(str(Path(path).parent))
    _backup_file(path)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=False)

def _expand_macros(pat: str, macros: Dict[str, str]) -> str:
    s = str(pat or "")
    for k, v in macros.items():
        s = s.replace("{" + k + "}", v)
    return s

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
            expanded = [_expand_macros(p, macros) for p in arr]
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

def _skills_iter(monster: Monster):
    if getattr(monster, "skills", None):
        for s in monster.skills:
            yield getattr(s, "id", None), getattr(s, "name", None), getattr(s, "description", None)
        return
    if getattr(monster, "monster_skills", None):
        for ms in monster.monster_skills:
            s = getattr(ms, "skill", None)
            if s is None:
                yield None, None, getattr(ms, "description", None)
            else:
                desc = getattr(ms, "description", None) or getattr(s, "description", None)
                yield getattr(s, "id", None), getattr(s, "name", None), desc

def _skill_texts(monster: Monster) -> List[Tuple[Optional[int], str, str]]:
    out = []
    for sid, name, desc in _skills_iter(monster):
        name = str(name) if name else ""
        desc = str(desc) if desc else ""
        if (name or desc):
            out.append((sid, name, (name + " " + desc).strip()))
    return out

def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for _, n, d in _skill_texts(monster):
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

def _snippet(text: str, m: re.Match, span_pad: int = 18) -> str:
    i = max(0, m.start() - span_pad)
    j = min(len(text), m.end() + span_pad)
    return text[i:j]

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
# 正则标签建议 + 审计命中
# ======================

def suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    text = _text_of_skills(monster)
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

def _audit_regex_hits(monster: Monster) -> Dict[str, List[Dict[str, Any]]]:
    """
    返回：{ code: [ {skill_id, skill_name, snippet, pattern_id}, ... ] }
    """
    patt = get_patterns_from_catalog(compiled=True)
    hits: Dict[str, List[Dict[str, Any]]] = {}
    skills = _skill_texts(monster)
    for cat in ("buff","debuff","special"):
        for code, pats in patt[cat].items():
            for idx, pat in enumerate(pats):
                if not isinstance(pat, re.Pattern):
                    continue
                for sid, sname, stext in skills:
                    m = pat.search(stext or "")
                    if m:
                        hits.setdefault(code, []).append({
                            "skill_id": sid, "skill_name": sname,
                            "snippet": _snippet(stext, m),
                            "pattern_id": idx
                        })
    return hits

def _audit_keyword_hits(monster: Monster, codes: List[str]) -> Dict[str, List[Dict[str, Any]]]:
    """
    使用目录 keywords 做“宽匹配”来定位 AI 命中的技能（避免逐技能再调一次 AI）。
    返回：{ code: [ {skill_id, skill_name, snippet}, ... ] }
    """
    kw_map = get_keywords_map()
    hits: Dict[str, List[Dict[str, Any]]] = {}
    skills = _skill_texts(monster)
    for code in codes:
        kws = kw_map.get(code, [])
        if not kws:
            continue
        for sid, sname, stext in skills:
            for kw in kws:
                pat = re.escape(kw).replace("\\ ", r"\s*")
                m = re.search(pat, stext or "")
                if m:
                    hits.setdefault(code, []).append({
                        "skill_id": sid, "skill_name": sname,
                        "snippet": (stext[max(0, m.start()-18): m.end()+18] if stext else "")
                    })
                    break
    return hits

def suggest_tags_for_monster(monster: Monster) -> List[str]:
    g = suggest_tags_grouped(monster)
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

def extract_signals(monster: Monster) -> Dict[str, object]:
    text = _text_of_skills(monster)
    g = suggest_tags_grouped(monster)
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
            pp_hits += len(re.findall(_expand_macros(p, _CACHE.macros), text))
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
# AI（分类/规则合成/严格候选/新标签矿工）
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

FREEFORM_SYSTEM_PROMPT = (
    "你是一个效果名抽取器。仅当固定标签集合仍不足以表达关键机制时，"
    "才提出【与既有标签代码精确对应】的短语建议。\n"
    "输出严格 JSON：\n"
    "{\"candidates\": [{\"code\":\"<buf_/deb_/util_*>\",\"category\":\"buff|debuff|special\",\"phrase\":\"短语(<=8汉字)\"}, ...]}\n"
    "必须包含合法 code（上面三类之一），并给出对应短语。\n"
    "如果无法满足条件，请输出 {\"candidates\":[]}。"
)

RULE_SYNTH_SYSTEM_PROMPT = (
    "你是中文规则工程师。现在要为【既有标签代码】补充更精准的正则与关键词。\n"
    "你会得到：\n"
    "1) 目标 code 与类别；2) 可复用的 {宏} 片段（fragments）；3) 目录中该 code 的已有正则与关键词；"
    "4) 若干真实命中片段（examples）。\n"
    "任务：输出严格 JSON：\n"
    "{"
    "  \"code\":\"buf_spd_up\","
    "  \"category\":\"buff\","
    "  \"regex\": [\"{SELF}.*?速度.*?{UP}\", \"加速|迅捷|敏捷提升\"],"
    "  \"keywords\": [\"加速\",\"速度提升\",\"迅捷\"]"
    "}\n"
    "要求：\n"
    "- 使用提供的 {宏}，尽量短而稳，避免误伤；\n"
    "- 不要与已有目录正则完全重复；\n"
    "- 不要越权到其他 code 的语义；\n"
    "- 2~5条 regex，3~8 个关键词；\n"
    "- 只输出 JSON。"
)

NEW_TAG_MINER_SYSTEM_PROMPT = (
    "你是标签工程师。阅读输入技能文本，若出现**目录中不存在**但稳定表达的效果，"
    "提出**新标签定义**（必须精确归入 buff/debuff/special）。\n"
    "输出严格 JSON：{\"new_tags\":["
    "{\"code\":\"util_xxx\",\"category\":\"special\",\"zh_CN\":\"中文名<=6字\",\"en_US\":\"English(<=20)\","
    "\"regex\":[\"使用{宏}\"...2-5条],\"keywords\":[\"3-8条\"],\"examples\":[\"片段1\",\"片段2\"]}"
    "...]}\n"
    "约束：\n"
    "- code 必须匹配 ^(buf|deb|util)_[a-z0-9_]+$，且不能与已知目录 code 重复；\n"
    "- 分类必须是 buff/debuff/special；\n"
    "- 正则尽量使用提供的 {宏}，能编译；\n"
    "- 只给确实存在于文本的效果；\n"
    "- 若没有合格新标签，返回 {\"new_tags\":[]}。"
)

def _build_ai_payload(text: str) -> Dict[str, Any]:
    load_catalog()
    bc = ", ".join(_CACHE.categories.get("buff", []))
    dc = ", ".join(_CACHE.categories.get("debuff", []))
    sc = ", ".join(_CACHE.categories.get("special", []))
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]
    system = AI_SYSTEM_PROMPT.format(buff_codes=bc, debuff_codes=dc, special_codes=sc)
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

def _build_freeform_payload(text: str) -> Dict[str, Any]:
    load_catalog()
    bc = ", ".join(_CACHE.categories.get("buff", []))
    dc = ", ".join(_CACHE.categories.get("debuff", []))
    sc = ", ".join(_CACHE.categories.get("special", []))
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]
    system = FREEFORM_SYSTEM_PROMPT.replace("{buff_codes}", bc).replace("{debuff_codes}", dc).replace("{special_codes}", sc)
    return {
        "url": DEEPSEEK_API_URL,
        "payload": {
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": f"技能文本：\n{txt}\n\n请只输出 JSON。"},
            ],
        },
    }

def _build_rule_synth_payload(code: str, category: str, examples: List[str]) -> Dict[str, Any]:
    load_catalog()
    data = _CACHE.data
    fragments = data.get("fragments") or data.get("patterns", {}).get("global_macros") or {}
    # 取目录里该 code 的已有正则/关键词，辅助模型避免重复
    if _schema_is_old(data):
        existing_regex = (data.get("patterns", {}).get("by_code", {}) or {}).get(code, []) or []
    else:
        existing_regex = (data.get("patterns", {}).get(category, {}).get(code, []) if isinstance(data.get("patterns", {}).get(category, {}), dict) else []) or []
    existing_kws = (data.get("keywords", {}) or {}).get(code, []) or []

    prompt_user = {
        "code": code,
        "category": category,
        "fragments": fragments,
        "existing_regex": existing_regex[:10],
        "existing_keywords": existing_kws[:10],
        "examples": examples[:10],
    }
    return {
        "url": DEEPSEEK_API_URL,
        "payload": {
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": RULE_SYNTH_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(prompt_user, ensure_ascii=False)},
            ],
        },
    }

def _build_newtag_payload(text: str) -> Dict[str, Any]:
    load_catalog()
    data = _CACHE.data
    fragments = data.get("fragments") or data.get("patterns", {}).get("global_macros") or {}
    known_codes = sorted(list(_CACHE.all_codes))
    payload_user = {
        "fragments": fragments,
        "known_codes": known_codes,
        "text": (text or "")[:8000],
    }
    return {
        "url": DEEPSEEK_API_URL,
        "payload": {
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": NEW_TAG_MINER_SYSTEM_PROMPT},
                {"role": "user", "content": json.dumps(payload_user, ensure_ascii=False)},
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

# ---- 严格 freeform 解析/验重/计数（仅已有标签）----

_FREEFORM_CODE_RE = re.compile(r"\b(?:buf|deb|util)_[a-z0-9_]+\b", re.I)

def _code_category(code: str) -> Optional[str]:
    load_catalog()
    for cat in ("buff","debuff","special"):
        if code in _CACHE.categories.get(cat, []):
            return cat
    if code in _CACHE.all_codes:
        if code.startswith("buf_"): return "buff"
        if code.startswith("deb_"): return "debuff"
        if code.startswith("util_"): return "special"
    return None

def _normalize_phrase(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"[\s/|·•~\-—_,，。.!?；;（）()\[\]【】]+", "", s)
    return s

def _dice_sim(a: str, b: str) -> float:
    a = _normalize_phrase(a); b = _normalize_phrase(b)
    if not a or not b:
        return 0.0
    A = set(a); B = set(b)
    inter = len(A & B)
    return (2 * inter) / (len(A) + len(B))

def _too_similar_to_code(code: str, phrase: str) -> bool:
    """ 与现有code的中英名/keywords过近似 → 视为重复 """
    load_catalog()
    p = _normalize_phrase(phrase)
    base_cn = _normalize_phrase(_CACHE.code2cn.get(code, ""))
    base_en = _normalize_phrase(_CACHE.code2en.get(code, ""))
    if p == base_cn or p == base_en:
        return True
    if p and (p in base_cn or base_cn in p or p in base_en or base_en in p):
        return True
    for kw in _CACHE.keywords_by_code.get(code, []):
        q = _normalize_phrase(kw)
        if not q:
            continue
        if p == q or p in q or q in p:
            return True
        if _dice_sim(p, q) >= 0.9:
            return True
    if base_cn and _dice_sim(p, base_cn) >= 0.9:
        return True
    return False

def _too_similar_any(zh: str, en: str, kws: List[str]) -> bool:
    """ 新标签与任意已有标签过近似则拒绝 """
    load_catalog()
    cand = [_normalize_phrase(zh), _normalize_phrase(en)] + [_normalize_phrase(k) for k in (kws or [])]
    cand = [c for c in cand if c]
    for code in _CACHE.all_codes:
        base = [_normalize_phrase(_CACHE.code2cn.get(code, "")), _normalize_phrase(_CACHE.code2en.get(code, ""))]
        base += [_normalize_phrase(k) for k in _CACHE.keywords_by_code.get(code, [])]
        base = [b for b in base if b]
        for c in cand:
            for b in base:
                if not b:
                    continue
                if c == b or c in b or b in c or _dice_sim(c, b) >= 0.9:
                    return True
    return False

def _parse_freeform_item(item: Any) -> Optional[Dict[str, str]]:
    """
    返回 dict: {"code":..., "category":..., "phrase":...}
    仅当存在合法 code 且短语有效时返回。
    """
    code = None; cat = None; phrase = None

    if isinstance(item, dict):
        code = str(item.get("code", "")).strip()
        phrase = str(item.get("phrase", "")).strip()
        cat = str(item.get("category", "")).strip().lower() or None
    elif isinstance(item, str):
        s = item.strip()
        m = _FREEFORM_CODE_RE.search(s)
        if not m:
            return None
        code = m.group(0)
        suffix = s[m.end():].strip(" :：-—[]()")
        prefix = s[:m.start()].strip(" :：-—[]()")
        phrase = suffix or prefix or ""
    else:
        return None

    if not code or code not in _CACHE.all_codes:
        return None

    real_cat = _code_category(code)
    if not real_cat:
        return None
    if cat and cat not in {"buff","debuff","special"}:
        return None
    if cat and cat != real_cat:
        return None
    cat = real_cat

    phrase = (phrase or "").strip()
    if not phrase:
        return None
    if len(phrase) > 16:
        return None
    if len(re.findall(r"[\u4e00-\u9fff]", phrase)) > 8:
        return None

    if _too_similar_to_code(code, phrase):
        return None

    return {"code": code, "category": cat, "phrase": phrase}

def _validate_freeform(obj: Any) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    arr = (obj or {}).get("candidates", [])
    if not isinstance(arr, list):
        return out
    for item in arr:
        parsed = _parse_freeform_item(item)
        if parsed:
            out.append(parsed)
    return out[:5]

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

def _ai_freeform_candidates(text: str) -> List[Dict[str, str]]:
    if not TAG_FREEFORM_ENABLE or not _HAS_HTTPX or not DEEPSEEK_API_KEY:
        return []
    try:
        conf = _build_freeform_payload(text)
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        with httpx.Client(timeout=20) as client:
            resp = client.post(conf["url"], headers=headers, json=conf["payload"])
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
        return _validate_freeform(obj)
    except Exception:
        return []

def _ai_rule_synthesis(code: str, category: str, examples: List[str]) -> Tuple[List[str], List[str]]:
    """
    让 AI 基于 examples + fragments + 目录现有规则，给出候选 regex/keywords。
    失败或输出非法时返回空列表。
    """
    if not _HAS_HTTPX or not DEEPSEEK_API_KEY:
        return [], []
    try:
        conf = _build_rule_synth_payload(code, category, examples)
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        with httpx.Client(timeout=25) as client:
            resp = client.post(conf["url"], headers=headers, json=conf["payload"])
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
        if not isinstance(obj, dict) or obj.get("code") != code or obj.get("category") != category:
            return [], []
        regex = [str(x) for x in (obj.get("regex") or []) if isinstance(x, str)]
        keywords = [str(x) for x in (obj.get("keywords") or []) if isinstance(x, str)]
        # 清洗：去空/去重/限制数量
        seen = set(); rex = []
        for r in regex:
            r = r.strip()
            if not r or len(r) > 200:
                continue
            if r not in seen:
                seen.add(r); rex.append(r)
        kw_seen = set(); kws = []
        for k in keywords:
            k = k.strip()
            if not k or len(k) > 20:
                continue
            if k not in kw_seen:
                kw_seen.add(k); kws.append(k)
        return rex[:5], kws[:8]
    except Exception:
        return [], []

def _ai_new_tag_candidates(text: str) -> List[Dict[str, Any]]:
    """
    让 AI 在文本中提出【新标签】定义：
    返回每项: {"code","category","zh_CN","en_US","regex":[...],"keywords":[...],"examples":[...]}
    仅校验 JSON 结构，具体合法性在合并到工作台时二次校验。
    """
    if not _HAS_HTTPX or not DEEPSEEK_API_KEY:
        return []
    try:
        conf = _build_newtag_payload(text)
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}", "Content-Type": "application/json"}
        with httpx.Client(timeout=25) as client:
            resp = client.post(conf["url"], headers=headers, json=conf["payload"])
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
        arr = obj.get("new_tags", [])
        out: List[Dict[str, Any]] = []
        if isinstance(arr, list):
            for it in arr:
                if not isinstance(it, dict):
                    continue
                code = str(it.get("code","")).strip()
                cat = str(it.get("category","")).strip().lower()
                zh = str(it.get("zh_CN","")).strip()
                en = str(it.get("en_US","")).strip()
                regex = [str(x).strip() for x in (it.get("regex") or []) if isinstance(x, (str,))]
                kws = [str(x).strip() for x in (it.get("keywords") or []) if isinstance(x, (str,))]
                exs = [str(x).strip() for x in (it.get("examples") or []) if isinstance(x, (str,))]
                out.append({
                    "code": code, "category": cat, "zh_CN": zh, "en_US": en,
                    "regex": regex, "keywords": kws, "examples": exs
                })
        return out[:5]
    except Exception:
        return []

# ======================
# 工作台（freeform_counts.json）
# ======================

def _workbench_path() -> str:
    return os.path.join(TAG_AUDIT_DIR, "freeform_counts.json")

def _empty_workbench() -> Dict[str, Any]:
    load_catalog()
    return {
        "schema_version": 2,
        "updated_at": _iso_now(),
        "i18n": {},
        "fragments": _CACHE.macros,                  # 与目录一致
        "patterns": {"buff": {}, "debuff": {}, "special": {}},  # 既有 code 的规则候选
        "keywords": {},                               # 既有 code 的关键词候选
        "counts": {"buff": {}, "debuff": {}, "special": {}},    # 既有 code 的阈值计数
        "examples": {},                               # 既有 code 的示例
        # —— 新标签候选区：按类别存储
        "new_tags": {
            "buff": {},  # code: {zh_CN,en_US,regex,keywords,examples,count}
            "debuff": {},
            "special": {}
        }
    }

def _read_workbench() -> Dict[str, Any]:
    try:
        with open(_workbench_path(), "r", encoding="utf-8") as f:
            wb = json.load(f)
        wb.setdefault("patterns", {}).setdefault("buff", {})
        wb["patterns"].setdefault("debuff", {})
        wb["patterns"].setdefault("special", {})
        wb.setdefault("keywords", {})
        wb.setdefault("counts", {"buff": {}, "debuff": {}, "special": {}})
        wb.setdefault("examples", {})
        wb.setdefault("new_tags", {"buff": {}, "debuff": {}, "special": {}})
        for k in ("buff","debuff","special"):
            wb["new_tags"].setdefault(k, {})
        return wb
    except Exception:
        return _empty_workbench()

def _write_workbench(wb: Dict[str, Any]) -> None:
    wb["updated_at"] = _iso_now()
    _write_json_with_backup(_workbench_path(), wb)

def _wb_merge_proposal(wb: Dict[str, Any], category: str, code: str,
                       regex: List[str], keywords: List[str], ex_snippets: List[str]) -> None:
    # 合并正则
    pat_map = wb["patterns"].setdefault(category, {})
    arr = pat_map.setdefault(code, [])
    exist = set(arr)
    for r in regex:
        if r and r not in exist:
            arr.append(r); exist.add(r)
    # 合并关键词
    kw_map = wb["keywords"].setdefault(code, [])
    kw_set = set(kw_map)
    for k in keywords:
        if k and k not in kw_set:
            kw_map.append(k); kw_set.add(k)
    # 合并例子（限量）
    ex = wb["examples"].setdefault(code, [])
    for s in ex_snippets[:5]:
        if s and s not in ex:
            ex.append(s)
    # 计数（每次调用 +1）
    cnt_map = wb["counts"].setdefault(category, {})
    cnt_map[code] = int(cnt_map.get(code, 0)) + 1

def _patterns_of_code_from_catalog(data: Dict[str, Any], category: str, code: str) -> List[str]:
    if _schema_is_old(data):
        return (data.get("patterns", {}).get("by_code", {}) or {}).get(code, []) or []
    sub = data.get("patterns", {}).get(category, {})
    if isinstance(sub, dict):
        return sub.get(code, []) or []
    return []

def _apply_promotions_if_ready(wb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    达阈值则把 workbench 的候选（该 code 的增量）写入目录（既有 code）：
    - 仅追加尚未在目录中的正则与关键词
    - 写目录前先备份
    返回已应用列表 [{code, category, added_regex:[...], added_keywords:[...]}]
    """
    if not TAGS_AUTOPROMOTE_ENABLE:
        return []
    promos: List[Dict[str, Any]] = []
    with _CACHE.lock:
        data = load_catalog()
        changed = False
        for cat in ("buff","debuff","special"):
            cnt_map = wb.get("counts", {}).get(cat, {}) or {}
            for code, cnt in cnt_map.items():
                if cnt < TAGS_AUTOPROMOTE_THRESHOLD:
                    continue
                cand_regex = wb.get("patterns", {}).get(cat, {}).get(code, []) or []
                cand_kws = wb.get("keywords", {}).get(code, []) or []
                if not cand_regex and not cand_kws:
                    continue
                exist_regex = set(_patterns_of_code_from_catalog(data, cat, code))
                add_regex = [r for r in cand_regex if r not in exist_regex]
                if not data.get("keywords"):
                    data["keywords"] = {}
                exist_kws = set((data["keywords"].get(code, []) or []))
                add_kws = [k for k in cand_kws if k not in exist_kws]
                if not add_regex and not add_kws:
                    continue
                # 追加到目录
                if _schema_is_old(data):
                    data.setdefault("patterns", {}).setdefault("by_code", {}).setdefault(code, [])
                    data["patterns"]["by_code"][code].extend(add_regex)
                else:
                    data.setdefault("patterns", {}).setdefault(cat, {}).setdefault(code, [])
                    data["patterns"][cat][code].extend(add_regex)
                data.setdefault("keywords", {}).setdefault(code, [])
                data["keywords"][code].extend(add_kws)
                promos.append({"code": code, "category": cat,
                               "added_regex": add_regex, "added_keywords": add_kws})
                changed = True
        if changed:
            _write_json_with_backup(TAGS_CATALOG_PATH, data)
            load_catalog(force=True)
    return promos

# ===== 新标签：英文名规范校验、合并与自动并入目录 =====

_NEW_CODE_RE = re.compile(r"^(buf|deb|util)_[a-z0-9_]+$")

_EN_UPCASE_TOKENS = {"ATK","DEF","MAG","RES","SPD","ACC","PP","HP"}

def _canonical_en_name_for_code(code: str, name: str) -> str:
    """
    规范化英文展示名：
    - 去首尾空格、合并多空格
    - 斜杠左右强制留单个空格：" A / B "
    - 圆括号内容 Title Case，且 Self 统一为 (Self)
    - 普通词 Title Case；ATK/DEF/MAG/RES/SPD/ACC/PP/HP 保持全大写
    - Multi-hit 等保持连字符
    """
    s = (name or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"\s*/\s*", " / ", s)  # 斜杠两侧空格

    # 标准化 (self) -> (Self)
    s = re.sub(r"\(\s*self\s*\)", "(Self)", s, flags=re.I)

    def _word_case(w: str) -> str:
        raw = w
        w = w.strip()
        if not w:
            return raw
        core = w.strip("()")
        left = "(" if w.startswith("(") else ""
        right = ")" if w.endswith(")") else ""

        token = re.sub(r"[^A-Za-z]", "", core).upper()
        if token in _EN_UPCASE_TOKENS:
            out = token
        else:
            parts = core.split("-")
            parts = [p.capitalize() if p else p for p in parts]
            out = "-".join(parts)

        # 常见词统一首字母大写
        if out.lower() in {"up","down","over","next","double","first","cleanse","status",
                           "immunity","drain","reflect","counter","charge","penetrate",
                           "shield","damage","cut","rate","enemy","buffs","strike",
                           "multi","hit","value","times"}:
            out = out.capitalize()

        return f"{left}{out}{right}"

    tokens = re.split(r"(\s+|/)", s)
    canon = []
    for t in tokens:
        if t == "/" or re.match(r"^\s+$", t or ""):
            canon.append(t)
        else:
            canon.append(_word_case(t))
    s = "".join(canon)
    s = re.sub(r"\s*/\s*", " / ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _validate_en_name(code: str, en_name: str) -> Tuple[bool, str, str]:
    """
    返回 (ok, canonical, reason)
    规则：
      - 只能包含字母/空格/斜杠/连字符/括号
      - 斜杠两侧必须有空格
      - ATK/DEF/MAG/RES/SPD/ACC/PP/HP 必须全大写
      - 括号内 Self -> (Self)
    """
    if not en_name or not isinstance(en_name, str):
        return False, "", "empty-en-name"

    s = _canonical_en_name_for_code(code, en_name)

    # 字符约束
    if re.search(r"[^A-Za-z\s/\-\(\)]", s):
        return False, s, "illegal-characters"

    # 斜杠两侧空格
    if "/" in s and not re.search(r"\s/\s", s):
        return False, s, "slash-spacing"

    # 大写缩写检查
    for tk in _EN_UPCASE_TOKENS:
        if re.search(rf"\b{tk.lower()}\b", s):
            return False, s, f"token-not-uppercase:{tk}"

    # Self 括号
    if re.search(r"\(self\)", s, flags=re.I):
        return False, s, "paren-self-not-canonical"

    return True, s, ""

def _merge_new_tag_candidate(wb: Dict[str, Any], cand: Dict[str, Any]) -> Optional[str]:
    """
    合并单个新标签候选到工作台：
    - 校验 code/分类/名称（含英文规范）/正则可编译；
    - 与已存在标签近似则拒绝；
    - 每次调用 count+1（同一只妖怪一次）。
    返回拒绝原因字符串；通过时返回 None。
    """
    code = (cand.get("code") or "").strip()
    cat = (cand.get("category") or "").strip().lower()
    zh = (cand.get("zh_CN") or "").strip()
    en = (cand.get("en_US") or "").strip()
    regex = [r for r in (cand.get("regex") or []) if isinstance(r, str)]
    kws = [k for k in (cand.get("keywords") or []) if isinstance(k, str)]
    exs = [e for e in (cand.get("examples") or []) if isinstance(e, str)]

    if not _NEW_CODE_RE.match(code):
        return "invalid_code_format"
    if code in _CACHE.all_codes:
        return "code_exists"
    if cat not in {"buff","debuff","special"}:
        return "invalid_category"
    if not zh or len(zh) > 12:
        return "invalid_zh"

    # 英文名规范化与校验
    ok, en_canon, reason = _validate_en_name(code, en)
    if not ok:
        return f"invalid_en:{reason}"
    en = en_canon

    # 至少1条可编译正则
    valid_rex = []
    for r in regex:
        try:
            re.compile(_expand_macros(r, _CACHE.macros))
            valid_rex.append(r)
        except Exception:
            pass
    if not valid_rex:
        return "no_compilable_regex"
    # 近似检查（与全库）
    if _too_similar_any(zh, en, kws):
        return "too_similar_existing"

    bucket = wb["new_tags"].setdefault(cat, {})
    rec = bucket.get(code) or {"zh_CN": zh, "en_US": en, "regex": [], "keywords": [], "examples": [], "count": 0}
    # 名称以首次出现为准，不覆盖；若后续与首次不一致则拒绝
    if rec["zh_CN"] != zh or rec["en_US"] != en:
        return "name_conflict_with_existing_candidate"

    # 合并正则/关键词/例子
    rex_set = set(rec.get("regex", []))
    for r in valid_rex:
        if r not in rex_set:
            rec["regex"].append(r); rex_set.add(r)
    kw_set = set(rec.get("keywords", []))
    for k in kws:
        if k and k not in kw_set:
            rec["keywords"].append(k); kw_set.add(k)
    ex_set = set(rec.get("examples", []))
    for e in exs[:5]:
        if e and e not in ex_set:
            rec["examples"].append(e); ex_set.add(e)
    # 计数 +1
    rec["count"] = int(rec.get("count", 0)) + 1
    bucket[code] = rec
    return None

def _apply_new_tag_promotions_if_ready(wb: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    将 new_tags 中 count ≥ NEW_TAGS_PROMOTE_THRESHOLD 的条目升格到 tags_catalog：
    - 写入 groups/类别；
    - 写入 i18n.zh_CN / en_US；
    - 写入 patterns[类别][code] 与 keywords[code]；
    - 自动备份 + 热更新；
    返回 [{code, category}]。
    """
    applied: List[Dict[str, Any]] = []
    with _CACHE.lock:
        data = load_catalog()
        changed = False
        for cat in ("buff","debuff","special"):
            bucket = wb.get("new_tags", {}).get(cat, {}) or {}
            for code, rec in bucket.items():
                if int(rec.get("count", 0)) < NEW_TAGS_PROMOTE_THRESHOLD:
                    continue
                if code in _CACHE.all_codes:
                    continue  # 已经存在则跳过
                # 写 groups
                groups_key = "groups" if data.get("groups") else "categories"
                data.setdefault(groups_key, {}).setdefault(cat, [])
                if code not in data[groups_key][cat]:
                    data[groups_key][cat].append(code)
                # 写 i18n
                data.setdefault("i18n", {})
                for lang_key in ("zh_CN","en_US"):
                    data["i18n"].setdefault(lang_key, {})
                data["i18n"]["zh_CN"][code] = rec.get("zh_CN") or code
                data["i18n"]["en_US"][code] = rec.get("en_US") or code
                # 写 patterns
                if _schema_is_old(data):
                    data.setdefault("patterns", {}).setdefault("by_code", {}).setdefault(code, [])
                    data["patterns"]["by_code"][code].extend([r for r in rec.get("regex", []) if isinstance(r, str)])
                else:
                    data.setdefault("patterns", {}).setdefault(cat, {}).setdefault(code, [])
                    data["patterns"][cat][code].extend([r for r in rec.get("regex", []) if isinstance(r, str)])
                # 写 keywords
                data.setdefault("keywords", {}).setdefault(code, [])
                data["keywords"][code].extend([k for k in rec.get("keywords", []) if isinstance(k, str)])
                applied.append({"code": code, "category": cat})
                changed = True
        if changed:
            _write_json_with_backup(TAGS_CATALOG_PATH, data)
            load_catalog(force=True)
    return applied

# ======================
# 审计 / Diff / 严格候选计数（既有标签）
# ======================

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d")

def diff_tags(ai_g: Dict[str, List[str]], re_g: Dict[str, List[str]]) -> Dict[str, Any]:
    diff: Dict[str, Any] = {"by_cat": {}, "overall": {}}
    total_ai, total_re = set(), set()
    for cat in ("buff", "debuff", "special"):
        ai_set = set(ai_g.get(cat, []))
        re_set = set(re_g.get(cat, []))
        total_ai |= ai_set; total_re |= re_set
        diff["by_cat"][cat] = {
            "ai_only": sorted(list(ai_set - re_set)),
            "regex_only": sorted(list(re_set - ai_set)),
            "both": sorted(list(ai_set & re_set)),
        }
    diff["overall"] = {
        "ai_only": sorted(list(total_ai - total_re)),
        "regex_only": sorted(list(total_re - total_ai)),
        "both": sorted(list(total_ai & total_re)),
        "ai_flat": sorted(list(total_ai)),
        "regex_flat": sorted(list(total_re)),
    }
    return diff

def record_audit(record: Dict[str, Any]) -> None:
    if not TAG_AUDIT_ENABLE:
        return
    try:
        _ensure_dir(TAG_AUDIT_DIR)
        dayfile = os.path.join(TAG_AUDIT_DIR, f"audit_{_today_str()}.jsonl")
        with open(dayfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        mon = record.get("monster", {})
        monfile = os.path.join(TAG_AUDIT_DIR, f"mon_{mon.get('id','unknown')}_latest.json")
        with open(monfile, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def _workbench_merge_and_maybe_promote(proposals: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    proposals 结构：
    { "buff": { code: {"regex":[...], "keywords":[...], "examples":[...]} }, ... }
    合并进 workbench 后尝试阈值自动写入目录（自动备份）。
    返回已应用到目录的 promotions 列表。
    """
    if not proposals:
        return []
    wb = _read_workbench()
    for cat in ("buff","debuff","special"):
        sub = proposals.get(cat, {}) or {}
        for code, obj in sub.items():
            regex = [r for r in (obj.get("regex") or []) if isinstance(r, str)]
            keywords = [k for k in (obj.get("keywords") or []) if isinstance(k, str)]
            examples = [e for e in (obj.get("examples") or []) if isinstance(e, str)]
            _wb_merge_proposal(wb, cat, code, regex, keywords, examples)
    _write_workbench(wb)
    return _apply_promotions_if_ready(wb)

def maybe_promote_candidates(cands: List[Dict[str, str]]) -> List[Dict[str, str]]:
    """
    仅对“短语”进行严格计数（必须带 code，避免新增标签）。
    不直接改目录；目录改动由规则工作台阈值流程掌控。
    """
    if not cands:
        return []
    wb = _read_workbench()
    accepted: List[Dict[str, str]] = []
    for item in cands:
        parsed = _parse_freeform_item(item)
        if not parsed:
            continue
        code = parsed["code"]; cat = parsed["category"]; phrase = parsed["phrase"]
        if _too_similar_to_code(code, phrase):
            continue
        # 把短语也作为 keywords 候选合入工作台（不含正则）
        _wb_merge_proposal(wb, cat, code, [], [phrase], [])
        accepted.append(parsed)
    _write_workbench(wb)
    return accepted

# ======================
# 主要入口：AI 打标 + 审计增强 + 规则合成 + 新标签矿工 + 阈值自动合并
# ======================

def ai_classify_text(text: str) -> Dict[str, List[str]]:
    txt = (text or "").strip()
    if not txt:
        return {"buff": [], "debuff": [], "special": []}
    return _ai_classify_cached(txt)

def ai_suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    return ai_classify_text(_text_of_skills(monster))

def ai_suggest_tags_for_monster(monster: Monster) -> List[str]:
    text = _text_of_skills(monster)
    ai_g = ai_classify_text(text)
    re_g = suggest_tags_grouped(monster)

    # 审计：逐技能命中（正则/关键词）
    regex_hits = _audit_regex_hits(monster)
    ai_flat_all = sorted(set(sum([ai_g.get(k, []) for k in ("buff","debuff","special")], [])))
    kw_hits = _audit_keyword_hits(monster, ai_flat_all)

    # 拍平
    ai_flat = sorted(set(sum([ai_g.get(k, []) for k in ("buff","debuff","special")], [])))
    re_flat = sorted(set(sum([re_g.get(k, []) for k in ("buff","debuff","special")], [])))

    # 选择策略
    strategy = TAG_WRITE_STRATEGY if TAG_WRITE_STRATEGY in {"ai", "regex", "repair_union"} else "ai"
    repair_verify = {}
    if strategy == "ai":
        chosen = ai_flat
    elif strategy == "regex":
        chosen = re_flat
    else:
        chosen, repair_verify = _repair_union(text, re_flat, ai_flat)

    # 自由候选短语（严格计数到工作台 keywords）
    freeform = _ai_freeform_candidates(text) if TAG_FREEFORM_ENABLE else []
    freeform_counted = maybe_promote_candidates(freeform) if freeform else []

    # 规则合成（针对 AI-only code），并尝试阈值自动合并到目录
    diff = diff_tags(ai_g, re_g)
    ai_only_codes = diff["overall"]["ai_only"]
    proposals: Dict[str, Dict[str, Any]] = {"buff": {}, "debuff": {}, "special": {}}
    for code in ai_only_codes:
        cat = _code_category(code)
        if not cat:
            continue
        # examples
        ex = []
        for hit in (kw_hits.get(code, []) or [])[:3]:
            ex.append(hit.get("snippet") or "")
        if not ex:
            for hit in (regex_hits.get(code, []) or [])[:2]:
                ex.append(hit.get("snippet") or "")
        if not ex and text:
            ex = [text[:180]]
        # AI 产出 regex/keywords
        rex, kws = _ai_rule_synthesis(code, cat, ex)
        # 保守：必须至少有 1 条能编译通过的正则才纳入工作台
        valid_rex = []
        for r in rex:
            try:
                re.compile(_expand_macros(r, _CACHE.macros))
                valid_rex.append(r)
            except Exception:
                pass
        if not valid_rex and not kws:
            continue
        proposals[cat].setdefault(code, {"regex": [], "keywords": [], "examples": []})
        proposals[cat][code]["regex"].extend(valid_rex)
        proposals[cat][code]["keywords"].extend(kws)
        proposals[cat][code]["examples"].extend(ex)

    applied_existing = _workbench_merge_and_maybe_promote(proposals) if any(proposals[c] for c in proposals) else []

    # —— 新标签矿工：提出新 code，并入工作台 new_tags（≥6 只自动并入目录）
    new_tag_defs = _ai_new_tag_candidates(text) or []
    wb = _read_workbench()
    rejected_reasons: List[Dict[str, Any]] = []
    accepted_new: List[str] = []
    for cand in new_tag_defs:
        # 不要接受“PP压制”类错误新标签：利用守卫进行筛除（若 code 指向 util_pp_drain 仍按既有标签路径处理）
        if cand.get("code") == "util_pp_drain":
            continue
        reason = _merge_new_tag_candidate(wb, cand)
        if reason is None:
            accepted_new.append(cand.get("code",""))
        else:
            rejected_reasons.append({"code": cand.get("code",""), "reason": reason})
    if new_tag_defs:
        _write_workbench(wb)
    applied_new = _apply_new_tag_promotions_if_ready(wb) if accepted_new else []

    # 审计落盘
    rec = {
        "timestamp": _iso_now(),
        "monster": {"id": getattr(monster, "id", None), "name": getattr(monster, "name", None)},
        "strategy": strategy,
        "skills_text_len": len(text or ""),
        "ai_grouped": ai_g,
        "regex_grouped": re_g,
        "diff": diff,
        "chosen_flat": chosen,
        "repair_verify": repair_verify,
        # 具体技能命中
        "regex_hits": regex_hits,
        "keyword_hits": kw_hits,
        # 候选与目录应用情况（既有标签）
        "freeform_candidates": freeform,
        "freeform_counted": freeform_counted,
        "rule_proposals_keys": {k: list((proposals.get(k) or {}).keys()) for k in ("buff","debuff","special")},
        "promotions_applied_existing": applied_existing,
        # 新标签
        "new_tag_candidates": new_tag_defs,
        "new_tag_accepted_codes": accepted_new,
        "new_tag_rejected": rejected_reasons,
        "new_tag_promoted": applied_new,
    }
    record_audit(rec)
    return chosen

# ======================
# 修复/并集策略
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
    后台线程：对给定 monster id 列表执行 AI 打标签（含审计/规则合成/新标签矿工/自动合并），并落库 tags。
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
                        tags = ai_suggest_tags_for_monster(m)
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
    from .derive_service import infer_role_for_monster as _infer
    return _infer(monster)

def derive(monster: Monster) -> Dict[str, int]:
    from .derive_service import compute_derived_out
    return compute_derived_out(monster)

__all__ = [
    # 目录接口
    "load_catalog", "get_patterns_from_catalog", "get_i18n_map", "get_all_codes", "get_keywords_map",
    # 默认（正则）接口
    "suggest_tags_grouped", "suggest_tags_for_monster",
    "extract_signals",
    # 审计&候选
    "diff_tags", "record_audit", "maybe_promote_candidates",
    # 兼容（转发到 derive_service）
    "infer_role_for_monster", "derive",
    # AI 独立接口（单个/文本）
    "ai_classify_text", "ai_suggest_tags_grouped", "ai_suggest_tags_for_monster",
    # 批量 AI 打标签（进度）
    "start_ai_batch_tagging", "get_ai_batch_progress", "cancel_ai_batch", "cleanup_finished_jobs",
    # 为向后兼容保留
    "CODE2CN", "CN2CODE", "ALL_CODES",
]