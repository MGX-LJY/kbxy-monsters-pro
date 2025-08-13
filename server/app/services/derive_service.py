# server/app/services/derive_service.py
from __future__ import annotations

import re
from typing import Dict, Tuple, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived
from .tags_service import extract_signals, suggest_tags_for_monster  # 定位已迁出此模块
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


def _tag_codes_from_monster(monster: Monster) -> List[str]:
    """
    读取已落库的新前缀标签（buf_/deb_/util_）。
    若没有，则回退到正则建议（避免“空标签”影响派生/定位）。
    """
    raw = []
    for t in (getattr(monster, "tags", None) or []):
        name = getattr(t, "name", None) or (t if isinstance(t, str) else None)
        if isinstance(name, str):
            raw.append(name)
    # 只要 prefix 标签
    codes = [c for c in raw if c.startswith("buf_") or c.startswith("deb_") or c.startswith("util_")]
    if not codes:
        # 回退：用正则建议的标签（同样只保留新前缀）
        tried = suggest_tags_for_monster(monster)
        codes = [c for c in tried if c.startswith("buf_") or c.startswith("deb_") or c.startswith("util_")]
    return codes


# ============ v2 信号抽取（只依赖：新前缀标签 + 技能文本特征） ============

def _detect_v2_signals(monster: Monster) -> Dict[str, float]:
    """
    基于新三类标签（buf_/deb_/util_）+ 技能文本正则提取信号。
    不再从 tags_service 里获取“定位”，仅做信号。
    """
    sig = extract_signals(monster)  # 基础统计：multi_hit / first_strike / speed_up / pp_hits 等
    text = _skills_text(monster)
    codes = set(_tag_codes_from_monster(monster))

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

    # Survive / Support
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
        # survive/support
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
    - 技能威力：分段、极低权重，仅 150/160 档触发。
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


# ============ 定位（迁入本模块，使用“派生 + 标签 + 六维”严谨判定） ============

def _category_scores(
    monster: Monster,
    derived_int: Dict[str, int],
    sig: Dict[str, float],
) -> Dict[str, float]:
    """
    为各定位计算一个“鲜明度分数”，用于比较。
    规则：
      - 强控优先：hard_cc 明确、control 高 → 控制
      - 强奶辅优先：治疗/护盾/净化/免疫 等 + survive 优 → 辅助
      - 纯主攻：offense 高 + 穿盾/暴击/多段/破防 等 → 主攻
      - 坦克：survive 高 + 高 HP/RES + 减伤/免疫/护盾 → 坦克
      - 通用：分数都不够或差距小
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)

    offense  = float(derived_int.get("offense", 0))
    survive  = float(derived_int.get("survive", 0))
    control  = float(derived_int.get("control", 0))
    tempo    = float(derived_int.get("tempo", 0))
    pp_press = float(derived_int.get("pp_pressure", 0))

    # 信号简化聚合
    dps_sig   = (2*sig["crit_up"] + 2*sig["ignore_def"] + 1.5*sig["multi_hit"]
                 + 1.2*sig["def_down"] + 1.2*sig["res_down"] + 1.2*sig["armor_break"] + 1.0*sig["mark"])
    ctrl_sig  = (4*sig["hard_cc"] + 2.5*sig["soft_cc"] + 2*sig["spd_down"] + 2*sig["acc_down"]
                 + 1.2*sig["atk_down"] + 1.2*sig["mag_down"])
    supp_sig  = (3.5*sig["heal"] + 3.5*sig["shield"] + 2.5*sig["cleanse_self"] + 2.5*sig["immunity"]
                 + 1.2*sig["def_up"] + 1.2*sig["res_up"] + 1.2*sig["dmg_reduce"])

    # 各定位分
    score_offense = 1.00*offense + 0.35*tempo + 8.0*dps_sig - 0.20*control - 0.15*supp_sig
    score_control = 1.10*control + 0.20*tempo + 10.0*sig["hard_cc"] + 3.5*sig["soft_cc"] + 2.0*(sig["spd_down"]+sig["acc_down"]) - 0.15*offense
    score_support = 0.90*survive + 0.25*tempo + 8.0*(sig["heal"]+sig["shield"]) + 5.0*(sig["cleanse_self"]+sig["immunity"]) + 1.5*(sig["def_up"]+sig["res_up"]) - 0.30*offense
    score_tank    = 1.05*survive + 0.15*tempo + 5.0*(sig["shield"]+sig["dmg_reduce"]) + 2.0*sig["immunity"] \
                    + (5.0 if hp >= 115 else 0.0) + (5.0 if resist >= 115 else 0.0) - 0.40*offense \
                    + 0.5*pp_press  # 小幅拉开与“压制型辅助”的差异

    return {
        "主攻": score_offense,
        "控制": score_control,
        "辅助": score_support,
        "坦克": score_tank,
    }


def _decide_role(scores: Dict[str, float], derived_int: Dict[str, int], sig: Dict[str, float]) -> Tuple[str, float, str]:
    """
    根据分数 + 规则决策最终定位，返回 (role, confidence, reason)。
    优先级：强控 > 强奶辅 > 主攻 > 坦克 > 通用。
    """
    # 强规则优先（鲜明判定）
    if sig["hard_cc"] >= 1 and derived_int.get("control", 0) >= 70:
        top_role = "控制"
        reason = "硬控存在且控制分高"
        confidence = 0.9
        return top_role, confidence, reason

    support_trigger = (sig["heal"] + sig["shield"] + sig["cleanse_self"] + sig["immunity"]) >= 2 and derived_int.get("survive", 0) >= 70
    if support_trigger:
        # 如果同时 offense 很高且 dps 信号强，则稍降置信度但仍以“辅助”为主（满足“更鲜明”）
        top_role = "辅助"
        reason = "治疗/护盾/净化/免疫信号明显且生存分高"
        confidence = 0.8 if derived_int.get("offense", 0) < 85 else 0.7
        return top_role, confidence, reason

    # 常规：按分数比较 + 阈值/差距
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (r1, s1), (r2, s2) = ordered[0], ordered[1] if len(ordered) > 1 else (("通用", 0.0))
    margin = s1 - s2

    # 阈值：分数不够“鲜明”或差距太小 → 通用
    if s1 < 55 and margin < 10:
        return "通用", 0.55, "各项分数均不突出"

    # 细化：当“主攻/坦克”相近时，用派生值与关键信号打破僵局
    tie_break_order = ["控制", "辅助", "主攻", "坦克"]  # 规则中的优先级
    if margin < 6:
        # 小差距时，按优先级靠前的类别倾斜（如果它在前两名中）
        for cat in tie_break_order:
            if cat in (r1, r2):
                r1 = cat
                break
        reason = f"分差较小，按优先级判定为{r1}"
        confidence = 0.62
        return r1, confidence, reason

    # 正常选择
    confidence = max(0.6, min(0.95, margin / max(1.0, s1)))  # 简易置信度：差距/最高分，裁剪至 [0.6,0.95]
    return r1, confidence, f"类别分对比：{r1}={round(s1,1)} 高于 {r2}={round(s2,1)}"


def infer_role_for_monster(monster: Monster) -> str:
    """
    对外主函数：仅返回角色字符串（兼容老接口）。
    实际决策使用“派生五维 + 标签信号 + 六维”综合打分。
    """
    # 使用 int 版派生（若未计算，compute_derived_out 会即时算）
    d_int = compute_derived_out(monster)
    sig = _detect_v2_signals(monster)
    scores = _category_scores(monster, d_int, sig)
    role, _conf, _reason = _decide_role(scores, d_int, sig)
    return role


def infer_role_details(monster: Monster) -> Dict[str, object]:
    """
    扩展版：返回 role / confidence / reason / scores（便于派生接口回显）。
    不强制持久化这些扩展字段。
    """
    d_int = compute_derived_out(monster)
    sig = _detect_v2_signals(monster)
    scores = _category_scores(monster, d_int, sig)
    role, conf, reason = _decide_role(scores, d_int, sig)
    return {
        "role": role,
        "confidence": round(float(conf), 3),
        "reason": reason,
        "scores": {k: round(float(v), 1) for k, v in scores.items()},
    }


# ============ 持久化派生 ============

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


def _ensure_prefix_tags(db: Session, monster: Monster) -> None:
    """
    若 monster.tags 缺少新前缀标签（buf_/deb_/util_），用正则建议补齐并落库。
    保持“已有的非新前缀标签”不丢失。
    """
    cur = [getattr(t, "name", None) or (t if isinstance(t, str) else None) for t in (monster.tags or [])]
    cur = [c for c in cur if isinstance(c, str)]
    has_prefix = any(c.startswith(("buf_", "deb_", "util_")) for c in cur)
    if has_prefix:
        return
    suggested = suggest_tags_for_monster(monster)
    new_prefix = sorted({c for c in suggested if c.startswith(("buf_", "deb_", "util_"))})
    if not new_prefix:
        return
    preserved_non_prefix = [c for c in cur if not c.startswith(("buf_", "deb_", "util_"))]
    monster.tags = upsert_tags(db, preserved_non_prefix + new_prefix)


# ============ 统一：派生 + 自动定位 + （可选）补标签 ============

def recompute_and_autolabel(db: Session, monster: Monster) -> MonsterDerived:
    """
    新流程：
      1) 计算并写入派生五维（compute_and_persist）
      2) 确保新前缀标签存在（缺则用正则补齐，不额外覆盖已有）
      3) 基于 派生 + 标签 + 六维 做定位，写回 monster.role
      4) 兼容：把建议定位挂到 md.role_suggested（仅返回时使用，非强制持久化列）
    """
    md = compute_and_persist(db, monster)          # 1) 派生
    _ensure_prefix_tags(db, monster)               # 2) 缺则补标签

    details = infer_role_details(monster)          # 3) 定位
    monster.role = details["role"]

    # 4) 兼容前端：把 role_suggested 附在派生对象上（动态属性，序列化端自行处理）
    setattr(md, "role_suggested", details["role"])
    setattr(md, "role_confidence", details.get("confidence"))
    setattr(md, "role_reason", details.get("reason"))
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
    "infer_role_for_monster",
    "infer_role_details",
    "recompute_and_autolabel",
    "recompute_all",
]