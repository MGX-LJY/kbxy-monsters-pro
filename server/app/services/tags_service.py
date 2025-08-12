# server/app/services/tags_service.py
from __future__ import annotations
import re
from typing import List, Tuple

from ..models import Monster

# 元素别名 -> 规范值
_ELEMENT_ALIAS = {
    "金系": "金", "木系": "木", "水系": "水", "火系": "火", "土系": "土",
    "风系": "风", "雷系": "雷", "冰系": "冰", "毒系": "毒", "妖系": "妖",
    "光系": "光", "暗系": "暗", "音系": "音",
}
def normalize_element(val: str) -> str:
    s = (val or "").strip()
    return _ELEMENT_ALIAS.get(s, s)

# 关键词
_CTRL = [r"眩晕", r"昏迷", r"束缚", r"窒息", r"冰冻", r"睡眠", r"混乱", r"封印", r"禁锢"]
_SLOW_ACC = [r"降速", r"速度下降", r"命中下降", r"降低命中"]
_MULTI = [r"多段", r"连击", r"2~3次", r"3~6次", r"三连"]
_CRIT_IGN = [r"暴击", r"必中", r"无视防御", r"破防"]
_SURVIVE = [r"回复", r"治疗", r"减伤", r"免疫", r"护盾"]
_FIRST = [r"先手", r"先制"]
_SPEED_UP = [r"加速", r"提速", r"速度提升"]
_PP = [
    r"能量消除", r"扣\s*PP", r"消耗\s*PP", r"减少.*技能.*使用次数", r"减少技能次数", r"降技能次数",
]

def _has_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)

def _skills_text(m: Monster) -> str:
    parts: List[str] = [m.name_final or "", m.element or "", m.role or ""]
    for s in (m.skills or []):
        if s.name: parts.append(s.name)
        if s.description: parts.append(s.description)
    return " ".join(parts)

def suggest_tags_for_monster(m: Monster) -> List[str]:
    """
    依据原始六维 + 技能文本给出标签（不落库，纯建议列表）
    """
    hp, spd, atk = float(m.hp or 0), float(m.speed or 0), float(m.attack or 0)
    defe, mag, resi = float(m.defense or 0), float(m.magic or 0), float(m.resist or 0)
    txt = _skills_text(m)

    tags: List[str] = []
    # 基于六维
    if spd >= 110: tags.append("高速")
    if atk >= 115: tags.append("强攻")
    if hp >= 115 or (defe + mag) / 2 >= 105 or resi >= 110: tags.append("耐久")

    # 基于文本
    if _has_any(_FIRST, txt): tags.append("先手")
    if _has_any(_MULTI, txt): tags.append("多段")
    if _has_any(_CTRL, txt): tags.append("控制")
    if _has_any(_PP, txt): tags.append("PP压制")
    if _has_any(_SURVIVE, txt): tags.append("回复/增防")

    # 去重并限长
    seen = set()
    out: List[str] = []
    for t in tags:
        if t and t not in seen:
            out.append(t); seen.add(t)
        if len(out) >= 8:
            break
    return out

def infer_role_for_monster(m: Monster) -> str:
    hp, spd, atk = float(m.hp or 0), float(m.speed or 0), float(m.attack or 0)
    defe, mag, resi = float(m.defense or 0), float(m.magic or 0), float(m.resist or 0)
    txt = _skills_text(m)

    offensive  = atk >= 115 or _has_any(_CRIT_IGN + _MULTI, txt)
    controlish = _has_any(_CTRL + _SLOW_ACC, txt)
    supportish = _has_any(_SURVIVE + _SPEED_UP, txt)
    tanky      = hp >= 115 or resi >= 115

    if offensive and not controlish and not supportish:
        return "主攻"
    if controlish and not offensive:
        return "控制"
    if supportish and not offensive:
        return "辅助"
    if tanky and not offensive:
        return "坦克"
    return "通用"

def infer_role_and_tags_for_monster(m: Monster) -> Tuple[str, List[str]]:
    return infer_role_for_monster(m), suggest_tags_for_monster(m)