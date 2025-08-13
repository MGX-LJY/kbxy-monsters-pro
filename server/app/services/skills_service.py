# server/app/services/skills_service.py
from __future__ import annotations

import re
from typing import List, Tuple, Iterable, Set, Optional

from sqlalchemy.orm import Session
from sqlalchemy import select

from ..models import Skill


# ============== 文本判定 & 轻量标签（保持原有能力） ==============

# 关键词 -> 标签（可继续扩充）
KEYWORD_TAGS: list[tuple[str, str]] = [
    (r"先手", "先手"),
    (r"消除.*(增益|加成)", "驱散"),
    (r"(去除|消除).*(负面|异常)", "净化"),
    (r"(速度|速).*提高|加速", "加速"),
    (r"速度.*下降|降速", "降速"),
    (r"攻击.*提高|加攻", "加攻"),
    (r"防御.*提高|加防", "加防"),
    (r"(抗性|抗).*提高|加抗", "加抗"),
    (r"(法术|魔).*提高|加法", "加法"),
    (r"命中.*下降", "降命"),
    (r"攻击.*下降|降攻", "降攻"),
    (r"防御.*下降|降防", "降防"),
    (r"(抗性|抗).*下降|降抗", "降抗"),
    (r"(窒息|混乱|眩晕|束缚)", "控制"),
    (r"(回复|吸收).*HP|吸血", "回复"),
    (r"免疫.*异常", "免疫异常"),
    (r"伤害.*减半|减伤", "减伤"),
    (r"(明王咒|下回合.*加倍|蓄力)", "蓄力"),
    (r"(技能的使用次数.*减少|PP.*减少|耗尽)", "耗PP"),
    (r"反弹|反馈", "反伤"),
    (r"暴击", "暴击"),
]

TRIVIAL_DESCS = {"", "0", "1", "-", "—", "无", "暂无", "null", "none", "N/A", "n/a"}


def _clean(s: Optional[str]) -> str:
    return (s or "").strip()


def _is_meaningful_desc(s: str) -> bool:
    s = _clean(s)
    if s.lower() in TRIVIAL_DESCS:
        return False
    return (
        len(s) >= 6
        or re.search(r"[，。；、,.]", s)
        or re.search(r"(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)", s)
    )


def _is_valid_skill_name(name: str) -> bool:
    """至少包含一个中文或英文字母；排除纯数字/连字符等（如 '1', '-', '—'）。"""
    s = _clean(name)
    if not s:
        return False
    if re.fullmatch(r"[\d\-\—\s]+", s):
        return False
    return bool(re.search(r"[\u4e00-\u9fffA-Za-z]", s))


def derive_tags_from_texts(texts: Iterable[str]) -> Set[str]:
    merged = "；".join([_clean(t) for t in texts if _clean(t)])
    tags: set[str] = set()
    for pat, tag in KEYWORD_TAGS:
        if re.search(pat, merged):
            tags.add(tag)
    return tags


# ============== 统一化（element/kind/power） ==============

def _norm_element(elem: Optional[str]) -> Optional[str]:
    """轻量统一：只做裁剪；空串 -> None。若后续需要，可在此做映射。"""
    e = _clean(elem)
    return e or None


def _norm_kind(kind: Optional[str]) -> Optional[str]:
    """轻量统一类型字段：物理/法术/特殊（含若干同义裁剪）。"""
    k = _clean(kind)
    if not k:
        return None
    # 同义修正（尽量保守）
    if k in {"物攻", "物理系", "物理"}:
        return "物理"
    if k in {"法攻", "魔法", "魔攻", "法伤", "法术系", "法术"}:
        return "法术"
    if k in {"变化", "辅助", "异常", "特性", "特殊"}:
        return "特殊"
    return k


def _norm_power(power: Optional[int | str]) -> Optional[int]:
    """转为 int；不可用则 None。"""
    if power is None:
        return None
    if isinstance(power, int):
        return power
    s = _clean(str(power))
    if not s:
        return None
    m = re.search(r"-?\d+", s)
    return int(m.group()) if m else None


# ============== 核心：按 (name, element, kind, power) 唯一 upsert ==============

def upsert_skills(
    db: Session,
    items: List[Tuple[str, Optional[str], Optional[str], Optional[int], Optional[str]]],
) -> List[Skill]:
    """
    批量 upsert 技能，唯一键为 (name, element, kind, power)。

    参数
    ----
    items : List[Tuple[name, element, kind, power, description]]
        - name: 技能名（必填）
        - element: 技能属性（可空）
        - kind: 技能类型：物理/法术/特殊（可空）
        - power: 技能威力（可空）
        - description: 技能描述（可空）

    策略
    ----
    - 过滤无效技能名（纯数字/标点等）。
    - 查询条件：Skill.name == name AND Skill.element == element AND Skill.kind == kind AND Skill.power == power
    - 不存在则创建；存在则仅在“新描述更像描述或更长”时覆盖旧描述。
    - 返回所有成功入库（新建或找到）的 Skill 实体，供上层关系绑定。
    """
    results: List[Skill] = []

    for name, element, kind, power, desc in items:
        name = _clean(name)
        if not _is_valid_skill_name(name):
            continue

        element = _norm_element(element)
        kind = _norm_kind(kind)
        power = _norm_power(power)
        desc = _clean(desc)

        # 查找唯一键命中
        stmt = select(Skill).where(
            Skill.name == name,
            Skill.element == element,
            Skill.kind == kind,
            Skill.power == power,
        )
        skill = db.execute(stmt).scalar_one_or_none()

        if not skill:
            # 新建：仅在描述“像描述”时保存，否则给空串
            skill = Skill(
                name=name,
                element=element,
                kind=kind,
                power=power,
                description=desc if _is_meaningful_desc(desc) else "",
            )
            db.add(skill)
            db.flush()  # 拿到 id
        else:
            # 更新策略：新描述更“像描述”，或（两者都像描述但新更长）才覆盖
            if _is_meaningful_desc(desc):
                old = _clean(skill.description)
                if (not _is_meaningful_desc(old)) or (len(desc) > len(old)):
                    skill.description = desc

        results.append(skill)

    return results