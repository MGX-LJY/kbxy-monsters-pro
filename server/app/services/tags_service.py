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

try:
    import httpx  # 仅 AI 接口需要；未安装也不影响默认正则路径
    _HAS_HTTPX = True
except Exception:
    _HAS_HTTPX = False

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from ..models import Monster

# ======================
# 规范化标签：以代码存库（前缀分类）
# ======================

# —— 增强类（buff/自强化） —— #
BUFF_CANON: Dict[str, str] = {
    "buf_atk_up":   "攻↑",
    "buf_mag_up":   "法↑",
    "buf_spd_up":   "速↑",
    "buf_def_up":   "防↑",
    "buf_res_up":   "抗↑",
    "buf_acc_up":   "命中↑",
    "buf_crit_up":  "暴击↑",
    "buf_heal":     "治疗",
    "buf_shield":   "护盾/减伤",
    "buf_purify":   "净化己减益",
    "buf_immunity": "免疫异常",
}

# —— 削弱类（debuff/对敌负面） —— #
DEBUFF_CANON: Dict[str, str] = {
    "deb_atk_down":     "攻↓",
    "deb_mag_down":     "法术↓",
    "deb_def_down":     "防↓",
    "deb_res_down":     "抗↓",
    "deb_spd_down":     "速↓",
    "deb_acc_down":     "命中↓",
    "deb_stun":         "眩晕/昏迷",
    "deb_bind":         "束缚/禁锢",
    "deb_sleep":        "睡眠",
    "deb_freeze":       "冰冻",
    "deb_confuse_seal": "混乱/封印",
    "deb_suffocate":    "窒息",
    "deb_dot":          "持续伤害",
    "deb_dispel":       "驱散敌增益",
}

# —— 特殊类（utility/玩法特性） —— #
SPECIAL_CANON: Dict[str, str] = {
    "util_first":        "先手",
    "util_multi":        "多段",
    "util_pp_drain":     "PP压制",
    "util_reflect":      "反击/反伤",
    "util_charge_next":  "加倍/下一击强",
    "util_penetrate":    "穿透/破盾",
}

# code -> 中文 / 中文 -> code
CODE2CN: Dict[str, str] = {**BUFF_CANON, **DEBUFF_CANON, **SPECIAL_CANON}
CN2CODE: Dict[str, str] = {v: k for k, v in CODE2CN.items()}

ALL_BUFF_CODES: Set[str] = set(BUFF_CANON.keys())
ALL_DEBUFF_CODES: Set[str] = set(DEBUFF_CANON.keys())
ALL_SPECIAL_CODES: Set[str] = set(SPECIAL_CANON.keys())
ALL_CODES: Set[str] = set(CODE2CN.keys())

# ======================
# 通用片段（用于正则）
# ======================

CN_NUM = r"[一二两三四五六七八九十百千]+"
SELF   = r"(?:自身|自我|自己|本方|我方)"
ENEMY  = r"(?:对方|对手|敌(?:人|方))"
UP     = r"(?:提升|提高|上升|增强|增加|加成|升高|强化)"
DOWN   = r"(?:下降|降低|减少|衰减|减弱)"
LEVEL  = rf"(?:\s*(?:{CN_NUM}|\d+)\s*级)?"
ONE_OR_TWO = r"(?:一|1|两|2|一或两|1或2|1-2|1～2|1~2)"
SEP    = r"(?:\s*[、，,/和与及]+\s*)"

# ======================
# 文本正则（默认路径用它；AI 失败不回退到这里，AI 是独立接口）
# ======================

BUFF_PATTERNS: Dict[str, List[str]] = {
    "buf_atk_up": [
        rf"{SELF}.*?攻击.*?{UP}",
        rf"{UP}.*?{SELF}.*?攻击",
        rf"攻击(?:{SEP}(?:法术|魔法|防御|速度|抗性|命中率|暴击率))*?各{UP}{LEVEL}",
        rf"有\d+%?机会.*?{UP}.*?{SELF}.*?攻击",
    ],
    "buf_mag_up": [
        rf"{SELF}.*?(法术|魔法).*?{UP}",
        rf"{UP}.*?{SELF}.*?(法术|魔法)",
        rf"(法术|魔法)(?:{SEP}(?:攻击|防御|速度|抗性|命中率|暴击率))*?各{UP}{LEVEL}",
        rf"有\d+%?机会.*?{UP}.*?{SELF}.*?(法术|魔法)",
    ],
    "buf_spd_up": [
        rf"{SELF}.*?速度.*?{UP}|{SELF}.*?(加速|迅捷|敏捷提升|加快速度)",
        rf"{UP}.*?{SELF}.*?速度",
        rf"速度(?:{SEP}(?:攻击|防御|法术|魔法|抗性))*?各{UP}{LEVEL}",
    ],
    "buf_def_up": [
        rf"{SELF}.*?(防御|防御力).*?{UP}|{SELF}.*?(护甲|硬化|铁壁)",
        rf"{UP}.*?{SELF}.*?(防御|防御力)",
        rf"(防御|防御力)(?:{SEP}(?:攻击|法术|魔法|速度|抗性))*?各{UP}{LEVEL}",
    ],
    "buf_res_up": [
        rf"{SELF}.*?(抗性|抗性值).*?{UP}|{SELF}.*?抗性增强|{SELF}.*?减易伤",
        rf"{UP}.*?{SELF}.*?(抗性|抗性值)",
        rf"(抗性|抗性值)(?:{SEP}(?:攻击|防御|速度|法术|魔法))*?各{UP}{LEVEL}",
    ],
    "buf_acc_up": [
        rf"{SELF}.*?命中率.*?{UP}",
        rf"{UP}.*?{SELF}.*?命中率",
        rf"命中率(?:{SEP}(?:暴击率|攻击|防御|速度|抗性|法术|魔法))*?各{UP}{LEVEL}",
    ],
    "buf_crit_up": [
        rf"{SELF}.*?(暴击|暴击率|会心).*?{UP}",
        rf"(必定暴击|命中时必定暴击)",
        rf"{UP}.*?{SELF}.*?(暴击|暴击率|会心)",
        rf"暴击率(?:{SEP}(?:命中率|攻击|防御|速度|抗性|法术|魔法))*?各{UP}{LEVEL}",
    ],
    "buf_heal": [
        rf"(回复|治疗|恢复).*?({SELF}|自身体力|自身HP|自身生命|自身最大血量)",
        r"给对手造成伤害的\s*1/2\s*回复",
        r"(?:[一二三四五六七八九十]|\d+)\s*回合内.*?每回合.*?(回复|恢复)",
    ],
    "buf_shield": [
        r"护盾|护体|结界",
        r"(所受|受到).*(法术|物理)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减)(?!.*敌方)",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)|庇护|保护",
    ],
    "buf_purify": [
        r"净化",
        rf"(清除|消除|解除|去除|移除).*?{SELF}.*?(负面|异常|减益|不良|状态)",
        rf"(将|把).*?{SELF}.*?(负面|异常|减益).*?(转移|移交).*?{ENEMY}",
    ],
    "buf_immunity": [
        r"免疫(异常|控制|不良)状态?",
        r"([一二三四五六七八九十]+|\d+)\s*回合.*?免疫.*?(异常|控制|不良)",
    ],
}

DEBUFF_PATTERNS: Dict[str, List[str]] = {
    "deb_atk_down": [
        rf"(?:{ENEMY}.*?)?攻击{DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?攻击{LEVEL}",
        rf"攻击(?:{SEP}(?:防御|速度|法术|魔法|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_mag_down": [
        rf"(?:{ENEMY}.*?)?(法术|魔法){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(法术|魔法){LEVEL}",
        rf"(法术|魔法)(?:{SEP}(?:攻击|防御|速度|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_def_down": [
        rf"(?:{ENEMY}.*?)?(防御|防御力){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(防御|防御力){LEVEL}",
        rf"(防御|防御力)(?:{SEP}(?:攻击|法术|魔法|速度|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_res_down": [
        rf"(?:{ENEMY}.*?)?(抗性|抗性值){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(抗性|抗性值){LEVEL}",
        rf"(抗性|抗性值)(?:{SEP}(?:攻击|防御|速度|法术|魔法|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_spd_down": [
        rf"(?:{ENEMY}.*?)?速度{DOWN}{LEVEL}|减速",
        rf"{DOWN}.*?{ENEMY}.*?速度{LEVEL}",
        rf"速度(?:{SEP}(?:攻击|防御|法术|魔法|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_acc_down": [
        rf"(?:{ENEMY}.*?)?命中率{DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?命中率{LEVEL}",
        rf"命中率(?:{SEP}(?:攻击|防御|速度|法术|魔法|抗性))*?各{DOWN}{LEVEL}",
    ],
    "deb_stun":           [r"眩晕|昏迷"],
    "deb_bind":           [r"束缚|禁锢"],
    "deb_sleep":          [r"睡眠"],
    "deb_freeze":         [r"冰冻"],
    "deb_confuse_seal":   [r"混乱|封印|禁技|无法使用技能|禁止使用技能|不能使用物理攻击|禁用物理攻击"],
    "deb_suffocate":      [r"窒息"],
    "deb_dot":            [r"流血|中毒|灼烧|燃烧|腐蚀|灼伤"],
    "deb_dispel": [
        rf"(消除|驱散|清除).*?{ENEMY}.*?(增益|强化|状态)",
        rf"(消除|清除).*?{ENEMY}.*?(加|提升).*?(攻|攻击|法术|魔法|防御|速度).*(状态|效果)",
        r"消除对方所有增益效果",
    ],
}

SPECIAL_PATTERNS: Dict[str, List[str]] = {
    "util_first":        [r"先手|先制"],
    "util_multi":        [r"多段|连击|(\d+)[-~–](\d+)次|[二两三四五六七八九十]+连"],
    "util_pp_drain": [
        r"扣\s*PP",
        rf"(随机)?减少.*?{ENEMY}.*?(所有)?技能.*?(使用)?次数{ONE_OR_TWO}?次",
        r"(技能|使用)次数.*?减少",
        r"使用次数.*?减少",
        r"降(低)?技能次数",
    ],
    "util_reflect":      [r"反击|反伤|反弹|反馈给对手|反射伤害"],
    "util_charge_next":  [r"伤害加倍|威力加倍|威力倍增|下一回合.*?(伤害|威力).*?加倍|下回合.*?必定暴击|命中时必定暴击|蓄力.*?(强力|加倍|倍增)"],
    "util_penetrate":    [r"无视防御|破防|穿透(护盾|防御)"],
}

# ================
# 审计/修复配置
# ================

TAG_AUDIT_ENABLE: bool = os.getenv("TAG_AUDIT_ENABLE", "1") not in {"0", "false", "False"}
TAG_AUDIT_DIR: str = os.getenv("TAG_AUDIT_DIR", "storage/tag_audit").strip()
# 写库策略：ai | regex | repair_union
TAG_WRITE_STRATEGY: str = os.getenv("TAG_WRITE_STRATEGY", "ai").strip().lower()
# repair_union 是否做关键词二次验证（降低误合并）
TAG_AI_REPAIR_VERIFY: bool = os.getenv("TAG_AI_REPAIR_VERIFY", "1") not in {"0", "false", "False"}
# 是否额外请求自由候选新标签短语
TAG_FREEFORM_ENABLE: bool = os.getenv("TAG_FREEFORM_ENABLE", "1") not in {"0", "false", "False"}

# 关键词库（用于验证 AI-only 标签是否在文本中有明显线索；可逐步补齐）
KEYWORDS_FOR_CODE: Dict[str, List[str]] = {
    "buf_atk_up": ["攻击 提升", "攻击 上升", "攻击 增加"],
    "buf_mag_up": ["法术 提升", "魔法 提升", "法术 上升", "魔法 上升"],
    "buf_spd_up": ["加速", "速度 提升", "迅捷", "敏捷"],
    "buf_def_up": ["防御 提升", "护甲", "硬化", "铁壁"],
    "buf_res_up": ["抗性 提升", "易伤 降低", "抗性 增加"],
    "buf_acc_up": ["命中率 提升", "命中 提升"],
    "buf_crit_up": ["必定暴击", "暴击率 提升", "会心"],
    "buf_heal": ["治疗", "回复", "恢复"],
    "buf_shield": ["护盾", "结界", "减伤", "庇护", "保护"],
    "buf_purify": ["净化", "清除 负面", "解除 异常"],
    "buf_immunity": ["免疫 异常", "免疫 控制"],

    "deb_atk_down": ["攻击 降低"],
    "deb_mag_down": ["法术 降低", "魔法 降低"],
    "deb_def_down": ["防御 降低"],
    "deb_res_down": ["抗性 降低"],
    "deb_spd_down": ["减速", "速度 降低"],
    "deb_acc_down": ["命中率 降低", "命中 降低"],
    "deb_stun": ["眩晕", "昏迷"],
    "deb_bind": ["束缚", "禁锢"],
    "deb_sleep": ["睡眠"],
    "deb_freeze": ["冰冻"],
    "deb_confuse_seal": ["封印", "禁技", "无法使用技能", "禁止使用技能"],
    "deb_suffocate": ["窒息"],
    "deb_dot": ["流血", "中毒", "灼烧", "燃烧", "腐蚀", "灼伤"],
    "deb_dispel": ["驱散 对方", "消除 对方 增益"],

    "util_first": ["先手", "先制"],
    "util_multi": ["多段", "连击", "二连", "三连", "四连"],
    "util_pp_drain": ["扣 PP", "减少 技能 使用 次数", "降 技能 次数"],
    "util_reflect": ["反击", "反伤", "反弹", "反射 伤害"],
    "util_charge_next": ["伤害 加倍", "威力 加倍", "下一回合 加倍", "蓄力 加倍"],
    "util_penetrate": ["无视 防御", "穿透 防御", "穿透 护盾", "破防"],
}

# ======================
# 工具
# ======================

def _ensure_dir(path: str) -> None:
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass

def _today_str() -> str:
    return datetime.utcnow().strftime("%Y%m%d")

def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for s in (monster.skills or []):
        if getattr(s, "name", None):
            parts.append(str(s.name))
        if getattr(s, "description", None):
            parts.append(str(s.description))
    return " ".join(parts).strip()

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    hp      = float(getattr(monster, "hp", 0) or 0)
    speed   = float(getattr(monster, "speed", 0) or 0)
    attack  = float(getattr(monster, "attack", 0) or 0)
    defense = float(getattr(monster, "defense", 0) or 0)
    magic   = float(getattr(monster, "magic", 0) or 0)
    resist  = float(getattr(monster, "resist", 0) or 0)
    return hp, speed, attack, defense, magic, resist

def _hit_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)

def _hit(p: str, text: str) -> bool:
    return re.search(p, text) is not None

def _detect(pattern_map: Dict[str, List[str]], text: str) -> List[str]:
    out: List[str] = []
    for code, pats in pattern_map.items():
        if _hit_any(pats, text):
            out.append(code)
    return out

def _flatten_grouped(g: Dict[str, List[str]]) -> List[str]:
    flat: List[str] = []
    for cat in ("buff", "debuff", "special"):
        flat.extend(g.get(cat, []))
    seen: Set[str] = set()
    out: List[str] = []
    for t in flat:
        if t in ALL_CODES and t not in seen:
            seen.add(t)
            out.append(t)
    return out

def _find_keyword_snippet(code: str, text: str) -> Tuple[bool, Optional[str]]:
    """
    在技能文本里按 KEYWORDS_FOR_CODE 做一次宽松验证；
    命中则返回（True, 片段），否则（False, None）
    """
    kws = KEYWORDS_FOR_CODE.get(code, [])
    if not text or not kws:
        return False, None
    for kw in kws:
        # 允许“词+空白若干+词”的松匹配
        pattern = re.escape(kw).replace("\\ ", r"\s*")
        m = re.search(pattern, text)
        if m:
            i = max(0, m.start() - 18)
            j = min(len(text), m.end() + 18)
            return True, text[i:j]
    return False, None

# ======================
# 内置 AI 识别（OpenAI 兼容 DeepSeek）—— 固定标签集合
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
    "如果你认为“固定标签集合”不够表达关键机制，请给出最多5个短语建议作为未来可能的新标签候选。"
    "输出严格 JSON：{\"candidates\": [\"短语1\", \"短语2\", ...]}；短语必须 <= 8 个汉字。"
)

def _build_ai_payload(text: str) -> Dict[str, Any]:
    base_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]

    system = AI_SYSTEM_PROMPT.format(
        buff_codes=", ".join(sorted(ALL_BUFF_CODES)),
        debuff_codes=", ".join(sorted(ALL_DEBUFF_CODES)),
        special_codes=", ".join(sorted(ALL_SPECIAL_CODES)),
    )
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": f"技能文本：\n{txt}\n\n请输出 JSON。"},
        ],
    }
    return {"url": base_url, "payload": payload}

def _build_freeform_payload(text: str) -> Dict[str, Any]:
    base_url = os.getenv("DEEPSEEK_API_URL", "https://api.deepseek.com/chat/completions").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-chat").strip() or "deepseek-chat"
    txt = (text or "").strip()
    if len(txt) > 8000:
        txt = txt[:8000]
    payload = {
        "model": model,
        "temperature": 0,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": FREEFORM_SYSTEM_PROMPT},
            {"role": "user", "content": f"技能文本：\n{txt}\n\n请只输出 JSON。"},
        ],
    }
    return {"url": base_url, "payload": payload}

def _validate_ai_result(obj: Any) -> Dict[str, List[str]]:
    def _pick(arr: Any, allowed: Set[str]) -> List[str]:
        if not isinstance(arr, list):
            return []
        seen: Set[str] = set()
        out: List[str] = []
        for x in arr:
            if isinstance(x, str) and x in allowed and x not in seen:
                seen.add(x)
                out.append(x)
        return sorted(out)

    buff = _pick(obj.get("buff", []), ALL_BUFF_CODES) if isinstance(obj, dict) else []
    debuff = _pick(obj.get("debuff", []), ALL_DEBUFF_CODES) if isinstance(obj, dict) else []
    special = _pick(obj.get("special", []), ALL_SPECIAL_CODES) if isinstance(obj, dict) else []
    return {"buff": buff, "debuff": debuff, "special": special}

def _validate_freeform(obj: Any) -> List[str]:
    if not isinstance(obj, dict):
        return []
    arr = obj.get("candidates", [])
    out: List[str] = []
    seen: Set[str] = set()
    if isinstance(arr, list):
        for x in arr:
            if isinstance(x, str):
                s = x.strip()
                if not s or len(s) > 16:  # 稍放宽
                    continue
                if s not in seen:
                    seen.add(s)
                    out.append(s)
    return out[:5]

@lru_cache(maxsize=8192)
def _ai_classify_cached(text: str) -> Dict[str, List[str]]:
    """
    直接调用 DeepSeek/OpenAI 兼容接口。
    - 未安装 httpx / 未配置密钥 / 调用错误将抛出 RuntimeError。
    - 使用 LRU 缓存避免重复费用。
    """
    if not _HAS_HTTPX:
        raise RuntimeError("AI 标签识别需要 httpx，请先安装依赖：pip install httpx")

    key = os.getenv("DEEPSEEK_API_KEY", "sk-7a1c5bc1d84240dcbb754ca169dbf741").strip()
    if not key:
        raise RuntimeError("缺少 DEEPSEEK_API_KEY，无法进行 AI 标签识别")

    conf = _build_ai_payload(text)
    url: str = conf["url"]
    payload: Dict[str, Any] = conf["payload"]
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=20) as client:
        resp = client.post(url, headers=headers, json=payload)
    resp.raise_for_status()
    data = resp.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
    return _validate_ai_result(obj)

def _ai_freeform_candidates(text: str) -> List[str]:
    """
    可选的自由候选新标签短语（用于完善词表/正则），失败静默返回空。
    """
    if not TAG_FREEFORM_ENABLE:
        return []
    try:
        if not _HAS_HTTPX:
            return []
        key = os.getenv("DEEPSEEK_API_KEY", "").strip()
        if not key:
            return []
        conf = _build_freeform_payload(text)
        url: str = conf["url"]
        payload: Dict[str, Any] = conf["payload"]
        headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
        with httpx.Client(timeout=20) as client:
            resp = client.post(url, headers=headers, json=payload)
        resp.raise_for_status()
        data = resp.json()
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        obj = json.loads(content) if isinstance(content, str) and content.strip().startswith("{") else {}
        return _validate_freeform(obj)
    except Exception:
        return []

def ai_classify_text(text: str) -> Dict[str, List[str]]:
    """
    对任意技能文本进行 AI 识别（独立接口）。
    失败将抛 RuntimeError（不回落正则）。
    """
    txt = (text or "").strip()
    if not txt:
        return {"buff": [], "debuff": [], "special": []}
    return _ai_classify_cached(txt)

def ai_suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    """
    对单个 Monster 的技能文本进行 AI 识别（独立接口）。
    失败将抛 RuntimeError（不回落正则）。
    """
    text = _text_of_skills(monster)
    return ai_classify_text(text)

# ======================
# 审计 / 修复（核心）
# ======================

def _build_diff(ai_g: Dict[str, List[str]], re_g: Dict[str, List[str]]) -> Dict[str, Any]:
    diff: Dict[str, Any] = {"by_cat": {}, "overall": {}}
    total_ai, total_re = set(), set()
    for cat in ("buff", "debuff", "special"):
        ai_set = set(ai_g.get(cat, []))
        re_set = set(re_g.get(cat, []))
        total_ai |= ai_set
        total_re |= re_set
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

def _repair_union(text: str, re_flat: List[str], ai_flat: List[str]) -> Tuple[List[str], Dict[str, Any]]:
    """
    以 regex 结果为基，合并“通过验证的 AI-only 标签”。
    返回 (merged_tags, verify_report)
    """
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
    return sorted(base), verified

def _write_audit(monster: Monster, text: str,
                 ai_g: Dict[str, List[str]], re_g: Dict[str, List[str]],
                 chosen: List[str], strategy: str,
                 repair_verify: Optional[Dict[str, Any]] = None,
                 freeform_candidates: Optional[List[str]] = None) -> None:
    if not TAG_AUDIT_ENABLE:
        return
    try:
        _ensure_dir(TAG_AUDIT_DIR)
        ts = datetime.utcnow().isoformat()
        diff = _build_diff(ai_g, re_g)
        record = {
            "timestamp": ts,
            "monster": {"id": getattr(monster, "id", None), "name": getattr(monster, "name", None)},
            "strategy": strategy,
            "skills_text_len": len(text or ""),
            "ai_grouped": ai_g,
            "regex_grouped": re_g,
            "diff": diff,
            "chosen_flat": chosen,
            "repair_verify": repair_verify or {},
            "freeform_candidates": freeform_candidates or [],
        }
        # 1) 按日汇总 JSONL
        dayfile = os.path.join(TAG_AUDIT_DIR, f"audit_{_today_str()}.jsonl")
        with open(dayfile, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        # 2) 每怪物快照
        monfile = os.path.join(TAG_AUDIT_DIR, f"mon_{getattr(monster,'id','unknown')}_latest.json")
        with open(monfile, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception:
        # 审计失败不影响主流程
        pass

# ======================
# AI 建议（拍平）—— 已融入审计/修复/策略
# ======================

def ai_suggest_tags_for_monster(monster: Monster) -> List[str]:
    """
    AI 版拍平结果（兼容原接口）：
      - 先 AI 分类
      - 与正则分组对比，写入审计 JSON
      - 根据 TAG_WRITE_STRATEGY 选择最终返回的一维标签
        * ai（默认）：仅 AI
        * regex：仅正则
        * repair_union：regex ∪（验证通过的 AI-only）
      - 可选 freeform 候选短语（不影响返回）
    """
    text = _text_of_skills(monster)
    # 1) 结果获取
    ai_g = ai_classify_text(text)
    re_g = suggest_tags_grouped(monster)
    ai_flat = _flatten_grouped(ai_g)
    re_flat = _flatten_grouped(re_g)

    # 2) 策略
    strategy = TAG_WRITE_STRATEGY if TAG_WRITE_STRATEGY in {"ai", "regex", "repair_union"} else "ai"
    repair_verify = {}
    if strategy == "ai":
        chosen = ai_flat
    elif strategy == "regex":
        chosen = re_flat
    else:
        chosen, repair_verify = _repair_union(text, re_flat, ai_flat)

    # 3) 可选自由候选短语（完善词表/正则）
    freeform_candidates = _ai_freeform_candidates(text) if TAG_FREEFORM_ENABLE else []

    # 4) 审计落盘
    _write_audit(
        monster, text, ai_g, re_g, chosen, strategy,
        repair_verify=repair_verify, freeform_candidates=freeform_candidates
    )
    return chosen

# ======================
# 批量 AI 打标签：进度注册表（内存）
# ======================

@dataclass
class BatchJobState:
    job_id: str
    total: int
    done: int = 0
    failed: int = 0
    running: bool = True
    canceled: bool = False
    errors: List[Dict[str, Any]] = field(default_factory=list)  # {"id": int, "error": str}
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
            "errors": self.errors[-20:],  # 只返回最近 20 条
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
                    self._jobs.pop(k, None)
                    removed += 1
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
    启动后台线程，按顺序对给定 monster id 列表进行 AI 打标签并落库。
    - 返回 job_id，前端可轮询 /tags/ai_batch/{job_id} 获取进度。
    - 内部已自动做审计与（可选）修复合并（取决于 TAG_WRITE_STRATEGY）。
    """
    ids = [int(x) for x in (ids or []) if isinstance(x, (int, str)) and str(x).isdigit()]
    ids = list(dict.fromkeys(ids))  # 去重保序
    st = _registry.create(total=len(ids))
    job_id = st.job_id

    def _worker(_ids: List[int], _job_id: str):
        from .monsters_service import upsert_tags  # 延迟导入，避免循环依赖
        try:
            for mid in _ids:
                cur = _registry.get(_job_id)
                if cur and cur.canceled:
                    _registry.update(_job_id, running=False)
                    return
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

                        # 关键：此处调用已具备审计/修复策略的 AI 接口
                        tags = ai_suggest_tags_for_monster(m)  # 失败抛出，外层捕获
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
# 对外（默认路径）：三类建议 / 一维建议 / 信号（正则）
# ※ 定位与派生已迁入 derive_service；本模块仅保留标签相关逻辑。
# ======================

def suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    """
    默认：仅用正则，返回固定 code 三类标签。
    """
    text = _text_of_skills(monster)
    buff = set(_detect(BUFF_PATTERNS, text))
    debuff = set(_detect(DEBUFF_PATTERNS, text))
    special = set(_detect(SPECIAL_PATTERNS, text))
    return {
        "buff": sorted(buff),
        "debuff": sorted(debuff),
        "special": sorted(special),
    }

def suggest_tags_for_monster(monster: Monster) -> List[str]:
    """
    默认：正则版拍平（用于 Monster.tags 存库）。
    """
    g = suggest_tags_grouped(monster)
    return _flatten_grouped(g)

def extract_signals(monster: Monster) -> Dict[str, object]:
    """
    v2 细粒度信号（仅保留派生所需；供 derive_service 使用）
    """
    text = _text_of_skills(monster)
    g = suggest_tags_grouped(monster)  # 使用默认正则标签
    deb = set(g["debuff"]); buf = set(g["buff"]); util = set(g["special"])

    # 进攻
    crit_up = ("buf_crit_up" in buf) or _hit_any([r"必定暴击", r"命中时必定暴击"], text)
    ignore_def = ("util_penetrate" in util) or _hit_any([r"无视防御", r"穿透(护盾|防御)"], text)
    armor_break = _hit(r"破防", text)
    def_down = ("deb_def_down" in deb)
    res_down = ("deb_res_down" in deb)
    mark = _hit_any([r"标记", r"易伤", r"(暴|曝)露", r"破绽"], text)
    has_multi_hit = ("util_multi" in util)

    # 生存
    heal = ("buf_heal" in buf) or _hit(r"(回复|治疗|恢复)", text)
    shield = _hit(r"护盾|庇护|保护|结界|护体", text)
    dmg_reduce = _hit_any([
        r"(所受|受到).*(法术|物理)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减(?!益))",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)"
    ], text)
    cleanse_self = ("buf_purify" in buf)
    immunity = ("buf_immunity" in buf) or _hit(r"免疫(异常|控制|不良)", text)
    life_steal = _hit_any([r"吸血", r"造成伤害.*(回复|恢复).*(自身|自我|HP)"], text)
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
    extra_turn = _hit_any([
        r"(追加|额外|再度|再动|再次|连续).*(行动|回合)",
        r"(立即|立刻|马上).*(再次)?行动",
        r"再行动(一次)?|额外回合"
    ], text)
    action_bar = _hit_any([
        r"行动条|行动值|先手值",
        r"(推进|提升|增加|降低|减少).*行动(条|值)",
        r"(推条|拉条)"
    ], text)

    # 压制
    pp_hits = 0
    for p in SPECIAL_PATTERNS["util_pp_drain"]:
        pp_hits += len(re.findall(p, text))
    if pp_hits == 0 and ("util_pp_drain" in util):
        pp_hits = 1
    dispel_enemy = ("deb_dispel" in deb)
    skill_seal = _hit_any([r"封印", r"禁技", r"无法使用技能", r"禁止使用技能"], text)
    buff_steal = _hit_any([r"(偷取|窃取|夺取).*(增益|强化|护盾)"], text)
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
# 兼容转发（定位 / 派生）—— 请尽快把调用方迁到 derive_service
# ======================

def infer_role_for_monster(monster: Monster) -> str:
    """
    兼容函数：已迁入 derive_service。
    请改用：from .derive_service import infer_role_for_monster
    """
    from .derive_service import infer_role_for_monster as _infer
    return _infer(monster)

def derive(monster: Monster) -> Dict[str, int]:
    """
    兼容函数：已迁入 derive_service。
    请改用：from .derive_service import compute_derived_out
    """
    from .derive_service import compute_derived_out
    return compute_derived_out(monster)

__all__ = [
    # 标签映射
    "BUFF_CANON", "DEBUFF_CANON", "SPECIAL_CANON",
    "CODE2CN", "CN2CODE",
    # 默认（正则）接口
    "suggest_tags_grouped", "suggest_tags_for_monster",
    "extract_signals",
    # 兼容（转发到 derive_service）
    "infer_role_for_monster", "derive",
    # AI 独立接口（单个/文本）
    "ai_classify_text", "ai_suggest_tags_grouped", "ai_suggest_tags_for_monster",
    # 批量 AI 打标签（进度）
    "start_ai_batch_tagging", "get_ai_batch_progress", "cancel_ai_batch", "cleanup_finished_jobs",
]