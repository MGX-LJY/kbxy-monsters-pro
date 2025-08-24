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


# ===================== 基础读取 =====================

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    hp      = float(getattr(monster, "hp", 0) or 0)
    speed   = float(getattr(monster, "speed", 0) or 0)
    attack  = float(getattr(monster, "attack", 0) or 0)
    defense = float(getattr(monster, "defense", 0) or 0)
    magic   = float(getattr(monster, "magic", 0) or 0)
    resist  = float(getattr(monster, "resist", 0) or 0)
    return hp, speed, attack, defense, magic, resist


def _skills_text(monster: Monster) -> str:
    """
    兼容两种关系结构：
    - monster.skills: [Skill or MonsterSkill(skill=Skill)]
    - monster.monster_skills: [MonsterSkill]
    """
    parts: List[str] = []
    # 1) 常规 skills
    for item in (getattr(monster, "skills", None) or []):
        skill = getattr(item, "skill", None) or item
        n = getattr(skill, "name", None)
        d = getattr(skill, "description", None)
        if n:
            parts.append(str(n))
        if d:
            parts.append(str(d))
        # 有些实现把说明写在 MonsterSkill 上
        desc2 = getattr(item, "description", None)
        if desc2:
            parts.append(str(desc2))
    # 2) 兼容 monster_skills
    for ms in (getattr(monster, "monster_skills", None) or []):
        sk = getattr(ms, "skill", None)
        if sk is not None:
            if getattr(sk, "name", None):
                parts.append(str(sk.name))
            if getattr(sk, "description", None):
                parts.append(str(sk.description))
        if getattr(ms, "description", None):
            parts.append(str(ms.description))
    return " ".join(parts)


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


# ===================== 信号抽取（在 tags_service 基础上补充“毒/自爆”等） =====================

def _detect_signals_v3(monster: Monster) -> Dict[str, float]:
    """
    统一信号面向新五轴：
      - 生存：heal/shield/dmg_reduce/reflect/物免/法免/异常免疫/净化/def_up/res_up/evasion_up
      - 抑制：def_down/res_down/armor_break/atk_down/mag_down/acc_down/spd_down/skill_seal/mark_expose
      - 资源&非常规：pp_any/pp_hits/poison/toxic/self_destruct/heal_block/fatigue/（可选）dispel/transfer/invert
    """
    sig = extract_signals(monster)  # 由 tags_service 产出的一组基础布尔/计数信号
    text = _skills_text(monster)
    codes = set(_tag_codes_from_monster(monster))

    def has(patterns: List[str]) -> bool:
        return any(re.search(p, text) for p in patterns)

    # —— 生存/辅助 —— #
    heal        = ("buf_heal" in codes) or has([r"(回复|治疗|恢复)"])
    shield      = ("buf_shield" in codes) or has([r"护盾|结界|护体|庇护|保护"])
    dmg_reduce  = ("buf_dmg_cut_all" in codes) or ("buf_phys_cut" in codes) or ("buf_mag_cut" in codes) or \
                  has([r"(所受|受到).*(伤害).*(减少|降低|减半|减免)", r"伤害(减少|降低|减半|减免)"])
    reflect     = ("util_reflect" in codes) or has([r"反击|反伤|反弹|反射伤害"])
    cleanse_self= ("buf_purify" in codes) or has([r"(净化|清除|消除|解除).*(自身|自我|本方).*?(负面|异常|减益|不良)"])
    immunity    = ("buf_immunity" in codes) or has([r"免疫(异常|控制|不良)状态?"])
    phys_immu   = ("buf_phys_immunity" in codes) or has([r"免疫.*?(物理|物理攻击)"])
    mag_immu    = ("buf_mag_immunity" in codes) or has([r"免疫.*?(法术|魔法|法术攻击|魔法攻击)"])
    def_up      = ("buf_def_up" in codes)
    res_up      = ("buf_res_up" in codes)
    evasion_up  = ("buf_evasion_up" in codes) or has([r"(闪避|回避|躲避)(率)?(提升|提高|上升|增加|增强)"])

    # —— 抑制（对敌方） —— #
    armor_break = has([r"破防", r"护甲破坏"])
    def_down    = ("deb_def_down" in codes)
    res_down    = ("deb_res_down" in codes)
    atk_down    = ("deb_atk_down" in codes)
    mag_down    = ("deb_mag_down" in codes)
    acc_down    = ("deb_acc_down" in codes)
    spd_down    = ("deb_spd_down" in codes)
    skill_seal  = ("deb_confuse_seal" in codes) or has([r"封印|禁技|无法使用技能|禁止使用技能"])
    mark_expose = ("deb_marked" in codes) or ("deb_vulnerable" in codes) or has([r"标记|易伤|(暴|曝)露|破绽"])

    # —— 资源/非常规 —— #
    pp_hits      = int(sig.get("pp_hits", 0))
    pp_any       = (pp_hits > 0) or ("util_pp_drain" in codes) or has([r"扣\s*PP", r"减少.*?技能.*?次数"])
    poison       = has([r"中毒|毒伤"]) and not has([r"解毒|祛毒"])
    toxic        = has([r"剧毒|猛毒|强毒"])
    self_destruct= has([r"自爆|自毁|同归于尽|玉石俱焚"])
    heal_block   = ("deb_heal_block" in codes) or has([r"无法(回复|治疗|恢复)", r"(治疗|回复|恢复).*(降低|减少|减半|抑制)"])
    fatigue      = ("deb_fatigue" in codes) or has([r"疲劳|乏力|疲倦"])
    dispel_enemy = ("deb_dispel" in codes) or has([r"(消除|驱散|清除).*(对方|对手|敌方).*(增益|强化|状态)"])
    transfer_debuff = ("util_transfer_debuff" in codes) or has([r"(将|把).*(自身|自我).*(负面|异常|减益).*(转移|移交).*(对方|对手|敌方)"])
    invert_buffs = ("util_invert_buffs" in codes) or has([r"(将|使).*(增益|强化).*(转变|变为).*(减益|负面)"])

    return {
        # 生存
        "heal": float(heal),
        "shield": float(shield),
        "dmg_reduce": float(dmg_reduce),
        "reflect": float(reflect),
        "cleanse_self": float(cleanse_self),
        "immunity": float(immunity),
        "phys_immunity": float(phys_immu),
        "mag_immunity": float(mag_immu),
        "def_up": float(def_up),
        "res_up": float(res_up),
        "evasion_up": float(evasion_up),

        # 抑制
        "armor_break": float(armor_break),
        "def_down": float(def_down),
        "res_down": float(res_down),
        "atk_down": float(atk_down),
        "mag_down": float(mag_down),
        "acc_down": float(acc_down),
        "spd_down": float(spd_down),
        "skill_seal": float(skill_seal),
        "mark_expose": float(mark_expose),

        # 资源/非常规
        "pp_any": float(pp_any),
        "pp_hits": float(pp_hits),
        "poison": float(poison),
        "toxic": float(toxic),
        "self_destruct": float(self_destruct),
        "heal_block": float(heal_block),
        "fatigue": float(fatigue),
        "dispel_enemy": float(dispel_enemy),
        "transfer_debuff": float(transfer_debuff),
        "invert_buffs": float(invert_buffs),
    }


# ===================== 新五轴计算（输出 0~120） =====================

NEW_KEYS = ["body_defense", "body_resist", "debuff_def_res", "debuff_atk_mag", "special_tactics"]


def compute_derived(monster: Monster) -> Dict[str, float]:
    """
    计算“体防/体抗/削防抗/削攻法/特殊”的原始浮点值（未裁剪）。
    """
    hp, _speed, _attack, defense, _magic, resist = _raw_six(monster)
    s = _detect_signals_v3(monster)

    # 体防：硬生存（体力/防御为主，少量抗性权重）
    body_defense_base = 0.45 * hp + 0.35 * defense + 0.10 * resist
    body_defense_sig = (
        10.0 * s["heal"] +
        10.0 * s["shield"] +
        8.0  * s["dmg_reduce"] +
        6.0  * s["reflect"] +
        6.0  * s["phys_immunity"] +
        6.0  * s["mag_immunity"] +
        3.0  * s["def_up"] +
        2.0  * s["evasion_up"] +
        2.0  * s["cleanse_self"]
    )
    body_defense_raw = body_defense_base + body_defense_sig

    # 体抗：抗异常（体力/抗性为主，少量防御权重）
    body_resist_base = 0.45 * hp + 0.35 * resist + 0.10 * defense
    body_resist_sig = (
        10.0 * s["immunity"] +
        6.0  * s["cleanse_self"] +
        4.0  * s["res_up"] +
        3.0  * s["mag_immunity"]
    )
    body_resist_raw = body_resist_base + body_resist_sig

    # 削防抗：降防/降抗/破甲 + 联合奖励（降速/易伤小额）
    debuff_def_res_sig = (
        8.0  * s["armor_break"] +
        6.0  * s["def_down"] +
        6.0  * s["res_down"] +
        2.0  * s["spd_down"] +
        2.0  * s["mark_expose"]
    )
    # 联合命中加成
    if s["def_down"] and s["res_down"]:
        debuff_def_res_sig += 4.0
    if s["def_down"] and s["armor_break"]:
        debuff_def_res_sig += 3.0
    debuff_def_res_raw = debuff_def_res_sig  # 该轴以信号为主，不叠加六维

    # 削攻法：降攻/降法/封技为主；降命中次之；降速小额
    debuff_atk_mag_raw = (
        8.0  * s["atk_down"] +
        8.0  * s["mag_down"] +
        6.0  * s["skill_seal"] +
        4.0  * s["acc_down"] +
        2.0  * s["spd_down"]
    )

    # 特殊：PP 压制/中毒(剧毒)/自爆/禁疗/疲劳/（可选）驱散/转移/反转
    special_tactics_raw = (
        12.0 * s["pp_any"] +
        4.0  * s["pp_hits"] +
        8.0  * s["toxic"] +
        6.0  * s["poison"] +
        10.0 * s["self_destruct"] +
        7.0  * s["heal_block"] +
        6.0  * s["fatigue"] +
        3.0  * s["dispel_enemy"] +
        3.0  * s["transfer_debuff"] +
        3.0  * s["invert_buffs"]
    )

    return {
        "body_defense": body_defense_raw,
        "body_resist": body_resist_raw,
        "debuff_def_res": debuff_def_res_raw,
        "debuff_atk_mag": debuff_atk_mag_raw,
        "special_tactics": special_tactics_raw,
    }


def compute_derived_out(monster: Monster) -> Dict[str, int]:
    vals = compute_derived(monster)
    return {k: _round_int_clip(v, hi=120) for k, v in vals.items()}


# ===================== 分位（可选，用于展示，不参与任何定位） =====================

def _percentile_rank(sorted_vals: List[int], v: float) -> float:
    """
    百分位（0~100）。对空样本/极端值做边界处理。
    """
    if not sorted_vals:
        return max(0.0, min(100.0, (v / 120.0) * 100.0))
    i = bisect.bisect_left(sorted_vals, v)
    n = len(sorted_vals)
    pct = ((i - 0.5) / n) if n > 0 else 0.0
    pct = max(0.0, min(1.0, pct))
    return pct * 100.0


def _build_norm_ctx(db: Optional[Session]) -> Dict[str, List[int]]:
    """
    从数据库汇总新五轴有序样本，用于计算分位。db 缺失时返回空上下文（走兜底线性缩放）。
    """
    if not isinstance(db, Session):
        return {k: [] for k in NEW_KEYS}
    vals = {k: [] for k in NEW_KEYS}
    rows = db.execute(select(
        MonsterDerived.body_defense,
        MonsterDerived.body_resist,
        MonsterDerived.debuff_def_res,
        MonsterDerived.debuff_atk_mag,
        MonsterDerived.special_tactics,
    )).all()
    for bd, br, ddr, dam, sp in rows:
        if bd is not None: vals["body_defense"].append(int(bd))
        if br is not None: vals["body_resist"].append(int(br))
        if ddr is not None: vals["debuff_def_res"].append(int(ddr))
        if dam is not None: vals["debuff_atk_mag"].append(int(dam))
        if sp is not None: vals["special_tactics"].append(int(sp))
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


# ===================== 持久化派生 =====================

def compute_and_persist(db: Session, monster: Monster) -> MonsterDerived:
    vals = compute_derived_out(monster)
    md = monster.derived
    if not md:
        md = MonsterDerived(monster_id=monster.id)
        db.add(md)
        monster.derived = md

    md.body_defense    = vals["body_defense"]
    md.body_resist     = vals["body_resist"]
    md.debuff_def_res  = vals["debuff_def_res"]
    md.debuff_atk_mag  = vals["debuff_atk_mag"]
    md.special_tactics = vals["special_tactics"]
    return md


def _ensure_prefix_tags(db: Session, monster: Monster) -> None:
    """
    可选：若缺少 buf_/deb_/util_ 前缀标签，则用正则建议补齐，不覆盖已有非前缀。
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


# ===================== 统一：仅派生（可选补标签） =====================

def recompute_derived_only(db: Session, monster: Monster, *, ensure_prefix_tags: bool = False) -> MonsterDerived:
    """
    1) 计算派生 0~120（写 MonsterDerived）
    2) （可选）若缺新前缀标签，用正则补齐并写库（不覆盖已有非前缀）
    不再写回 monster.role，也不提供任何定位相关输出。
    """
    md = compute_and_persist(db, monster)
    if ensure_prefix_tags:
        _ensure_prefix_tags(db, monster)
    return md


def recompute_all(db: Session) -> int:
    """
    全库重算，仅落新五轴。
    """
    mons: List[Monster] = db.scalars(select(Monster)).all()
    n = 0
    for m in mons:
        recompute_derived_only(db, m, ensure_prefix_tags=False)
        n += 1
    return n


__all__ = [
    "compute_derived",
    "compute_derived_out",
    "compute_and_persist",
    "recompute_derived_only",
    "recompute_all",
]