# server/app/services/derive_service.py
from __future__ import annotations

import re
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived

# =========================
#  关键词规则（可按需扩充）
# =========================
CTRL_PATTERNS = [r"眩晕", r"昏迷", r"束缚", r"窒息", r"冰冻", r"睡眠", r"混乱", r"封印", r"禁锢"]
SLOW_OR_ACCURACY_DOWN = [r"降速", r"速度下降", r"命中下降", r"降低命中"]
MULTI_HIT = [r"多段", r"连击", r"2~3次", r"3~6次", r"三连"]
CRIT_OR_IGNORE = [r"暴击", r"必中", r"无视防御", r"破防"]
SURVIVE_BUFF = [r"回复", r"治疗", r"减伤", r"免疫", r"护盾"]
FIRST_STRIKE = [r"先手", r"先制"]
SPEED_UP = [r"加速", r"提速", r"速度提升"]
PP_PRESSURE = [r"能量消除", r"扣PP", r"减少技能次数", r"降技能次数"]


def _text_of_skills(monster: Monster) -> str:
    """把技能名与描述拼成一段文本，便于关键词命中。"""
    parts: List[str] = []
    for s in (monster.skills or []):
        if s.name:
            parts.append(s.name)
        if s.description:
            parts.append(s.description)
    return " ".join(parts)


def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    """
    统一取【列字段】为准（hp, speed, attack, defense, magic, resist）。
    若列为 0/None，再兜底 explain_json.raw_stats（兼容导入老备份）。
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


def compute_derived(monster: Monster) -> Dict[str, float]:
    """
    计算派生五维（float）。
    - offense = 0.5×attack + 0.2×speed + 10×[多段] + 12×[暴击/必中/无视防御/破防]
    - survive = 0.4×hp + 0.3×defense + 0.2×resist + 10×[回复/减伤/免疫/护盾]
    - control = 12×（控制类效果数量） + 8×[降速/降命中] + 0.1×speed
    - tempo = speed + 15×[先手] + 8×[加速/提速]
    - pp_pressure = 20×[出现过能量/PP压制类词] + 5×（出现频次）
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)

    offense = (
        0.5 * attack
        + 0.2 * speed
        + (10.0 if _has_any(MULTI_HIT, text) else 0.0)
        + (12.0 if _has_any(CRIT_OR_IGNORE, text) else 0.0)
    )

    survive = (
        0.4 * hp
        + 0.3 * defense
        + 0.2 * resist
        + (10.0 if _has_any(SURVIVE_BUFF, text) else 0.0)
    )

    control = (
        12.0 * _count_any(CTRL_PATTERNS, text)
        + (8.0 if _has_any(SLOW_OR_ACCURACY_DOWN, text) else 0.0)
        + 0.1 * speed
    )

    tempo = (
        speed
        + (15.0 if _has_any(FIRST_STRIKE, text) else 0.0)
        + (8.0 if _has_any(SPEED_UP, text) else 0.0)
    )

    # “出现频次”按关键词命中次数粗略统计
    pp_hits = 0
    for p in PP_PRESSURE:
        pp_hits += len(re.findall(p, text))
    pp_pressure = 20.0 * (1 if pp_hits > 0 else 0) + 5.0 * pp_hits

    return {
        "offense": float(offense),
        "survive": float(survive),
        "control": float(control),
        "tempo": float(tempo),
        "pp_pressure": float(pp_pressure),
    }


def _to_ints(d: Dict[str, float]) -> Dict[str, int]:
    """float → int（四舍五入）。"""
    return {k: int(round(float(v))) for k, v in d.items()}


def compute_derived_out(monster: Monster) -> Dict[str, int]:
    """给路由/Schema 用的整型输出。"""
    return _to_ints(compute_derived(monster))


def compute_and_persist(db: Session, monster: Monster) -> MonsterDerived:
    """
    计算 + 写入/更新 MonsterDerived（不 commit，交由调用方统一提交）。
    """
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
        # 让关系指回去（访问 m.derived 时更稳）
        monster.derived = md
    else:
        md.offense = vals["offense"]
        md.survive = vals["survive"]
        md.control = vals["control"]
        md.tempo = vals["tempo"]
        md.pp_pressure = vals["pp_pressure"]
    return md


def recompute_all(db: Session) -> int:
    """全量重算派生五维并落库，返回处理条数（不 commit）。"""
    mons = db.scalars(select(Monster)).all()
    n = 0
    for m in mons:
        compute_and_persist(db, m)
        n += 1
    return n


__all__ = [
    "compute_derived",
    "compute_derived_out",
    "compute_and_persist",
    "recompute_all",
]