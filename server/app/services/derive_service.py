# server/app/services/derive_service.py
from __future__ import annotations

import re
from typing import Dict, List, Tuple
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import Monster, MonsterDerived

# ========= 关键词规则 =========
CTRL_PATTERNS = [r"眩晕", r"昏迷", r"束缚", r"窒息", r"冰冻", r"睡眠", r"混乱", r"封印", r"禁锢"]
SLOW_OR_ACCURACY_DOWN = [r"降速", r"速度下降", r"命中下降", r"降低命中"]
MULTI_HIT = [r"多段", r"连击", r"2~3次", r"3~6次", r"三连"]
CRIT_OR_IGNORE = [r"暴击", r"必中", r"无视防御", r"破防"]
SURVIVE_BUFF = [r"回复", r"治疗", r"减伤", r"免疫", r"护盾"]
FIRST_STRIKE = [r"先手", r"先制"]
SPEED_UP = [r"加速", r"提速", r"速度提升"]
# 补充 “PP压制” / “消耗PP” 等写法（大小写不敏感）
PP_PRESSURE = [
    r"PP压制", r"能量消除", r"扣PP", r"减少技能次数", r"降技能次数",
    r"消耗\s*PP", r"耗\s*PP", r"\bPP\b"
]

def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for s in (monster.skills or []):
        if s.name: parts.append(s.name)
        if s.description: parts.append(s.description)
    return " ".join(parts)

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    """
    只认列字段（hp/speed/attack/defense/magic/resist），
    若为 0/None，再兜底 explain_json.raw_stats（兼容旧备份）。
    """
    ex = monster.explain_json or {}
    raw = ex.get("raw_stats") or {}

    def pick(col_val, raw_key):
        if col_val is not None and float(col_val) != 0.0:
            return float(col_val)
        v = raw.get(raw_key)
        return float(v) if v is not None else 0.0

    hp      = pick(monster.hp,      "hp")
    speed   = pick(monster.speed,   "speed")
    attack  = pick(monster.attack,  "attack")
    defense = pick(monster.defense, "defense")
    magic   = pick(monster.magic,   "magic")
    resist  = pick(monster.resist,  "resist")
    return hp, speed, attack, defense, magic, resist

def _has_any(patterns: List[str], text: str) -> bool:
    return any(re.search(p, text, flags=re.I) for p in patterns)

def _count_any(patterns: List[str], text: str) -> int:
    return sum(1 for p in patterns if re.search(p, text, flags=re.I))

def compute_derived(monster: Monster) -> Dict[str, float]:
    """计算派生五维（float）。"""
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)

    offense = 0.5 * attack + 0.2 * speed \
              + (10.0 if _has_any(MULTI_HIT, text) else 0.0) \
              + (12.0 if _has_any(CRIT_OR_IGNORE, text) else 0.0)

    survive = 0.4 * hp + 0.3 * defense + 0.2 * resist \
              + (10.0 if _has_any(SURVIVE_BUFF, text) else 0.0)

    control = 12.0 * _count_any(CTRL_PATTERNS, text) \
              + (8.0 if _has_any(SLOW_OR_ACCURACY_DOWN, text) else 0.0) \
              + 0.1 * speed

    tempo = speed \
            + (15.0 if _has_any(FIRST_STRIKE, text) else 0.0) \
            + (8.0 if _has_any(SPEED_UP, text) else 0.0)

    # PP 压制出现频次
    pp_hits = 0
    for p in PP_PRESSURE:
        pp_hits += len(re.findall(p, text, flags=re.I))
    pp_pressure = 20.0 * (1 if pp_hits > 0 else 0) + 5.0 * pp_hits

    return {
        "offense": float(offense),
        "survive": float(survive),
        "control": float(control),
        "tempo": float(tempo),
        "pp_pressure": float(pp_pressure),
    }

def _to_ints(d: Dict[str, float]) -> Dict[str, int]:
    return {k: int(round(float(v))) for k, v in d.items()}

def compute_derived_out(monster: Monster) -> Dict[str, int]:
    return _to_ints(compute_derived(monster))

# --------- 自动定位 & 标签 ---------
def infer_role_and_tags(monster: Monster) -> Tuple[str, List[str]]:
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)
    tags: List[str] = []

    if speed >= 110: tags.append("高速")
    if attack >= 115: tags.append("强攻")
    if hp >= 115 or (defense + magic) / 2 >= 105 or resist >= 110: tags.append("耐久")
    if _has_any(FIRST_STRIKE, text): tags.append("先手")
    if _has_any(MULTI_HIT, text): tags.append("多段")
    if _has_any(CTRL_PATTERNS, text): tags.append("控制")
    if _has_any(PP_PRESSURE, text): tags.append("PP压制")

    offensive = attack >= 115 or _has_any(CRIT_OR_IGNORE, text)
    controlish = _has_any(CTRL_PATTERNS + SLOW_OR_ACCURACY_DOWN, text)
    supportish = _has_any(SURVIVE_BUFF + SPEED_UP, text)
    tanky = hp >= 115 or resist >= 115

    if offensive and not controlish and not supportish:
        role = "主攻"
    elif controlish and not offensive:
        role = "控制"
    elif supportish and not offensive:
        role = "辅助"
    elif tanky and not offensive:
        role = "坦克"
    else:
        role = "通用"

    # 去重，限 6 个
    out, seen = [], set()
    for t in tags:
        if t not in seen:
            out.append(t); seen.add(t)
        if len(out) >= 6:
            break
    return role, out

def apply_role_tags(db: Session, monster: Monster, *, override_role_if_blank=True, merge_tags=True):
    """将推断的 role/tags 写回 monster。"""
    role, tags = infer_role_and_tags(monster)
    if override_role_if_blank and (not monster.role or not monster.role.strip()):
        monster.role = role
    if merge_tags:
        # 合并至现有标签（不覆盖）
        have = {t.name for t in (monster.tags or [])}
        need = [t for t in tags if t not in have]
        from ..services.monsters_service import upsert_tags
        if need:
            monster.tags = (monster.tags or []) + upsert_tags(db, need)

def compute_and_persist(db: Session, monster: Monster) -> MonsterDerived:
    """只写派生五维（不 commit）。"""
    vals = compute_derived_out(monster)
    md = monster.derived
    if not md:
        md = MonsterDerived(
            monster_id=monster.id,
            offense=vals["offense"],
            survive=vals["survive"],
            control=vals["control"],
            tempo=vals["tempo"],
            pp_pressure=vals["pp_pressure"],
        )
        db.add(md)
        monster.derived = md
    else:
        md.offense = vals["offense"]
        md.survive = vals["survive"]
        md.control = vals["control"]
        md.tempo = vals["tempo"]
        md.pp_pressure = vals["pp_pressure"]
    return md

def recompute_and_autolabel(db: Session, monster: Monster):
    """计算派生五维 + 自动打定位/标签（不 commit）。"""
    compute_and_persist(db, monster)
    apply_role_tags(db, monster, override_role_if_blank=True, merge_tags=True)

def recompute_all(db: Session) -> int:
    mons = db.scalars(select(Monster)).all()
    n = 0
    for m in mons:
        recompute_and_autolabel(db, m)
        n += 1
    return n

__all__ = [
    "compute_derived",
    "compute_derived_out",
    "compute_and_persist",
    "recompute_and_autolabel",
    "recompute_all",
    "infer_role_and_tags",
    "apply_role_tags",
]