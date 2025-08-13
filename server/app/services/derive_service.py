# server/app/services/derive_service.py
from __future__ import annotations

import re
from typing import Dict, Tuple, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived
from .tags_service import extract_signals, suggest_tags_for_monster, infer_role_for_monster
from .monsters_service import upsert_tags


# ============ 基础读取 ============

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    """只读列（hp/speed/attack/defense/magic/resist），None 当 0。"""
    hp      = float(getattr(monster, "hp", 0) or 0)
    speed   = float(getattr(monster, "speed", 0) or 0)
    attack  = float(getattr(monster, "attack", 0) or 0)
    defense = float(getattr(monster, "defense", 0) or 0)
    magic   = float(getattr(monster, "magic", 0) or 0)
    resist  = float(getattr(monster, "resist", 0) or 0)
    return hp, speed, attack, defense, magic, resist


def _skills_text(monster: Monster) -> str:
    """
    汇总技能名与描述文本。兼容：
      1) monster.skills 为 Skill 列表
      2) monster.skills 为 MonsterSkill 列表，且 .skill 指向 Skill
    """
    parts: List[str] = []
    for item in (getattr(monster, "skills", None) or []):
        skill = getattr(item, "skill", None) or item
        n = getattr(skill, "name", None)
        d = getattr(skill, "description", None)
        if n:
            parts.append(str(n))
        if d:
            parts.append(str(d))
    return " ".join(parts)


def _skill_powers(monster: Monster) -> List[int]:
    """收集技能威力（int，>0）。兼容 Skill 与 MonsterSkill。"""
    out: List[int] = []
    for item in (getattr(monster, "skills", None) or []):
        skill = getattr(item, "skill", None)
        power: Optional[int] = getattr(skill, "power", None) if skill is not None else None
        if power is None:
            power = getattr(item, "power", None)
        if isinstance(power, (int, float)) and power > 0:
            out.append(int(power))
    return out


def _clip(v: float, lo: float = 0.0, hi: float = 120.0) -> float:
    return max(lo, min(hi, v))


def _round_int_clip(v: float, hi: int = 120) -> int:
    return int(min(hi, max(0, round(v))))


# ============ v2 信号抽取（不改对外契约） ============

def _detect_v2_signals(monster: Monster) -> Dict[str, float]:
    """
    基于新三类标签（buf_/deb_/util_）+ 正则提取信号。
    """
    sig = extract_signals(monster)
    text = _skills_text(monster)
    codes = set(suggest_tags_for_monster(monster))

    def has(patterns: List[str]) -> bool:
        return any(re.search(p, text) for p in patterns)

    # Offense
    crit_up     = ("buf_crit_up" in codes) or has([r"必定暴击", r"暴击(率|几率|概率)?(提升|提高|上升|增加|增强)"])
    ignore_def  = ("util_penetrate" in codes) or has([r"无视防御", r"穿透(防御|护盾)"])
    armor_break = has([r"破防", r"护甲破坏"])
    def_down    = ("deb_def_down" in codes)
    res_down    = ("deb_res_down" in codes)
    marked      = has([r"标记", r"易伤", r"暴露", r"破绽"])
    multi_hit   = bool(sig.get("has_multi_hit", False))

    # Survive
    heal        = ("buf_heal" in codes) or has([r"治疗|回复|恢复"])
    shield      = ("buf_shield" in codes) or has([r"护盾|屏障"])
    dmg_reduce  = has([r"(所受|受到).*(伤害).*(减少|降低|减半|减免)", r"伤害(减少|降低|减半|减免)"])
    cleanse_self= ("buf_purify" in codes) or has([r"(净化|清除|消除|解除).*(自身).*(负面|异常|减益)"])
    immunity    = ("buf_immunity" in codes) or has([r"免疫(异常|控制|不良)状态?"])
    life_steal  = has([r"吸血", r"造成.*伤害.*(回复|恢复).*(HP|生命)"])
    def_up      = ("buf_def_up" in codes)
    res_up      = ("buf_res_up" in codes)

    # Control
    hard_cc     = sum(1 for c in ("deb_stun","deb_bind","deb_sleep","deb_freeze","deb_suffocate") if c in codes)
    soft_cc     = 1 if ("deb_confuse_seal" in codes) else 0
    acc_down    = ("deb_acc_down" in codes)
    spd_down    = ("deb_spd_down" in codes)
    atk_down    = ("deb_atk_down" in codes)
    mag_down    = ("deb_mag_down" in codes)

    # Tempo
    first_strike= bool(sig.get("first_strike", False))
    speed_up    = bool(sig.get("speed_up", False))
    extra_turn  = has([r"追加回合|再行动|额外回合|再次行动|可再动|连动"])
    action_bar  = has([r"行动条|行动值|推进(行动)?条|推条"])

    # PP
    pp_hits     = int(sig.get("pp_hits", 0))
    pp_any      = pp_hits > 0
    dispel_enemy= ("deb_dispel" in codes) or has([r"(消除|驱散).*(对方|对手).*(增益|强化)"])
    skill_seal  = ("deb_confuse_seal" in codes) or has([r"封印|禁技|无法使用技能"])
    buff_steal  = has([r"(偷取|夺取|窃取).*(增益|buff|护盾)"])
    mark_or_exp = marked

    return {
        # offense
        "crit_up": float(crit_up),
        "ignore_def": float(ignore_def),
        "armor_break": float(armor_break),
        "def_down": float(def_down),
        "res_down": float(res_down),
        "mark": float(marked),
        "multi_hit": float(multi_hit),
        # survive
        "heal": float(heal),
        "shield": float(shield),
        "dmg_reduce": float(dmg_reduce),
        "cleanse_self": float(cleanse_self),
        "immunity": float(immunity),
        "life_steal": float(life_steal),
        "def_up": float(def_up),
        "res_up": float(res_up),
        # control
        "hard_cc": float(hard_cc),
        "soft_cc": float(soft_cc),
        "acc_down": float(acc_down),
        "spd_down": float(spd_down),
        "atk_down": float(atk_down),
        "mag_down": float(mag_down),
        # tempo
        "first_strike": float(first_strike),
        "extra_turn": float(extra_turn),
        "speed_up": float(speed_up),
        "action_bar": float(action_bar),
        # pp pressure
        "pp_hits": float(pp_hits),
        "pp_any": float(pp_any),
        "dispel_enemy": float(dispel_enemy),
        "skill_seal": float(skill_seal),
        "buff_steal": float(buff_steal),
        "mark_expose": float(mark_or_exp),
    }


# ============ v2 计算公式（降低技能威力影响度） ============

def _offense_power_bonus(powers: List[int]) -> float:
    """
    只有当 Top3 平均威力达到阈值时才给少量加分：
      - avg_top3 >= 160 → +6
      - avg_top3 >= 150 → +3
      - 其它 → +0
    """
    if not powers:
        return 0.0
    top3 = sorted(powers, reverse=True)[:3]
    avg_top3 = sum(top3) / len(top3)
    if avg_top3 >= 160:
        return 6.0
    if avg_top3 >= 150:
        return 3.0
    return 0.0


def compute_derived(monster: Monster) -> Dict[str, float]:
    """
    使用 v2 规则计算派生五维（float 版本，未四舍五入）。
    - 技能威力：改为分段、极低权重，仅 150/160 档触发。
    - Offense 内部封顶 130，最终展示仍 clip 到 120。
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    s = _detect_v2_signals(monster)

    # —— 技能威力参考（分段、温和）——
    offense_power = _offense_power_bonus(_skill_powers(monster))

    # 1) 攻 offense
    atk_hi = max(attack, magic)
    atk_lo = min(attack, magic)
    offense_base = 0.55 * atk_hi + 0.15 * atk_lo + 0.20 * speed
    offense_sig = (
        10.0 * s["crit_up"] +
        12.0 * s["ignore_def"] +
        8.0  * s["multi_hit"] +
        6.0  * s["armor_break"] +
        4.0  * s["def_down"] +
        4.0  * s["res_down"] +
        3.0  * s["mark"]
    )
    offense_raw = offense_base + offense_sig + offense_power
    offense_capped = min(130.0, offense_raw)

    # 2) 生 survive
    survive_base = 0.45 * hp + 0.30 * defense + 0.25 * resist
    survive_sig = (
        10.0 * s["heal"] +
        10.0 * s["shield"] +
        8.0  * s["dmg_reduce"] +
        5.0  * s["cleanse_self"] +
        4.0  * s["immunity"] +
        3.0  * s["life_steal"] +
        2.0  * s["def_up"] +
        2.0  * s["res_up"]
    )
    survive_raw = survive_base + survive_sig

    # 3) 控 control（以信号为主）
    control_raw = (
        14.0 * s["hard_cc"] +
        8.0  * s["soft_cc"] +
        6.0  * s["acc_down"] +
        4.0  * s["spd_down"] +
        3.0  * s["atk_down"] +
        3.0  * s["mag_down"] +
        0.10 * speed
    )

    # 4) 速 tempo
    tempo_raw = (
        1.0  * speed +
        15.0 * s["first_strike"] +
        10.0 * s["extra_turn"] +
        8.0  * s["speed_up"] +
        6.0  * s["action_bar"]
    )

    # 5) 压 pp_pressure
    pp_pressure_raw = (
        18.0 * s["pp_any"] +
        5.0  * s["pp_hits"] +
        8.0  * s["dispel_enemy"] +
        10.0 * s["skill_seal"] +
        6.0  * s["buff_steal"] +
        3.0  * s["mark_expose"]
    )

    return {
        "offense": offense_capped,
        "survive": survive_raw,
        "control": control_raw,
        "tempo": tempo_raw,
        "pp_pressure": pp_pressure_raw,
    }


def _to_ints(d: Dict[str, float]) -> Dict[str, int]:
    return {k: _round_int_clip(v, hi=120) for k, v in d.items()}


def compute_derived_out(monster: Monster) -> Dict[str, int]:
    return _to_ints(compute_derived(monster))


# ============ 持久化与自动标注（保持不变） ============

def compute_and_persist(db: Session, monster: Monster) -> MonsterDerived:
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


def apply_role_tags(
    db: Session,
    monster: Monster,
    *,
    override_role_if_blank: bool = True,
    merge_tags: bool = True,
) -> None:
    role_suggest = infer_role_for_monster(monster)
    tags_suggest = suggest_tags_for_monster(monster)
    if override_role_if_blank:
        if not getattr(monster, "role", None):
            monster.role = role_suggest
    else:
        monster.role = role_suggest

    if merge_tags:
        existed_non_prefix = {
            t.name for t in (monster.tags or [])
            if getattr(t, "name", None) and not (
                t.name.startswith("buf_") or t.name.startswith("deb_") or t.name.startswith("util_")
            )
        }
        merged = sorted({*existed_non_prefix, *tags_suggest})
        monster.tags = upsert_tags(db, merged)
    else:
        monster.tags = upsert_tags(db, sorted(set(tags_suggest)))


def recompute_and_autolabel(db: Session, monster: Monster) -> MonsterDerived:
    apply_role_tags(db, monster, override_role_if_blank=True, merge_tags=True)
    md = compute_and_persist(db, monster)
    return md


def recompute_all(db: Session) -> int:
    mons: List[Monster] = db.scalars(select(Monster)).all()
    n = 0
    for m in mons:
        recompute_and_autolabel(db, m)
        n += 1
    return n


__all__ = [
    "compute_derived",
    "compute_derived_out",
    "compute_and_persist",
    "apply_role_tags",
    "recompute_and_autolabel",
    "recompute_all",
]