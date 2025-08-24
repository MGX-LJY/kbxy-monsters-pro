# server/app/services/derive_service.py
from __future__ import annotations

import bisect
from typing import Dict, Tuple, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Monster, MonsterDerived
# 仅保留用于“可选补齐前缀标签”的建议；计算本身不再依赖技能
from .tags_service import suggest_tags_for_monster  # 仅在 _ensure_prefix_tags 可选使用
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


def _round_int_clip(v: float, hi: int = 120) -> int:
    return int(min(hi, max(0, round(v))))


def _tag_codes_from_monster(monster: Monster) -> List[str]:
    """
    只从已有标签中读取规范化代码（buf_/deb_/util_）。
    不做基于技能文本的回退/推断。
    """
    raw: List[str] = []
    for t in (getattr(monster, "tags", None) or []):
        name = getattr(t, "name", None) or (t if isinstance(t, str) else None)
        if isinstance(name, str):
            raw.append(name.strip())
    return [c for c in raw if c.startswith(("buf_", "deb_", "util_"))]


# ===================== 信号抽取（仅基于标签） =====================

def _detect_signals_v3(monster: Monster) -> Dict[str, float]:
    """
    统一信号面向新五轴，**仅依据标签 codes（buf_/deb_/util_）**：

    - 生存：heal/shield/dmg_reduce/reflect/物免/法免/异常免疫/净化/def_up/res_up/evasion_up
    - 抑制：def_down/res_down/armor_break(=util_penetrate)/atk_down/mag_down/acc_down/spd_down/skill_seal/mark_expose
    - 资源&非常规：pp_any(util_pp_drain)/pp_hits(=0)/poison(deb_poison)/toxic(=0)/self_destruct(=0)/
      heal_block/debuff_fatigue/dispel_enemy/transfer_debuff/invert_buffs
    """
    codes = set(_tag_codes_from_monster(monster))

    def has_code(*keys: str) -> bool:
        return any(k in codes for k in keys)

    # —— 生存/辅助 —— #
    heal         = has_code("buf_heal")
    shield       = has_code("buf_shield")
    dmg_reduce   = has_code("buf_dmg_cut_all", "buf_phys_cut", "buf_mag_cut")
    reflect      = has_code("util_reflect")
    cleanse_self = has_code("buf_purify")
    immunity     = has_code("buf_immunity")
    phys_immu    = has_code("buf_phys_immunity")
    mag_immu     = has_code("buf_mag_immunity")
    def_up       = has_code("buf_def_up")
    res_up       = has_code("buf_res_up")
    evasion_up   = has_code("buf_evasion_up")

    # —— 抑制（对敌方） —— #
    armor_break  = has_code("util_penetrate")  # 破防/穿透/破盾 视作破甲信号
    def_down     = has_code("deb_def_down")
    res_down     = has_code("deb_res_down")
    atk_down     = has_code("deb_atk_down")
    mag_down     = has_code("deb_mag_down")
    acc_down     = has_code("deb_acc_down")
    spd_down     = has_code("deb_spd_down")
    skill_seal   = has_code("deb_confuse_seal")
    mark_expose  = has_code("deb_marked", "deb_vulnerable")

    # —— 资源/非常规 —— #
    pp_hits       = 0  # 不读取技能，不统计段数
    pp_any        = has_code("util_pp_drain")
    poison        = has_code("deb_poison")
    toxic         = False  # 无单独“剧毒”标签，置 0
    self_destruct = False  # 无“自爆”标签，置 0
    heal_block    = has_code("deb_heal_block")
    fatigue       = has_code("deb_fatigue")
    dispel_enemy  = has_code("deb_dispel")
    transfer_debuff = has_code("util_transfer_debuff")
    invert_buffs    = has_code("util_invert_buffs")

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
    仅基于：六维（hp/defense/resist）+ 上述标签信号。
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
        8.0  * s["armor_break"] +   # = util_penetrate
        6.0  * s["def_down"] +
        6.0  * s["res_down"] +
        2.0  * s["spd_down"] +
        2.0  * s["mark_expose"]
    )
    # 联合命中加成（只看标签是否同时存在）
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

    # 特殊：PP 压制/中毒(剧毒=0)/自爆=0/禁疗/疲劳/（可选）驱散/转移/反转
    special_tactics_raw = (
        12.0 * s["pp_any"] +
        4.0  * s["pp_hits"] +     # 恒为 0（不读技能）
        8.0  * s["toxic"] +       # 恒为 0（无“剧毒”标签）
        6.0  * s["poison"] +
        10.0 * s["self_destruct"] +  # 恒为 0
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
    （注意：这一步仍可能基于技能文本；默认 recompute_derived_only 会传 ensure_prefix_tags=False）
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
    1) 计算派生 0~120（写 MonsterDerived）—— 仅基于标签与基础六维
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