from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from ..db import SessionLocal
from ..models import Skill, Monster
import re

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

TRIVIAL = {"", "0", "1", "-", "—", "无", "暂无", "null", "none", "n/a", "N/A"}

def _invalid_name(name: str) -> bool:
    s = (name or "").strip()
    return (not s) or bool(re.fullmatch(r"[\d\-\—\s]+", s))

def _is_suspicious_desc(desc: str, summary_set: set[str]) -> bool:
    """把像 summary 的描述视为可清理目标"""
    if not desc:
        return False
    d = desc.strip()
    if d.lower() in TRIVIAL:
        return True
    # 与任意 monster 的 summary 完全相同
    if d in summary_set:
        return True
    # 一些更像评价/总结的词汇（尽量保守）
    bad_kw = ("主攻", "辅助", "比较均衡", "可以", "不错", "非常", "克星", "种族值", "做一个", "生存能力")
    if any(k in d for k in bad_kw) and not re.search(r"(命中|回合|几率|造成|伤害|提高|降低|免疫|状态|先手|消除|PP|倍|持续)", d):
        return True
    return False

@router.get("/admin/skills/stats")
def skills_stats(db: Session = Depends(get_db)):
    total = db.query(func.count(Skill.id)).scalar() or 0
    with_desc = db.query(func.count(Skill.id)).filter(Skill.description.isnot(None), Skill.description != "").scalar() or 0
    # 收集 summary 集合用于“疑似”判定
    summaries = set()
    for m in db.query(Monster).all():
        ex = (m.explain_json or {})
        s = (ex.get("summary") or "").strip()
        if s:
            summaries.add(s)
    suspicious = 0
    for s in db.query(Skill).filter(Skill.description.isnot(None), Skill.description != "").all():
        if _is_suspicious_desc(s.description or "", summaries):
            suspicious += 1
    return {
        "total_skills": total,
        "with_description": with_desc,
        "suspicious_description": suspicious,
    }

@router.post("/admin/skills/clear_descriptions")
def clear_descriptions(mode: str = Query("suspicious", regex="^(suspicious|all)$"), db: Session = Depends(get_db)):
    """
    mode=suspicious: 只清理疑似由 summary 误写入的描述（推荐）
    mode=all: 清空所有技能描述（清空后建议立刻重新导入 CSV 回填）
    """
    changed = 0
    if mode == "all":
        q = db.query(Skill).filter(Skill.description.isnot(None), Skill.description != "")
        for s in q.all():
            s.description = ""
            db.add(s)
            changed += 1
        db.commit()
        return {"mode": mode, "changed": changed}

    # suspicious
    summaries = set()
    for m in db.query(Monster).all():
        ex = (m.explain_json or {})
        s = (ex.get("summary") or "").strip()
        if s:
            summaries.add(s)

    q = db.query(Skill).filter(Skill.description.isnot(None), Skill.description != "")
    for s in q.all():
        if _is_suspicious_desc(s.description or "", summaries):
            s.description = ""
            db.add(s)
            changed += 1
    db.commit()
    return {"mode": mode, "changed": changed, "summary_candidates": len(summaries)}

@router.post("/admin/skills/scrub_names")
def scrub_invalid_skill_names(db: Session = Depends(get_db)):
    skills = db.query(Skill).all()
    removed = 0
    for s in skills:
        if _invalid_name(s.name):
            s.monsters.clear()  # 解除关联
            db.delete(s)
            removed += 1
    db.commit()
    return {"removed": removed, "total": len(skills)}