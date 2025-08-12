# server/app/routes/tags.py
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, selectinload
import re
from typing import Set, List
from ..db import SessionLocal
from ..models import Monster

router = APIRouter()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# 规则与词典（可按需增删）
ELEMENT_MAP = {
    '风': '风系', '火': '火系', '水': '水系', '金': '金系', '木': '木系', '土': '土系',
    '雷': '雷系', '冰': '冰系', '毒': '毒系', '妖': '妖系', '光': '光系', '暗': '暗系', '音': '音系'
}
ROLE_MAP = {'主攻':'输出','控制':'控制','辅助':'辅助','坦克':'坦克','通用':'通用'}

REGEX_TAGS = [
    (r'先手|优先|超先', '先手'),
    (r'连击|2~3|3~6|多段', '多段'),
    (r'昏迷|麻痹|睡眠|封印|束缚|石化|眩晕', '控制'),
    (r'回复|治疗|恢复|吸取', '回复'),
    (r'暴击|会心', '暴击'),
    (r'无视.*防御|穿透|破防', '破防'),
    (r'提高.*速度|速度.*提升|提速', '提速'),
    (r'降低.*速度|速度.*下降|减速', '减速'),
    (r'提高.*命中|命中.*提升', '命中↑'),
    (r'降低.*命中|命中.*下降', '命中↓'),
    (r'免疫', '免疫'),
    (r'降低.*攻击|攻.*下降', '降攻'),
    (r'提高.*攻击|攻.*提升', '增攻'),
    (r'降低.*防御|防.*下降|破甲', '破甲'),
    (r'提高.*防御|防.*提升|减伤|护盾', '增防'),
]

def _smart_add(tags: Set[str], tag: str):
    if tag: tags.add(tag)

def suggest_from_stats(m, tags: Set[str]):
    raw = (m.explain_json or {}).get('raw_stats') if getattr(m, 'explain_json', None) else None
    # 取“原始六维”，没有就用基础列回退
    hp = (raw or {}).get('hp', m.base_survive or 0)
    spd = (raw or {}).get('speed', m.base_tempo or 0)
    atk = (raw or {}).get('attack', m.base_offense or 0)
    # 这两个若无“原始六维”，只能用 base_control 近似
    defe = (raw or {}).get('defense', m.base_control or 0)
    mag = (raw or {}).get('magic', m.base_control or 0)
    resi = (raw or {}).get('resist', m.base_pp or 0)

    if atk >= 120: _smart_add(tags, '高攻')
    if spd >= 110: _smart_add(tags, '高速')
    if hp >= 110: _smart_add(tags, '厚血')
    if defe >= 110 or mag >= 110 or resi >= 110: _smart_add(tags, '高耐久')
    if resi == 0: _smart_add(tags, '无抗')
    # 简单组合
    if atk >= 120 and spd >= 110: _smart_add(tags, '先手输出')

def suggest_from_text(text: str, tags: Set[str]):
    for pat, lab in REGEX_TAGS:
        if re.search(pat, text):
            _smart_add(tags, lab)

@router.post("/monsters/{monster_id}/suggest_tags")
def suggest_tags(monster_id: int, db: Session = Depends(get_db)):
    # 带技能一起查
    m = db.query(Monster).options(selectinload(Monster.skills)).get(monster_id)
    if not m:
        raise HTTPException(404, "monster not found")

    tags: Set[str] = set()

    # 元素、定位
    if m.element and m.element in ELEMENT_MAP:
        tags.add(ELEMENT_MAP[m.element])
    if m.role and m.role in ROLE_MAP:
        tags.add(ROLE_MAP[m.role])

    # 基于六维
    suggest_from_stats(m, tags)

    # 基于名称+技能文本
    blob = [m.name_final or '', m.element or '', m.role or '']
    for s in (m.skills or []):
        blob.append((s.name or '') + ' ' + (s.description or ''))
    big = ' '.join(blob)
    suggest_from_text(big, tags)

    # 返回按字典序稳定排序
    return {"tags": sorted(tags)}