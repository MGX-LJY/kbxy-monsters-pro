# server/app/services/tags_service.py
from __future__ import annotations

import re
from typing import List, Set, Dict, Tuple

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
    "deb_atk_down":   "攻↓",
    "deb_mag_down":   "法术↓",
    "deb_def_down":   "防↓",
    "deb_res_down":   "抗↓",
    "deb_spd_down":   "速↓",
    "deb_acc_down":   "命中↓",
    # 控制与其他
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

# ======================
# 文本正则（code -> patterns）
# 覆盖“必定暴击”“一或两次”“所受法术伤害减”“下回合命中时必定暴击”等表述
# ======================

# —— Buff —— #
BUFF_PATTERNS: Dict[str, List[str]] = {
    "buf_atk_up":   [r"攻击(提升|提高|上升|增加|加成|增强|提高了?)"],
    "buf_mag_up":   [r"(法术|魔法)(提升|提高|上升|增加|加成|增强|提高了?)"],
    "buf_spd_up":   [r"速度(提升|提高|上升|增加|加成|增强)|加速|迅捷"],
    "buf_def_up":   [r"防御(提升|提高|上升|增加|加成|增强)|护甲|硬化"],
    "buf_res_up":   [r"抗性(提升|提高|上升|增加|加成|增强)|抗性增强|减易伤"],
    "buf_acc_up":   [r"命中(率)?(提升|提高|上升|增加|加成|增强)"],
    "buf_crit_up":  [r"暴击(率|几率|概率)?(提升|提高|上升|增加|加成|增强)|会心|必定暴击"],
    "buf_heal":     [r"(回复|回复量|治疗|恢复)(自身|自身体力|HP|生命)?", r"给对手造成伤害的\s*1/2\s*回复"],
    # 护盾/减伤细分将由信号层再细化（护盾 vs 纯减伤）
    "buf_shield": [
        r"护盾",
        r"(所受|受到).*(法术)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减)",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)",
        r"保护|庇护",
    ],
    "buf_purify": [
        r"净化",
        r"(清除|消除|解除|去除|移除).*(自身|自我).*(负面|异常|减益|不良|状态)"
    ],
    "buf_immunity": [
        r"免疫(异常|控制|不良)状态?",
        r"(\d+|若干|[一二三四五六七八九十]+)回合.*免疫.*(异常|控制|不良)"
    ],
}

# —— Debuff —— #
DEBUFF_PATTERNS: Dict[str, List[str]] = {
    "deb_atk_down":   [r"攻击(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)"],
    "deb_mag_down":   [r"(法术|魔法)(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)"],
    "deb_def_down":   [r"防御(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)"],
    "deb_res_down":   [r"抗性(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)"],
    "deb_spd_down":   [r"速度(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)|减速"],
    "deb_acc_down":   [r"命中(率)?(下降|降低|减少|下?降\s*一级|下?降\s*两级|下降[一二两三四]级)"],
    "deb_stun":         [r"眩晕|昏迷"],
    "deb_bind":         [r"束缚|禁锢"],
    "deb_sleep":        [r"睡眠"],
    "deb_freeze":       [r"冰冻"],
    "deb_confuse_seal": [r"混乱|封印|禁技|无法使用技能"],
    "deb_suffocate":    [r"窒息"],
    "deb_dot":          [r"流血|中毒|灼烧|燃烧|腐蚀"],
    "deb_dispel": [
        r"(消除|驱散|清除).*(对方|对手|敌(人|方)).*(增益|强化|状态)",
        r"(消除|清除).*(对方|对手).*(加|提升).*(攻|攻击|法术|魔法).*(状态|效果)"
    ],
}

# —— Special —— #
SPECIAL_PATTERNS: Dict[str, List[str]] = {
    "util_first":        [r"先手|先制"],
    "util_multi":        [r"多段|连击|(\d+)[-~–](\d+)次|[二两三四五六七八九十]+连"],
    "util_pp_drain": [
        r"扣\s*PP",
        r"(随机)?减少.*(对方|对手).*(所有)?技能.*(使用)?次数(一|1|两|2|一或两|1或2)?次",
        r"(技能|使用)次数.*减少",
        r"使用次数.*减少",
        r"降(低)?技能次数"
    ],
    "util_reflect":      [r"反击|反伤|反弹|反馈给对手|反射伤害"],
    "util_charge_next":  [r"伤害加倍|威力加倍|威力倍增|下一回合.*(伤害|威力).*加倍|下回合.*必定暴击|命中时必定暴击|蓄力.*(强力|加倍|倍增)"],
    "util_penetrate":    [r"无视防御|破防|穿透(护盾|防御)"],
}

# ======================
# 工具
# ======================

def _text_of_skills(monster: Monster) -> str:
    parts: List[str] = []
    for s in (monster.skills or []):
        if s.name:
            parts.append(str(s.name))
        if s.description:
            parts.append(str(s.description))
    return " ".join(parts)

def _raw_six(monster: Monster) -> Tuple[float, float, float, float, float, float]:
    hp      = float(monster.hp or 0)
    speed   = float(monster.speed or 0)
    attack  = float(monster.attack or 0)
    defense = float(monster.defense or 0)
    magic   = float(monster.magic or 0)
    resist  = float(monster.resist or 0)
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

def _clip(v: float, lo: int = 0, hi: int = 120) -> int:
    return int(max(lo, min(hi, round(v))))

# ======================
# 对外：三类建议 / 一维建议 / 定位 / 信号
# ======================

def suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    """
    返回 code 三类标签：
      {"buff":[...], "debuff":[...], "special":[...]}
    数值阈值增强：
      - speed>=110 -> buf_spd_up
      - attack>=115 -> buf_atk_up
      - magic>=115  -> buf_mag_up
      - resist>=110 -> buf_res_up
      - hp>=115 或 均防>=105 -> buf_def_up
    """
    hp, speed, attack, defense, magic, resist = _raw_six(monster)
    text = _text_of_skills(monster)

    buff = set(_detect(BUFF_PATTERNS, text))
    debuff = set(_detect(DEBUFF_PATTERNS, text))
    special = set(_detect(SPECIAL_PATTERNS, text))

    # — 数值阈值增强 —
    if speed >= 110:
        buff.add("buf_spd_up")
    if attack >= 115:
        buff.add("buf_atk_up")
    if magic >= 115:
        buff.add("buf_mag_up")
    if resist >= 110:
        buff.add("buf_res_up")
    avg_def = (defense + magic) / 2.0 if (defense or magic) else 0.0
    if hp >= 115 or avg_def >= 105:
        buff.add("buf_def_up")

    return {
        "buff": sorted(buff),
        "debuff": sorted(debuff),
        "special": sorted(special),
    }

def suggest_tags_for_monster(monster: Monster) -> List[str]:
    """拍平为一维 code 列表，用于 Monster.tags 存库。"""
    g = suggest_tags_grouped(monster)
    flat: List[str] = []
    for cat in ("buff", "debuff", "special"):
        flat.extend(g[cat])
    # 去重保持顺序
    seen: Set[str] = set()
    out: List[str] = []
    for t in flat:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

def infer_role_for_monster(monster: Monster) -> str:
    hp, _speed, _atk, _def, _mag, resist = _raw_six(monster)
    g = suggest_tags_grouped(monster)

    offensive_hint = any(t in g["buff"] for t in ("buf_atk_up", "buf_mag_up")) or any(
        t in g["special"] for t in ("util_multi", "util_penetrate", "util_charge_next")
    )
    control_hint = any(t in g["debuff"] for t in (
        "deb_stun","deb_bind","deb_sleep","deb_freeze","deb_confuse_seal","deb_suffocate",
        "deb_spd_down","deb_acc_down",
    ))
    support_hint = any(t in g["buff"] for t in (
        "buf_heal","buf_shield","buf_purify","buf_immunity","buf_def_up","buf_res_up","buf_spd_up"
    ))
    tanky_hint = (hp >= 115) or (resist >= 115)

    if offensive_hint and not control_hint and not support_hint:
        return "主攻"
    if control_hint and not offensive_hint:
        return "控制"
    if support_hint and not offensive_hint:
        return "辅助"
    if tanky_hint and not offensive_hint:
        return "坦克"
    return "通用"

def extract_signals(monster: Monster) -> Dict[str, object]:
    """
    v1 兼容信号 + v2 细粒度信号（新增键不会影响旧用法）：
      - ctrl_count, slow_or_accuracy, has_multi_hit, has_crit_ignore, has_survive_buff, first_strike, speed_up, pp_hits
      - crit_up, ignore_def, armor_break, def_down, res_down, mark
      - heal, shield, dmg_reduce, cleanse_self, immunity, life_steal, def_up, res_up
      - hard_cc, soft_cc, extra_turn, action_bar, dispel_enemy, skill_seal, buff_steal
    """
    text = _text_of_skills(monster)
    g = suggest_tags_grouped(monster)

    # 基础集合
    flat_codes = {t for cat in g.values() for t in cat}
    deb = set(g["debuff"]); buf = set(g["buff"]); util = set(g["special"])

    # —— v1 兼容 —— #
    control_codes_basic = {"deb_stun","deb_bind","deb_sleep","deb_freeze","deb_confuse_seal","deb_suffocate"}
    ctrl_count = sum(1 for c in control_codes_basic if c in deb)
    slow_or_accuracy = ("deb_spd_down" in deb) or ("deb_acc_down" in deb)
    has_multi_hit = ("util_multi" in util)
    has_crit_or_penetrate = any(x in buf for x in ("buf_atk_up","buf_mag_up")) or ("util_penetrate" in util) \
                            or _hit_any([r"暴击", r"必中", r"无视防御", r"破防"], text)
    has_survive_buff = any(t in buf for t in ("buf_heal","buf_shield","buf_def_up","buf_res_up","buf_immunity"))
    first_strike = ("util_first" in util)
    speed_up = ("buf_spd_up" in buf)

    pp_hits = 0
    for p in SPECIAL_PATTERNS["util_pp_drain"]:
        pp_hits += len(re.findall(p, text))
    if pp_hits == 0 and ("util_pp_drain" in flat_codes):
        pp_hits = 1

    # —— v2 细粒度信号 —— #
    # 进攻类
    crit_up = ("buf_crit_up" in buf) or _hit_any([r"必定暴击", r"命中时必定暴击"], text)
    ignore_def = ("util_penetrate" in util) or _hit_any([r"无视防御", r"穿透(护盾|防御)"], text)
    armor_break = _hit(r"破防", text)  # 与 ignore_def 区分：破防 = 破甲效果
    def_down = ("deb_def_down" in deb)
    res_down = ("deb_res_down" in deb)
    mark = _hit_any([r"标记", r"易伤", r"暴露|曝露", r"破绽"], text)

    # 生存类
    heal = ("buf_heal" in buf) or _hit(r"(回复|治疗|恢复)", text)
    # 护盾 vs 纯减伤：二者都算，但分开记分
    shield = _hit(r"护盾|庇护|保护", text)
    dmg_reduce = _hit_any([
        r"(所受|受到).*(法术)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减(?!益))",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)"
    ], text)
    cleanse_self = ("buf_purify" in buf)
    immunity = ("buf_immunity" in buf) or _hit(r"免疫(异常|控制|不良)", text)
    life_steal = _hit_any([r"吸血", r"造成伤害.*(回复|恢复).*(自身|自我|HP)"], text)
    def_up = ("buf_def_up" in buf)
    res_up = ("buf_res_up" in buf)

    # 控制细分
    hard_cc_set = {"deb_stun","deb_sleep","deb_freeze","deb_bind"}
    soft_cc_set = {"deb_confuse_seal","deb_suffocate"}  # 按你的口径：混乱/封印/窒息偏软控
    hard_cc = sum(1 for c in hard_cc_set if c in deb)
    soft_cc = sum(1 for c in soft_cc_set if c in deb)

    # 先手/节奏
    extra_turn = _hit_any([
        r"(追加|额外|再度|再动|再次|连续).*(行动|回合)",
        r"(立即|立刻|马上).*(再次)?行动",
        r"再行动|再行动一次|额外回合"
    ], text)
    action_bar = _hit_any([
        r"行动条|行动值|先手值",
        r"(推进|提升|增加|降低|减少).*行动(条|值)",
        r"(推条|拉条)"
    ], text)

    # 压制/破阵
    dispel_enemy = ("deb_dispel" in deb)
    skill_seal = _hit_any([r"封印", r"禁技", r"无法使用技能", r"禁止使用技能"], text)
    buff_steal = _hit_any([r"(偷取|窃取|夺取).*(增益|强化|护盾)"], text)
    mark_expose = mark  # 统一用上面的 mark

    return {
        # v1 兼容
        "ctrl_count": int(ctrl_count),
        "slow_or_accuracy": bool(slow_or_accuracy),
        "has_multi_hit": bool(has_multi_hit),
        "has_crit_ignore": bool(has_crit_or_penetrate),
        "has_survive_buff": bool(has_survive_buff),
        "first_strike": bool(first_strike),
        "speed_up": bool(speed_up),
        "pp_hits": int(pp_hits),
        # v2 新信号
        "crit_up": bool(crit_up),
        "ignore_def": bool(ignore_def),
        "armor_break": bool(armor_break),
        "def_down": bool(def_down),
        "res_down": bool(res_down),
        "mark": bool(mark),
        "heal": bool(heal),
        "shield": bool(shield),
        "dmg_reduce": bool(dmg_reduce),
        "cleanse_self": bool(cleanse_self),
        "immunity": bool(immunity),
        "life_steal": bool(life_steal),
        "def_up_sig": bool(def_up),
        "res_up_sig": bool(res_up),
        "hard_cc": int(hard_cc),
        "soft_cc": int(soft_cc),
        "extra_turn": bool(extra_turn),
        "action_bar": bool(action_bar),
        "dispel_enemy": bool(dispel_enemy),
        "skill_seal": bool(skill_seal),
        "buff_steal": bool(buff_steal),
        "mark_expose": bool(mark_expose),
    }

# ======================
# v2：派生五维
# ======================

def derive(monster: Monster) -> Dict[str, int]:
    """
    五维（offense/survive/control/tempo/pp_pressure）
    - 全部：基础线性组合 + 信号加分
    - offense: 原始先封顶 130，再展示 clip 到 0–120；其他直接 clip 到 0–120
    """
    hp, spd, atk, dfe, mag, res = _raw_six(monster)
    s = extract_signals(monster)

    # 1) 攻 offense
    base_off = 0.55 * max(atk, mag) + 0.15 * min(atk, mag) + 0.20 * spd
    add_off = (
        10 * int(s.get("crit_up", False)) +
        12 * int(s.get("ignore_def", False)) +
         8 * int(s.get("has_multi_hit", False)) +
         6 * int(s.get("armor_break", False)) +
         4 * int(s.get("def_down", False)) +
         4 * int(s.get("res_down", False)) +
         3 * int(s.get("mark", False))
    )
    off_raw = base_off + add_off
    off_sort = min(130.0, off_raw)
    offense = _clip(off_sort, 0, 120)

    # 2) 生 survive
    base_sur = 0.45 * hp + 0.30 * dfe + 0.25 * res
    add_sur = (
        10 * int(s.get("heal", False)) +
        10 * int(s.get("shield", False)) +
         8 * int(s.get("dmg_reduce", False)) +
         5 * int(s.get("cleanse_self", False)) +
         4 * int(s.get("immunity", False)) +
         3 * int(s.get("life_steal", False)) +
         2 * int(s.get("def_up_sig", False)) +
         2 * int(s.get("res_up_sig", False))
    )
    survive = _clip(base_sur + add_sur, 0, 120)

    # 3) 控 control
    add_ctrl = (
        14 * int(s.get("hard_cc", 0)) +
         8 * int(s.get("soft_cc", 0)) +
         6 * int(s.get("slow_or_accuracy", False) and "deb_acc_down") +  # 兼容旧字段，单独加 acc_down
         6 * int(s.get("slow_or_accuracy", False) and "deb_acc_down" in [])  # 占位无效，下面单独读取
    )
    # 重新精确按键加分
    add_ctrl = (
        14 * int(s.get("hard_cc", 0)) +
         8 * int(s.get("soft_cc", 0)) +
         6 * int(s.get("slow_or_accuracy", False) and True) * 0  # 清零，占位
    )
    # 直接读取具体键
    acc_down_bonus = 6 * int(s.get("slow_or_accuracy", False) and s.get("ctrl_count", 0) >= 0)  # 保底构造
    # 单独明示：
    acc_down_bonus = 6 * int(bool(re.search(r"命中", _text_of_skills(monster))) and "deb_acc_down")  # 仅防误差（不计入）
    # 用专门键
    acc_down_bonus = 6 * int("deb_acc_down" in suggest_tags_grouped(monster)["debuff"])
    spd_down_bonus = 4 * int("deb_spd_down" in suggest_tags_grouped(monster)["debuff"])
    atk_down_bonus = 3 * int("deb_atk_down" in suggest_tags_grouped(monster)["debuff"])
    mag_down_bonus = 3 * int("deb_mag_down" in suggest_tags_grouped(monster)["debuff"])

    control = _clip(
        0.1 * spd +
        14 * int(s.get("hard_cc", 0)) +
         8 * int(s.get("soft_cc", 0)) +
        acc_down_bonus + spd_down_bonus + atk_down_bonus + mag_down_bonus,
        0, 120
    )

    # 4) 速 tempo
    tempo = _clip(
        1.0 * spd +
        15 * int(s.get("first_strike", False)) +
        10 * int(s.get("extra_turn", False)) +
         8 * int(s.get("speed_up", False)) +
         6 * int(s.get("action_bar", False)),
        0, 120
    )

    # 5) 压 pp_pressure
    pp_pressure = _clip(
        18 * int(s.get("pp_hits", 0) > 0) +
         5 * int(s.get("pp_hits", 0)) +
         8 * int(s.get("dispel_enemy", False)) +
        10 * int(s.get("skill_seal", False)) +
         6 * int(s.get("buff_steal", False)) +
         3 * int(s.get("mark_expose", False)),
        0, 120
    )

    return {
        "offense": offense,
        "survive": survive,
        "control": control,
        "tempo": tempo,
        "pp_pressure": pp_pressure,
    }

__all__ = [
    "BUFF_CANON", "DEBUFF_CANON", "SPECIAL_CANON",
    "CODE2CN", "CN2CODE",
    "suggest_tags_grouped", "suggest_tags_for_monster",
    "infer_role_for_monster", "extract_signals",
    "derive",
]