# server/app/services/derive_service.py
from __future__ import annotations

import bisect
import re
from typing import Dict, Tuple, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived
from .tags_service import extract_signals, suggest_tags_for_monster  # 仅用于信号与“缺前缀时的补齐”
from .monsters_service import upsert_tags


# ============ 基础读取 ============

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    hp      = float(getattr(monster, "hp", 0) or 0)
    speed   = float(getattr(monster, "speed", 0) or 0)
    attack  = float(getattr(monster, "attack", 0) or 0)
    defense = float(getattr(monster, "defense", 0) or 0)
    magic   = float(getattr(monster, "magic", 0) or 0)
    resist  = float(getattr(monster, "resist", 0) or 0)
    return hp, speed, attack, defense, magic, resist


def _skills_text(monster: Monster) -> str:
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
    raw = []
    for t in (getattr(monster, "tags", None) or []):
        name = getattr(t, "name", None) or (t if isinstance(t, str) else None)
        if isinstance(name, str):
            raw.append(name)
    codes = [c for c in raw if c.startswith("buf_") or c.startswith("deb_") or c.startswith("util_")]
    if not codes:
        tried = suggest_tags_for_monster(monster)
        codes = [c for c in tried if c.startswith("buf_") or c.startswith("deb_") or c.startswith("util_")]
    return codes


# ============ v2 信号抽取（只依赖：新前缀标签 + 技能文本特征） ============

def _detect_v2_signals(monster: Monster) -> Dict[str, float]:
    sig = extract_signals(monster)
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
        "crit_up": float(crit_up),
        "ignore_def": float(ignore_def),
        "armor_break": float(armor_break),
        "def_down": float(def_down),
        "res_down": float(res_down),
        "mark": float(marked),
        "multi_hit": float(multi_hit),

        "heal": float(heal),
        "shield": float(shield),
        "dmg_reduce": float(dmg_reduce),
        "cleanse_self": float(cleanse_self),
        "immunity": float(immunity),
        "life_steal": float(life_steal),
        "def_up": float(def_up),
        "res_up": float(res_up),

        "hard_cc": float(hard_cc),
        "soft_cc": float(soft_cc),
        "acc_down": float(acc_down),
        "spd_down": float(spd_down),
        "atk_down": float(atk_down),
        "mag_down": float(mag_down),

        "first_strike": float(first_strike),
        "extra_turn": float(extra_turn),
        "speed_up": float(speed_up),
        "action_bar": float(action_bar),

        "pp_hits": float(pp_hits),
        "pp_any": float(pp_any),
        "dispel_enemy": float(dispel_enemy),
        "skill_seal": float(skill_seal),
        "buff_steal": float(buff_steal),
        "mark_expose": float(mark_or_exp),
    }


# ============ v2 计算公式（派生五系：仍然产出 0~120，不做全局依赖） ============

def _offense_power_bonus(powers: List[int]) -> float:
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
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    s = _detect_v2_signals(monster)
    offense_power = _offense_power_bonus(_skill_powers(monster))

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

    control_raw = (
        14.0 * s["hard_cc"] +
        8.0  * s["soft_cc"] +
        6.0  * s["acc_down"] +
        4.0  * s["spd_down"] +
        3.0  * s["atk_down"] +
        3.0  * s["mag_down"] +
        0.10 * speed
    )

    tempo_raw = (
        1.0  * speed +
        15.0 * s["first_strike"] +
        10.0 * s["extra_turn"] +
        8.0  * s["speed_up"] +
        6.0  * s["action_bar"]
    )

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


# ============ 标准化/分位上下文（基于 MonsterDerived 样本） ============

def _percentile_rank(sorted_vals: List[int], v: float) -> float:
    """
    百分位（0~100）。对空样本/极端值做边界处理。
    """
    if not sorted_vals:
        return (v / 120.0) * 100.0  # 兜底线性缩放
    i = bisect.bisect_left(sorted_vals, v)
    n = len(sorted_vals)
    # 使用 (i-0.5)/n 的插值更平滑
    pct = ((i - 0.5) / n) if n > 0 else 0.0
    pct = max(0.0, min(1.0, pct))
    return pct * 100.0


def _build_norm_ctx(db: Optional[Session]) -> Dict[str, List[int]]:
    """
    从数据库汇总五系有序样本，用于计算分位。db 缺失时返回空上下文（走兜底线性缩放）。
    """
    if not isinstance(db, Session):
        return {k: [] for k in ["offense", "survive", "control", "tempo", "pp_pressure"]}
    vals = {k: [] for k in ["offense", "survive", "control", "tempo", "pp_pressure"]}
    rows = db.execute(select(
        MonsterDerived.offense,
        MonsterDerived.survive,
        MonsterDerived.control,
        MonsterDerived.tempo,
        MonsterDerived.pp_pressure,
    )).all()
    for off, sur, ctl, tmp, pp in rows:
        if off is not None: vals["offense"].append(int(off))
        if sur is not None: vals["survive"].append(int(sur))
        if ctl is not None: vals["control"].append(int(ctl))
        if tmp is not None: vals["tempo"].append(int(tmp))
        if pp  is not None: vals["pp_pressure"].append(int(pp))
    for k in vals:
        vals[k].sort()
    return vals


def _normalize_derived(derived_int: Dict[str, int], norm_ctx: Dict[str, List[int]]) -> Dict[str, float]:
    """
    将 0~120 的派生整数映射到 0~100 的分位百分位。
    """
    out: Dict[str, float] = {}
    for k, v in derived_int.items():
        samples = norm_ctx.get(k, []) if norm_ctx else []
        out[k] = round(_percentile_rank(samples, float(v)), 2)
    return out


# ============ 定位（用分位后的五系 + 信号 + 六维） ============

def _category_scores(
    monster: Monster,
    derived_pctl: Dict[str, float],   # 注意：这里使用分位后的 0~100
    sig: Dict[str, float],
) -> Dict[str, float]:
    hp, _speed, _attack, _defense, _magic, resist = _raw_six(monster)

    offense  = float(derived_pctl.get("offense", 0.0))
    survive  = float(derived_pctl.get("survive", 0.0))
    control  = float(derived_pctl.get("control", 0.0))
    tempo    = float(derived_pctl.get("tempo", 0.0))
    pp_press = float(derived_pctl.get("pp_pressure", 0.0))

    dps_sig   = (2*sig["crit_up"] + 2*sig["ignore_def"] + 1.5*sig["multi_hit"]
                 + 1.2*sig["def_down"] + 1.2*sig["res_down"] + 1.2*sig["armor_break"] + 1.0*sig["mark"])
    ctrl_sig  = (4*sig["hard_cc"] + 2.5*sig["soft_cc"] + 2*sig["spd_down"] + 2*sig["acc_down"]
                 + 1.2*sig["atk_down"] + 1.2*sig["mag_down"])
    supp_sig  = (3.5*sig["heal"] + 3.5*sig["shield"] + 2.5*sig["cleanse_self"] + 2.5*sig["immunity"]
                 + 1.2*sig["def_up"] + 1.2*sig["res_up"] + 1.2*sig["dmg_reduce"])

    # 在“分位空间”的综合得分
    score_offense = 1.00*offense + 0.35*tempo + 8.0*dps_sig - 0.15*control - 0.10*supp_sig
    score_control = 1.05*control + 0.20*tempo + 10.0*sig["hard_cc"] + 3.5*sig["soft_cc"] + 2.0*(sig["spd_down"]+sig["acc_down"]) - 0.10*offense
    score_support = 0.95*survive + 0.20*tempo + 8.0*(sig["heal"]+sig["shield"]) + 5.0*(sig["cleanse_self"]+sig["immunity"]) + 1.5*(sig["def_up"]+sig["res_up"]) - 0.20*offense
    score_tank    = 1.00*survive + 0.10*tempo + 5.0*(sig["shield"]+sig["dmg_reduce"]) + 2.0*sig["immunity"] \
                    + (3.5 if hp >= 115 else 0.0) + (3.5 if resist >= 115 else 0.0) - 0.30*offense \
                    + 0.4*pp_press

    return {
        "主攻": score_offense,
        "控制": score_control,
        "辅助": score_support,
        "坦克": score_tank,
    }


def _decide_role(
    scores: Dict[str, float],
    derived_pctl: Dict[str, float],
    sig: Dict[str, float]
) -> Tuple[str, float, str]:
    """
    在分位空间决策最终定位，返回 (role, confidence, reason)。
    强规则（更鲜明） > 常规比较 > 小差距优先级。
    """
    # 强规则（分位阈值避免固定偏置）
    if sig["hard_cc"] >= 1 and derived_pctl.get("control", 0.0) >= 75.0:
        return "控制", 0.9, "硬控存在且控制分位≥P75"

    support_trigger = (sig["heal"] + sig["shield"] + sig["cleanse_self"] + sig["immunity"]) >= 2 \
                      and derived_pctl.get("survive", 0.0) >= 70.0
    if support_trigger:
        conf = 0.8 if derived_pctl.get("offense", 0.0) < 85.0 else 0.7
        return "辅助", conf, "奶辅信号≥2 且生存分位≥P70"

    # 常规比较
    ordered = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    (r1, s1), (r2, s2) = ordered[0], (ordered[1] if len(ordered) > 1 else ("通用", 0.0))
    margin = s1 - s2

    # 分数太平、均衡 → 通用
    if s1 < 55 and margin < 10:
        return "通用", 0.55, "各项分位与信号均不够突出"

    # 小差距：按优先级打破（强控 > 强辅 > 主攻 > 坦克）
    tie_break_order = ["控制", "辅助", "主攻", "坦克"]
    if margin < 6:
        for cat in tie_break_order:
            if cat in (r1, r2):
                return cat, 0.62, f"分差小（{round(margin,2)}），按优先级判定为{cat}"

    # 正常：差距越大，置信度越高（保守裁剪）
    confidence = max(0.6, min(0.95, margin / max(1.0, abs(s1))))
    return r1, confidence, f"类别分对比：{r1}={round(s1,1)} 高于 {r2}={round(s2,1)}（Δ={round(margin,1)}）"


def infer_role_for_monster(monster: Monster, db: Optional[Session] = None) -> str:
    """
    对外主函数：仅返回角色字符串（兼容旧签名，可不传 db）。
    若提供 db，则先基于 MonsterDerived 样本做分位标准化。
    """
    d_int = compute_derived_out(monster)
    sig = _detect_v2_signals(monster)
    norm = _build_norm_ctx(db)
    d_p = _normalize_derived(d_int, norm)
    scores = _category_scores(monster, d_p, sig)
    role, _conf, _reason = _decide_role(scores, d_p, sig)
    return role


def infer_role_details(monster: Monster, db: Optional[Session] = None) -> Dict[str, object]:
    """
    扩展版：返回 role / confidence / reason / scores，并包含派生分位。
    """
    d_int = compute_derived_out(monster)
    sig = _detect_v2_signals(monster)
    norm = _build_norm_ctx(db)
    d_p = _normalize_derived(d_int, norm)
    scores = _category_scores(monster, d_p, sig)
    role, conf, reason = _decide_role(scores, d_p, sig)
    return {
        "role": role,
        "confidence": round(float(conf), 3),
        "reason": reason,
        "scores": {k: round(float(v), 1) for k, v in scores.items()},
        "derived_percentile": d_p,   # 0~100
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
    1) 计算派生 0~120（写 MonsterDerived）
    2) 若缺新前缀标签，用正则补齐并写库（不覆盖已有非前缀）
    3) 基于“分位后的五系 + 信号 + 六维”做定位，写回 monster.role
    4) 将建议定位附到 md 的动态属性供前端读取（role_suggested / role_confidence / role_reason）
    """
    md = compute_and_persist(db, monster)
    _ensure_prefix_tags(db, monster)

    details = infer_role_details(monster, db=db)   # <—— 传入 db 以启用分位标准化
    monster.role = details["role"]

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