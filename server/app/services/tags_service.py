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
    "deb_atk_down":     "攻↓",
    "deb_mag_down":     "法术↓",
    "deb_def_down":     "防↓",
    "deb_res_down":     "抗↓",
    "deb_spd_down":     "速↓",
    "deb_acc_down":     "命中↓",
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
# 通用片段（用于 rf"" 拼装）
# ======================

CN_NUM = r"[一二两三四五六七八九十百千]+"
SELF   = r"(?:自身|自我|自己|本方|我方)"
ENEMY  = r"(?:对方|对手|敌(?:人|方))"
UP     = r"(?:提升|提高|上升|增强|增加|加成|升高|强化)"
DOWN   = r"(?:下降|降低|减少|衰减|减弱)"
LEVEL  = rf"(?:\s*(?:{CN_NUM}|\d+)\s*级)?"
ONE_OR_TWO = r"(?:一|1|两|2|一或两|1或2|1-2|1～2|1~2)"
SEP    = r"(?:\s*[、，,/和与及]+\s*)"   # 列表分隔符

# ======================
# 文本正则（code -> patterns）
# Buff 必须出现 SELF 以避免把“对方加攻/加防”识别成己方增益；
# 支持“X、Y 各提高/各下降”并列句式。
# ======================

# —— Buff —— #
BUFF_PATTERNS: Dict[str, List[str]] = {
    # 攻击 ↑
    "buf_atk_up": [
        rf"{SELF}.*?攻击.*?{UP}",
        rf"{UP}.*?{SELF}.*?攻击",
        rf"攻击(?:{SEP}(?:法术|魔法|防御|速度|抗性|命中率|暴击率))*?各{UP}{LEVEL}",
        rf"有\d+%?机会.*?{UP}.*?{SELF}.*?攻击",
    ],
    # 法术 ↑
    "buf_mag_up": [
        rf"{SELF}.*?(法术|魔法).*?{UP}",
        rf"{UP}.*?{SELF}.*?(法术|魔法)",
        rf"(法术|魔法)(?:{SEP}(?:攻击|防御|速度|抗性|命中率|暴击率))*?各{UP}{LEVEL}",
        rf"有\d+%?机会.*?{UP}.*?{SELF}.*?(法术|魔法)",
    ],
    # 速度 ↑
    "buf_spd_up": [
        rf"{SELF}.*?速度.*?{UP}|{SELF}.*?(加速|迅捷|敏捷提升|加快速度)",
        rf"{UP}.*?{SELF}.*?速度",
        rf"速度(?:{SEP}(?:攻击|防御|法术|魔法|抗性))*?各{UP}{LEVEL}",
    ],
    # 防御 ↑
    "buf_def_up": [
        rf"{SELF}.*?(防御|防御力).*?{UP}|{SELF}.*?(护甲|硬化|铁壁)",
        rf"{UP}.*?{SELF}.*?(防御|防御力)",
        rf"(防御|防御力)(?:{SEP}(?:攻击|法术|魔法|速度|抗性))*?各{UP}{LEVEL}",
    ],
    # 抗性 ↑
    "buf_res_up": [
        rf"{SELF}.*?(抗性|抗性值).*?{UP}|{SELF}.*?抗性增强|{SELF}.*?减易伤",
        rf"{UP}.*?{SELF}.*?(抗性|抗性值)",
        rf"(抗性|抗性值)(?:{SEP}(?:攻击|防御|速度|法术|魔法))*?各{UP}{LEVEL}",
    ],
    # 命中 ↑（只认“命中率↑”，不吃“命中时必定暴击”）
    "buf_acc_up": [
        rf"{SELF}.*?命中率.*?{UP}",
        rf"{UP}.*?{SELF}.*?命中率",
        rf"命中率(?:{SEP}(?:暴击率|攻击|防御|速度|抗性|法术|魔法))*?各{UP}{LEVEL}",
    ],
    # 暴击 ↑（允许“必定暴击/命中时必定暴击”视为暴击强化）
    "buf_crit_up": [
        rf"{SELF}.*?(暴击|暴击率|会心).*?{UP}",
        rf"(必定暴击|命中时必定暴击)",
        rf"{UP}.*?{SELF}.*?(暴击|暴击率|会心)",
        rf"暴击率(?:{SEP}(?:命中率|攻击|防御|速度|抗性|法术|魔法))*?各{UP}{LEVEL}",
    ],
    # 治疗/回复
    "buf_heal": [
        rf"(回复|治疗|恢复).*?({SELF}|自身体力|自身HP|自身生命|自身最大血量)",
        r"给对手造成伤害的\s*1/2\s*回复",
        r"(?:[一二三四五六七八九十]|\d+)\s*回合内.*?每回合.*?(回复|恢复)",
    ],
    # 护盾/减伤
    "buf_shield": [
        r"护盾|护体|结界",
        r"(所受|受到).*(法术|物理)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减)(?!.*敌方)",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)|庇护|保护",
    ],
    # 自净
    "buf_purify": [
        r"净化",
        rf"(清除|消除|解除|去除|移除).*?{SELF}.*?(负面|异常|减益|不良|状态)",
        rf"(将|把).*?{SELF}.*?(负面|异常|减益).*?(转移|移交).*?{ENEMY}",
    ],
    # 免疫异常
    "buf_immunity": [
        r"免疫(异常|控制|不良)状态?",
        r"([一二三四五六七八九十]+|\d+)\s*回合.*?免疫.*?(异常|控制|不良)",
    ],
}

# —— Debuff —— #
DEBUFF_PATTERNS: Dict[str, List[str]] = {
    # 属性下降（支持数字/中文数字 + “各下降”并列）
    "deb_atk_down": [
        rf"(?:{ENEMY}.*?)?攻击{DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?攻击{LEVEL}",
        rf"攻击(?:{SEP}(?:防御|速度|法术|魔法|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_mag_down": [
        rf"(?:{ENEMY}.*?)?(法术|魔法){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(法术|魔法){LEVEL}",
        rf"(法术|魔法)(?:{SEP}(?:攻击|防御|速度|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_def_down": [
        rf"(?:{ENEMY}.*?)?(防御|防御力){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(防御|防御力){LEVEL}",
        rf"(防御|防御力)(?:{SEP}(?:攻击|法术|魔法|速度|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_res_down": [
        rf"(?:{ENEMY}.*?)?(抗性|抗性值){DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?(抗性|抗性值){LEVEL}",
        rf"(抗性|抗性值)(?:{SEP}(?:攻击|防御|速度|法术|魔法|命中率))*?各{DOWN}{LEVEL}",
    ],
    "deb_spd_down": [
        rf"(?:{ENEMY}.*?)?速度{DOWN}{LEVEL}|减速",
        rf"{DOWN}.*?{ENEMY}.*?速度{LEVEL}",
        rf"速度(?:{SEP}(?:攻击|防御|法术|魔法|抗性|命中率))*?各{DOWN}{LEVEL}",
    ],
    # 命中↓：只认“命中率”，避免“命中时…”
    "deb_acc_down": [
        rf"(?:{ENEMY}.*?)?命中率{DOWN}{LEVEL}",
        rf"{DOWN}.*?{ENEMY}.*?命中率{LEVEL}",
        rf"命中率(?:{SEP}(?:攻击|防御|速度|法术|魔法|抗性))*?各{DOWN}{LEVEL}",
    ],
    # 控制与异常
    "deb_stun":           [r"眩晕|昏迷"],
    "deb_bind":           [r"束缚|禁锢"],
    "deb_sleep":          [r"睡眠"],
    "deb_freeze":         [r"冰冻"],
    # “禁物攻/禁技/无法使用技能”
    "deb_confuse_seal":   [r"混乱|封印|禁技|无法使用技能|禁止使用技能|不能使用物理攻击|禁用物理攻击"],
    "deb_suffocate":      [r"窒息"],
    # DOT（含“灼伤”）
    "deb_dot":            [r"流血|中毒|灼烧|燃烧|腐蚀|灼伤"],
    # 敌方增益驱散（含“消除对方所有增益效果”“消除对手加攻加防状态”）
    "deb_dispel": [
        rf"(消除|驱散|清除).*?{ENEMY}.*?(增益|强化|状态)",
        rf"(消除|清除).*?{ENEMY}.*?(加|提升).*?(攻|攻击|法术|魔法|防御|速度).*(状态|效果)",
        r"消除对方所有增益效果",
    ],
}

# —— Special —— #
SPECIAL_PATTERNS: Dict[str, List[str]] = {
    "util_first":        [r"先手|先制"],
    "util_multi":        [r"多段|连击|(\d+)[-~–](\d+)次|[二两三四五六七八九十]+连"],
    # PP 压制：随机/所有技能/一次/一或两次/1次等
    "util_pp_drain": [
        r"扣\s*PP",
        rf"(随机)?减少.*?{ENEMY}.*?(所有)?技能.*?(使用)?次数{ONE_OR_TWO}?次",
        r"(技能|使用)次数.*?减少",
        r"使用次数.*?减少",
        r"降(低)?技能次数",
    ],
    # 反击/反伤/反馈
    "util_reflect":      [r"反击|反伤|反弹|反馈给对手|反射伤害"],
    # 下一击强化/伤害加倍/蓄力/触发暴击
    "util_charge_next":  [r"伤害加倍|威力加倍|威力倍增|下一回合.*?(伤害|威力).*?加倍|下回合.*?必定暴击|命中时必定暴击|蓄力.*?(强力|加倍|倍增)"],
    # 穿透/无视防御/破防
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

# ======================
# 对外：三类建议 / 一维建议 / 定位 / 信号
# ======================

def suggest_tags_grouped(monster: Monster) -> Dict[str, List[str]]:
    """
    返回 code 三类标签：
      {"buff":[...], "debuff":[...], "special":[...]}
    注意：不再注入阈值型增益（speed/attack/magic/resist/hp 等），
         阈值仅用于派生五维计算；展示标签仅根据技能文本匹配。
    """
    text = _text_of_skills(monster)
    buff = set(_detect(BUFF_PATTERNS, text))
    debuff = set(_detect(DEBUFF_PATTERNS, text))
    special = set(_detect(SPECIAL_PATTERNS, text))
    return {
        "buff": sorted(buff),
        "debuff": sorted(debuff),
        "special": sorted(special),
    }

def suggest_tags_for_monster(monster: Monster) -> List[str]:
    """拍平为一维 code 列表，用于 Monster.tags 存库（仅文本匹配结果）。"""
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
    """
    极简定位（只依赖文本标签；不使用阈值注入）：
      - 主攻：有 buf_atk_up/buf_mag_up 或 util_multi/util_penetrate/util_charge_next，且非明显控制/纯辅助
      - 控制：有任一控制 debuff 或 deb_spd_down / deb_acc_down
      - 辅助：有治疗/护盾/净化/免疫/防/抗/速 等，而无明显主攻特征
      - 坦克：血量或抗性很高而非主攻（此处仅作兜底）
    """
    hp, _speed, _atk, _def, _mag, resist = _raw_six(monster)
    g = suggest_tags_grouped(monster)

    offensive_hint = any(t in g["buff"] for t in ("buf_atk_up", "buf_mag_up")) \
        or any(t in g["special"] for t in ("util_multi", "util_penetrate", "util_charge_next"))
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
    v2 细粒度信号（仅保留派生所需）：
      - 进攻：crit_up / ignore_def / armor_break / def_down / res_down / mark / has_multi_hit
      - 生存：heal / shield / dmg_reduce / cleanse_self / immunity / life_steal / def_up_sig / res_up_sig
      - 控制：hard_cc / soft_cc
      - 节奏：first_strike / speed_up / extra_turn / action_bar
      - 压制：pp_hits / dispel_enemy / skill_seal / buff_steal / mark_expose
    """
    text = _text_of_skills(monster)
    g = suggest_tags_grouped(monster)
    deb = set(g["debuff"]); buf = set(g["buff"]); util = set(g["special"])

    # 进攻
    crit_up = ("buf_crit_up" in buf) or _hit_any([r"必定暴击", r"命中时必定暴击"], text)
    ignore_def = ("util_penetrate" in util) or _hit_any([r"无视防御", r"穿透(护盾|防御)"], text)
    armor_break = _hit(r"破防", text)
    def_down = ("deb_def_down" in deb)
    res_down = ("deb_res_down" in deb)
    mark = _hit_any([r"标记", r"易伤", r"(暴|曝)露", r"破绽"], text)
    has_multi_hit = ("util_multi" in util)

    # 生存
    heal = ("buf_heal" in buf) or _hit(r"(回复|治疗|恢复)", text)
    shield = _hit(r"护盾|庇护|保护|结界|护体", text)
    dmg_reduce = _hit_any([
        r"(所受|受到).*(法术|物理)?伤害.*(减少|降低|减半|减免|降低\d+%|减少\d+%|减(?!益))",
        r"伤害(减少|降低|减半|减免|降低\d+%|减少\d+%)",
        r"减伤(?!.*敌方)"
    ], text)
    cleanse_self = ("buf_purify" in buf)
    immunity = ("buf_immunity" in buf) or _hit(r"免疫(异常|控制|不良)", text)
    life_steal = _hit_any([r"吸血", r"造成伤害.*(回复|恢复).*(自身|自我|HP)"], text)
    def_up_sig = ("buf_def_up" in buf)
    res_up_sig = ("buf_res_up" in buf)

    # 控制
    hard_cc_set = {"deb_stun","deb_sleep","deb_freeze","deb_bind"}
    soft_cc_set = {"deb_confuse_seal","deb_suffocate"}
    hard_cc = sum(1 for c in hard_cc_set if c in deb)
    soft_cc = sum(1 for c in soft_cc_set if c in deb)

    # 节奏
    first_strike = ("util_first" in util)
    speed_up = ("buf_spd_up" in buf)
    extra_turn = _hit_any([
        r"(追加|额外|再度|再动|再次|连续).*(行动|回合)",
        r"(立即|立刻|马上).*(再次)?行动",
        r"再行动(一次)?|额外回合"
    ], text)
    action_bar = _hit_any([
        r"行动条|行动值|先手值",
        r"(推进|提升|增加|降低|减少).*行动(条|值)",
        r"(推条|拉条)"
    ], text)

    # 压制
    pp_hits = 0
    for p in SPECIAL_PATTERNS["util_pp_drain"]:
        pp_hits += len(re.findall(p, text))
    if pp_hits == 0 and ("util_pp_drain" in util):
        pp_hits = 1
    dispel_enemy = ("deb_dispel" in deb)
    skill_seal = _hit_any([r"封印", r"禁技", r"无法使用技能", r"禁止使用技能"], text)
    buff_steal = _hit_any([r"(偷取|窃取|夺取).*(增益|强化|护盾)"], text)
    mark_expose = mark

    return {
        "crit_up": bool(crit_up),
        "ignore_def": bool(ignore_def),
        "armor_break": bool(armor_break),
        "def_down": bool(def_down),
        "res_down": bool(res_down),
        "mark": bool(mark),
        "has_multi_hit": bool(has_multi_hit),

        "heal": bool(heal),
        "shield": bool(shield),
        "dmg_reduce": bool(dmg_reduce),
        "cleanse_self": bool(cleanse_self),
        "immunity": bool(immunity),
        "life_steal": bool(life_steal),
        "def_up_sig": bool(def_up_sig),
        "res_up_sig": bool(res_up_sig),

        "hard_cc": int(hard_cc),
        "soft_cc": int(soft_cc),

        "first_strike": bool(first_strike),
        "speed_up": bool(speed_up),
        "extra_turn": bool(extra_turn),
        "action_bar": bool(action_bar),

        "pp_hits": int(pp_hits),
        "dispel_enemy": bool(dispel_enemy),
        "skill_seal": bool(skill_seal),
        "buff_steal": bool(buff_steal),
        "mark_expose": bool(mark_expose),
    }

# ======================
# v2：派生五维（保留给需要直接调用 derive 的地方）
# ======================

def derive(monster: Monster) -> Dict[str, int]:
    """
    五维（offense/survive/control/tempo/pp_pressure）
    - 线性基底 + 信号加分；展示层 clip 到 [0,120]（offense 内部 130 用于排序可选）
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
    offense = int(max(0, min(120, round(off_sort))))

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
    survive = int(max(0, min(120, round(base_sur + add_sur))))

    # 3) 控 control
    acc_down_bonus = 6 * int("deb_acc_down" in suggest_tags_grouped(monster)["debuff"])
    spd_down_bonus = 4 * int("deb_spd_down" in suggest_tags_grouped(monster)["debuff"])
    atk_down_bonus = 3 * int("deb_atk_down" in suggest_tags_grouped(monster)["debuff"])
    mag_down_bonus = 3 * int("deb_mag_down" in suggest_tags_grouped(monster)["debuff"])

    control = int(max(0, min(120, round(
        0.1 * spd +
        14 * int(s.get("hard_cc", 0)) +
         8 * int(s.get("soft_cc", 0)) +
        acc_down_bonus + spd_down_bonus + atk_down_bonus + mag_down_bonus
    ))))

    # 4) 速 tempo
    tempo = int(max(0, min(120, round(
        1.0 * spd +
        15 * int(s.get("first_strike", False)) +
        10 * int(s.get("extra_turn", False)) +
         8 * int(s.get("speed_up", False)) +
         6 * int(s.get("action_bar", False)
    )))))

    # 5) 压 pp_pressure
    pp_pressure = int(max(0, min(120, round(
        18 * int(s.get("pp_hits", 0) > 0) +
         5 * int(s.get("pp_hits", 0)) +
         8 * int(s.get("dispel_enemy", False)) +
        10 * int(s.get("skill_seal", False)) +
         6 * int(s.get("buff_steal", False)) +
         3 * int(s.get("mark_expose", False))
    ))))

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