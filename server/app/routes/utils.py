# server/app/routes/utils.py
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re

router = APIRouter()

class ExtractReq(BaseModel):
    text: str

class ExtractRespSkill(BaseModel):
    name: str
    description: str

class ExtractResp(BaseModel):
    skills: list[ExtractRespSkill]

def _meaningful_desc(s: str) -> bool:
    t = (s or "").strip()
    if not t or t.lower() in {"0","1","-","—","无","暂无","null","none","n/a","N/A"}:
        return False
    return (len(t) >= 6 or
            re.search(r"[，。；、,.]", t) or
            re.search(r"(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)", t))

@router.post("/utils/extract_skills", response_model=ExtractResp)
def extract_skills(payload: ExtractReq):
    """
    适配示例：
    岚羽箭雕 115 113 120 107 96 94  疾袭贯羽 72 风 物理 165 5 无视对手防御提升的效果，若本次攻击造成的伤害小于300，则令对方速度下降两级
    结果：name=疾袭贯羽, description=无视对手防御提升的效果...
    """
    text = (payload.text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="empty text")

    # 1) 找出前 6 个数字（六维），并定位到其后
    nums = list(re.finditer(r"\d+", text))
    pos = 0
    if len(nums) >= 6:
        pos = nums[5].end()  # 第6个数字结束的位置

    tail = text[pos:].strip() or text  # 没找到也用全文兜底

    # 2) 找技能名（第一个长度≥2的中文词）
    m_name = re.search(r"[\u4e00-\u9fff]{2,20}", tail)
    if not m_name:
        # 兜底：在全文里找
        m_name = re.search(r"[\u4e00-\u9fff]{2,20}", text)
    if not m_name:
        return {"skills": []}

    name = m_name.group(0)
    after = tail[m_name.end():]

    # 3) 去掉常见前缀垃圾（元素/类型/威力/PP/冷却/数字等）
    junk_prefix = r"""
        ^\s*
        (?:
            \d+|
            [风火水木金土冰雷毒岩光暗普]|        # 元素/属性简写
            (?:物理|法术|特殊|状态|类型)|          # 类型词
            (?:威力|PP|耗能|冷却|cd|CD|命中率?)   # 常见字段
        )
        [:：]?
        \s*
    """
    # 多剥几次
    for _ in range(6):
        after = re.sub(junk_prefix, "", after, flags=re.X)

    desc = after.strip()
    if not _meaningful_desc(desc):
        # 兜底：从原文里找第一个像描述的句子
        m_desc = re.search(r"(无视|若|当|命中|使|令|提高|降低|回复|免疫|伤害|回合|几率|状态).{4,}", text)
        if m_desc:
            desc = m_desc.group(0).strip()

    if not _meaningful_desc(desc):
        return {"skills": [{"name": name, "description": ""}]}

    return {"skills": [{"name": name, "description": desc}]}