from typing import List, Tuple, Iterable, Set
import re
from sqlalchemy.orm import Session
from sqlalchemy import select
from ..models import Skill

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

def derive_tags_from_texts(texts: Iterable[str]) -> Set[str]:
    merged = "；".join([t for t in texts if t])
    tags: set[str] = set()
    for pat, tag in KEYWORD_TAGS:
        if re.search(pat, merged):
            tags.add(tag)
    return tags

def upsert_skills(db: Session, items: List[Tuple[str, str]]):
    """items: [(skill_name, description)]"""
    result: list[Skill] = []
    for name, desc in items:
        name = (name or "").strip()
        if not name:
            continue
        skill = db.execute(select(Skill).where(Skill.name == name)).scalar_one_or_none()
        if not skill:
            skill = Skill(name=name, description=desc or "")
            db.add(skill)
            db.flush()
        else:
            if (desc or "") and not skill.description:
                skill.description = desc or ""
        result.append(skill)
    return result