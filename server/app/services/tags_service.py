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
from pathlib import Path  # ✅ 新增：用于构造绝对路径

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

# ✅ 修复点：默认路径改为“以本文件为基准的绝对路径”
_DEFAULT_CATALOG_PATH = str((Path(__file__).resolve().parent / "config" / "tags_catalog.json"))
TAGS_CATALOG_PATH: str = os.getenv("TAGS_CATALOG_PATH", "").strip() or _DEFAULT_CATALOG_PATH
TAGS_CATALOG_TTL: float = float(os.getenv("TAGS_CATALOG_TTL", "5"))  # 秒
TAGS_AUTOPROMOTE_THRESHOLD: int = int(os.getenv("TAGS_AUTOPROMOTE_THRESHOLD", "5"))
TAGS_AUTOPROMOTE_ENABLE: bool = os.getenv("TAGS_AUTOPROMOTE_ENABLE", "1") not in {"0", "false", "False"}

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
    cn2code: Dict[str, str] = {}
    categories: Dict[str, List[str]] = {"buff": [], "debuff": [], "special": []}
    all_codes: Set[str] = set()
    patterns_by_code: Dict[str, List[str]] = {}
    compiled_by_code: Dict[str, List[re.Pattern]] = {}
    keywords_by_code: Dict[str, List[str]] = {}
    macros: Dict[str, str] = {}

    lock = threading.RLock()

_CACHE = _CatalogCache()

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

def _expand_macros(pat: str, macros: Dict[str, str]) -> str:
    """
    将 {MACRO} 占位符替换为目录里的正则片段。
    注意：目录里已经是原始正则，无需额外转义。
    """
    s = str(pat or "")
    for k, v in macros.items():
        s = s.replace("{" + k + "}", v)
    return s

def load_catalog(force: bool = False) -> Dict[str, Any]:
    """
    读取 tags_catalog.json 并编译缓存；热更新：TTL 或 mtime 变化时触发。
    返回原始 JSON dict（只读用途）。
    """
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

        # 读盘
        try:
            with open(TAGS_CATALOG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            raise RuntimeError(f"加载标签目录失败：{TAGS_CATALOG_PATH}，{e}")

        # 基本字段
        i18n = data.get("i18n", {})
        zh_map = i18n.get("zh", {})
        en_map = i18n.get("en", {})
        cat = data.get("categories", {}) or {}
        patt = (data.get("patterns", {}) or {})
        macros = patt.get("global_macros", {}) or {}
        by_code = patt.get("by_code", {}) or {}
        kws = data.get("keywords", {}) or {}

        # 计算 code 集与中英映射
        categories = {
            "buff": list(cat.get("buff", []) or []),
            "debuff": list(cat.get("debuff", []) or []),
            "special": list(cat.get("special", []) or []),
        }
        all_codes: Set[str] = set(categories["buff"]) | set(categories["debuff"]) | set(categories["special"])
        code2cn = {c: zh_map.get(c, c) for c in all_codes}
        cn2code = {v: k for k, v in code2cn.items()}

        # 展开宏并编译正则
        patterns_by_code: Dict[str, List[str]] = {}
        compiled_by_code: Dict[str, List[re.Pattern]] = {}
        for code in all_codes:
            arr = by_code.get(code, []) or []
            expanded = [_expand_macros(p, macros) for p in arr]
            patterns_by_code[code] = expanded
            comps: List[re.Pattern] = []
            for s in expanded:
                try:
                    comps.append(re.compile(s))
                except Exception:
                    # 跳过非法正则
                    pass
            compiled_by_code[code] = comps

        # 关键词
        keywords_by_code = {c: list(kws.get(c, []) or []) for c in all_codes}

        # 更新缓存
        _CACHE.data = data
        _CACHE.mtime = _file_mtime(TAGS_CATALOG_PATH)
        _CACHE.loaded_at = _now()
        _CACHE.code2cn = code2cn
        _CACHE.cn2code = cn2code
        _CACHE.categories = categories
        _CACHE.all_codes = all_codes
        _CACHE.patterns_by_code = patterns_by_code
        _CACHE.compiled_by_code = compiled_by_code
        _CACHE.keywords_by_code = keywords_by_code
        _CACHE.macros = macros

        return data

# 便捷获取函数（会自动触发热更新）
def get_i18n_map(lang: str = "zh") -> Dict[str, str]:
    data = load_catalog()
    i18n = data.get("i18n", {})
    m = i18n.get(lang, {})
    if not m:
        # 回退中文
        return _CACHE.code2cn
    # 只返回已知 code 的映射
    return {c: m.get(c, c) for c in _CACHE.all_codes}

def get_all_codes() -> Set[str]:
    load_catalog()
    return set(_CACHE.all_codes)

def get_patterns_from_catalog(compiled: bool = True) -> Dict[str, Dict[str, List[Any]]]:
    """
    返回按类别划分的 patterns：
    { "buff": {code: [pat or compiled], ...}, "debuff": {...}, "special": {...} }
    """
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

# 维持向后兼容的只读导出（模块加载时初始化一次）
def _init_static_exports():
    load_catalog(force=True)
    globals()["CODE2CN"] = dict(_CACHE.code2cn)
    globals()["CN2CODE"] = dict(_CACHE.cn2code)
    globals()["ALL_CODES"] = set(_CACHE.all_codes)

_init_static_exports()  # 模块导入即尝试加载一次，避免其他模块 import 后拿到空映射

# ======================
# 文本工具
# ======================

def _skills_iter(monster: Monster):
    """
    统一遍历技能（兼容 Monster.skills 或 Monster.monster_skills）
    """
    if getattr(monster, "skills", None):
        for s in monster.skills:
            yield getattr(s, "name", None), getattr(s, "description", None)
        return
    if getattr(monster, "monster_skills", None):
        for ms in monster.monster_skills:
            s = getattr(ms, "skill", None)
            if s is None:
                yield None, getattr(ms, "description", None)
            else:
                # 关联上的描述优先
                desc = getattr(ms, "description", None) or getattr(s, "description", None)
                yield getattr(s, "name", None), desc

def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for n, d in _skills_iter(monster):
        if n:
            parts.append(str(n))
        if d:
            parts.append(str(d))
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
# 默认（正则）标签建议：读取“目录缓存的 patterns”
# ======================

def suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    """
    使用目录驱动的正则进行三类匹配。
    """
    text = _text_of_skills(monster)
    patt = get_patterns_from_catalog(compiled=True)

    out: Dict[str, List[str]] = {"buff": [], "debuff": [], "special": []}
    for cat in ("buff", "debuff", "special"):
        codes = []
        for code, pats in patt[cat].items():
            if _hit_any(pats, text):
                codes.append(code)
        out[cat] = sorted(set(codes))
    return out

def suggest_tags_for_monster(monster: Monster) -> List[str]:
    g = suggest_tags_grouped(monster)
    flat: List[str] = []
    for cat in ("buff", "debuff", "special"):
        flat.extend(g.get(cat, []))
    # 目录保证 code 有效，无需再过滤；保持顺序去重
    seen: Set[str] = set()
    res: List[str] = []
    for c in flat:
        if c not in seen:
            seen.add(c)
            res.append(c)
    return res

# ======================
# v2 信号（派生服务依赖）—— 仍基于正则/标签，但从目录取
# ======================

def extract_signals(monster: Monster) -> Dict[str, object]:
    """
    供 derive_service 使用（保持字段名不变）。
    """
    text = _text_of_skills(monster)
    g = suggest_tags_grouped(monster)
    deb = set(g["debuff"]); buf = set(g["buff"]); util = set(g["special"])

    # 关键字直接从目录 patterns 拿（例如 util_pp_drain 多段计数）
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
    if pp_hits == 0 and ("util_pp_drain" in util):
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
# AI 识别（允许审计 / 修复 / 候选池）
# ======================

AI_SYSTEM_PROMPT = (
    "你是一个标签分类器。根据输入的宠物技能文本，"
    "只在以下固定标签集合中做多选，输出 JSON 对象（必须是严格 JSON）：\n\n"
    "三类：\n"
    "- buff: {buff_codes}\n"
    "- debuff: {debuff_codes}\n"
    "- special: {special_codes}\n\n"
    "要求：\n"
    "1) 只返回以上代码，不要新增标签或返回中文；\n"
    "2) 按语义判断是否存在该效果，有就包含到对应数组；\n"
    "3) 若没有则留空数组；\n"
    "4) 仅输出形如 {{\"buff\":[],\"debuff\":[],\"special\":[]}} 的 JSON；不要任何额外解释；\n"
    "5) 输入可能含中文描述与技能名。"
)

FREEFORM_SYSTEM_PROMPT = (
    "你是一个效果名抽取器。阅读输入的技能文本，"
    "如果固定标签集合不够表达关键机制，请给出最多5个短语建议作为未来可能的新标签候选。"
    "输出严格 JSON：{\"candidates\": [\"短语1\", \"短语2\", ...]}；短语必须 <= 8 个汉字。"
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
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]
    return {
        "url": DEEPSEEK_API_URL,
        "payload": {
            "model": DEEPSEEK_MODEL,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": FREEFORM_SYSTEM_PROMPT},
                {"role": "user", "content": f"技能文本：\n{txt}\n\n请只输出 JSON。"},
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

def _validate_freeform(obj: Any) -> List[str]:
    if not isinstance(obj, dict):
        return []
    arr = obj.get("candidates", [])
    out: List[str] = []; seen: Set[str] = set()
    if isinstance(arr, list):
        for x in arr:
            if isinstance(x, str):
                s = x.strip()
                if not s or len(s) > 16:
                    continue
                if s not in seen:
                    seen.add(s); out.append(s)
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

def _ai_freeform_candidates(text: str) -> List[str]:
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

def ai_classify_text(text: str) -> Dict[str, List[str]]:
    txt = (text or "").strip()
    if not txt:
        return {"buff": [], "debuff": [], "special": []}
    return _ai_classify_cached(txt)

def ai_suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    return ai_classify_text(_text_of_skills(monster))

# ======================
# 审计 / Diff / 候选池与自动提升
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

def _counts_path() -> str:
    return os.path.join(TAG_AUDIT_DIR, "freeform_counts.json")

def _read_counts() -> Dict[str, int]:
    try:
        with open(_counts_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _write_counts(d: Dict[str, int]) -> None:
    try:
        _ensure_dir(TAG_AUDIT_DIR)
        with open(_counts_path(), "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def maybe_promote_candidates(cands: List[str]) -> List[str]:
    """
    将自由候选计数并在达到阈值后写入 tags_catalog.json 的 freeform_candidates。
    返回本次被提升的短语列表。
    """
    if not cands:
        return []
    counts = _read_counts()
    promoted: List[str] = []
    changed = False
    for s in cands:
        counts[s] = int(counts.get(s, 0)) + 1
        # 达阈值尝试写入目录
        if TAGS_AUTOPROMOTE_ENABLE and counts[s] >= TAGS_AUTOPROMOTE_THRESHOLD:
            try:
                with _CACHE.lock:
                    data = load_catalog()  # 取最新
                    ff = data.setdefault("freeform_candidates", [])
                    if s not in ff:
                        ff.append(s)
                        # 写回目录文件
                        with open(TAGS_CATALOG_PATH, "w", encoding="utf-8") as f:
                            json.dump(data, f, ensure_ascii=False, indent=2)
                        # 刷新缓存
                        load_catalog(force=True)
                        promoted.append(s)
                        changed = True
            except Exception:
                # 失败不影响统计
                pass
    if counts:
        _write_counts(counts)
    return promoted

def _find_keyword_snippet(code: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    在技能文本里按目录 keywords 做一次宽松验证；
    命中则返回（True, 片段），否则（False, None）
    """
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
    # 排序保持稳定
    seen: Set[str] = set(); res: List[str] = []
    for c in base:
        if c not in seen:
            seen.add(c); res.append(c)
    return res, verified

def ai_suggest_tags_for_monster(monster: Monster) -> List[str]:
    """
    AI 版拍平结果（集成：审计 / 修复 / 候选池）：
      1) AI 分类
      2) 正则对比 → 审计落盘
      3) 策略选择（ai / regex / repair_union）
      4) 自由候选计数 + 自动提升到目录 freeform_candidates（可关）
    """
    text = _text_of_skills(monster)
    ai_g = ai_classify_text(text)
    re_g = suggest_tags_grouped(monster)
    ai_flat = sorted(set(sum([ai_g.get(k, []) for k in ("buff","debuff","special")], [])))
    re_flat = sorted(set(sum([re_g.get(k, []) for k in ("buff","debuff","special")], [])))

    strategy = TAG_WRITE_STRATEGY if TAG_WRITE_STRATEGY in {"ai", "regex", "repair_union"} else "ai"
    repair_verify = {}
    if strategy == "ai":
        chosen = ai_flat
    elif strategy == "regex":
        chosen = re_flat
    else:
        chosen, repair_verify = _repair_union(text, re_flat, ai_flat)

    # 自由候选
    freeform = _ai_freeform_candidates(text) if TAG_FREEFORM_ENABLE else []
    promoted = maybe_promote_candidates(freeform) if freeform else []

    rec = {
        "timestamp": datetime.utcnow().isoformat(),
        "monster": {"id": getattr(monster, "id", None), "name": getattr(monster, "name", None)},
        "strategy": strategy,
        "skills_text_len": len(text or ""),
        "ai_grouped": ai_g,
        "regex_grouped": re_g,
        "diff": diff_tags(ai_g, re_g),
        "chosen_flat": chosen,
        "repair_verify": repair_verify,
        "freeform_candidates": freeform,
        "promoted": promoted,
    }
    record_audit(rec)
    return chosen

# ======================
# 批量 AI 打标签（含审计/策略）
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
    后台线程：对给定 monster id 列表执行 AI 打标签（含审计/修复/候选池），并落库 tags。
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
                        tags = ai_suggest_tags_for_monster(m)  # 内部已审计/修复/候选
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
# 兼容转发（定位/派生）—— 请尽快把调用方迁到 derive_service
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
    # 为向后兼容保留的只读导出（模块加载时已填充）
    "CODE2CN", "CN2CODE", "ALL_CODES",
]