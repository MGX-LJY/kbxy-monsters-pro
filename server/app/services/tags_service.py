from __future__ import annotations

import re
from typing import List, Set, Dict, Tuple

from ..models import Monster

# ===== 关键词词典 =====
CTRL_PATTERNS = [r"眩晕", r"昏迷", r"束缚", r"窒息", r"冰冻", r"睡眠", r"混乱", r"封印", r"禁锢"]
SLOW_OR_ACCURACY_DOWN = [r"降速", r"速度下降", r"命中下降", r"降低命中"]
MULTI_HIT = [r"多段", r"连击", r"2~3次", r"3~6次", r"三连"]
CRIT_OR_IGNORE = [r"暴击", r"必中", r"无视防御", r"破防"]
SURVIVE_BUFF = [r"回复", r"治疗", r"减伤", r"免疫", r"护盾"]
FIRST_STRIKE = [r"先手", r"先制"]
SPEED_UP = [r"加速", r"提速", r"速度提升"]

# 重要：去掉“能量消除”，只保留能明确表达“降低对手技能次数 / 扣PP”的词
PP_PRESSURE = [
    r"扣PP",
    r"减少.*技能.*次数",
    r"技能.*次数.*减少",
    r"减少.*使用次数",
    r"使用次数.*减少",
    r"降技能次数",
]

# 一些常用标签名（与前端展示一致）
TAG_FAST = "高速"
TAG_OFFENSE = "强攻"
TAG_TANKY = "耐久"
TAG_FIRST = "先手"
TAG_MULTI = "多段"
TAG_CTRL = "控制"
TAG_PP = "PP压制"
TAG_SUPPORT = "回复/增防"


def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for s in (monster.skills or []):
        if s.name:
            parts.append(s.name)
        if s.description:
            parts.append(s.description)
    return " ".join(parts)


def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    """
    从列（hp/speed/attack/defense/magic/resist）读取；为 0/None 时，回退 explain_json.raw_stats。
    """
    ex = monster.explain_json or {}
    raw = ex.get("raw_stats") or {}

    def pick(col_val, raw_key):
        if col_val is not None and float(col_val) != 0.0:
            return float(col_val)
        v = raw.get(raw_key)
        return float(v) if v is not None else 0.0

    hp = pick(monster.hp, "hp")
    speed = pick(monster.speed, "speed")
    attack = pick(monster.attack, "attack")
    defense = pick(monster.defense, "defense")
    magic = pick(monster.magic, "magic")
    resist = pick(monster.resist, "resist")
    return hp, speed, attack, defense, magic, resist


def _has_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _count_any(patterns: List[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text))


def suggest_tags_for_monster(monster: Monster) -> List[str]:
    """
    统一的自动贴标签：基于六维 + 技能文本。
    只产出“玩法相关”标签（不会生成元素/定位的同义标签）。
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)

    tags: List[str] = []

    # 数值向
    if speed >= 110:
        tags.append(TAG_FAST)
    if attack >= 115:
        tags.append(TAG_OFFENSE)
    if hp >= 115 or (defense + magic) / 2 >= 105 or resist >= 110:
        tags.append(TAG_TANKY)

    # 文本向
    if _has_any(FIRST_STRIKE, text):
        tags.append(TAG_FIRST)
    if _has_any(MULTI_HIT, text):
        tags.append(TAG_MULTI)
    if _has_any(CTRL_PATTERNS, text):
        tags.append(TAG_CTRL)
    if _has_any(PP_PRESSURE, text):
        tags.append(TAG_PP)
    if _has_any(SURVIVE_BUFF, text):
        tags.append(TAG_SUPPORT)

    # 去重并稳定
    seen: Set[str] = set()
    uniq: List[str] = []
    for t in tags:
        if t and t not in seen:
            uniq.append(t)
            seen.add(t)
    return uniq


def infer_role_for_monster(monster: Monster) -> str:
    """
    极简定位规则：输出/控制/辅助/坦克/通用
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)

    offensive = attack >= 115 or _has_any(CRIT_OR_IGNORE + MULTI_HIT, text)
    controlish = _has_any(CTRL_PATTERNS + SLOW_OR_ACCURACY_DOWN, text)
    supportish = _has_any(SURVIVE_BUFF + SPEED_UP, text)
    tanky = hp >= 115 or resist >= 115

    if offensive and not controlish and not supportish:
        return "主攻"
    if controlish and not offensive:
        return "控制"
    if supportish and not offensive:
        return "辅助"
    if tanky and not offensive:
        return "坦克"
    return "通用"


def extract_signals(monster: Monster) -> Dict[str, object]:
    """
    为派生五维准备的一份“信号”，结合技能文本 + 已有标签：
    - ctrl_count / slow_or_accuracy / has_multi_hit / has_crit_ignore / has_survive_buff / first_strike / speed_up
    - pp_hits：PP相关关键词出现次数；若已有 'PP压制' 标签，至少按 1 计
    """
    text = _text_of_skills(monster)
    tag_names = {t.name for t in (monster.tags or []) if getattr(t, "name", None)}

    ctrl_count = _count_any(CTRL_PATTERNS, text)
    slow_or_accuracy = _has_any(SLOW_OR_ACCURACY_DOWN, text)

    has_multi_hit = _has_any(MULTI_HIT, text) or ("多段" in tag_names)
    has_crit_ignore = _has_any(CRIT_OR_IGNORE, text) or ("强攻" in tag_names)
    has_survive_buff = _has_any(SURVIVE_BUFF, text) or ("回复/增防" in tag_names)
    first_strike = _has_any(FIRST_STRIKE, text) or ("先手" in tag_names)
    speed_up = _has_any(SPEED_UP, text) or ("高速" in tag_names)

    pp_hits = 0
    for p in PP_PRESSURE:
        pp_hits += len(re.findall(p, text))
    if (pp_hits == 0) and ("PP压制" in tag_names):
        pp_hits = 1  # 有“PP压制”标签时，至少按一次记分

    return {
        "ctrl_count": int(ctrl_count),
        "slow_or_accuracy": bool(slow_or_accuracy),
        "has_multi_hit": bool(has_multi_hit),
        "has_crit_ignore": bool(has_crit_ignore),
        "has_survive_buff": bool(has_survive_buff),
        "first_strike": bool(first_strike),
        "speed_up": bool(speed_up),
        "pp_hits": int(pp_hits),
    }


__all__ = [
    "suggest_tags_for_monster",
    "infer_role_for_monster",
    "extract_signals",
]