from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
import re
from typing import List, Optional

router = APIRouter()

# ====== I/O 模型 ======
class ExtractReq(BaseModel):
  text: str

class ExtractSkill(BaseModel):
  name: str
  description: str = ""

class ExtractStats(BaseModel):
  hp: Optional[int] = None
  speed: Optional[int] = None
  attack: Optional[int] = None
  defense: Optional[int] = None
  magic: Optional[int] = None
  resist: Optional[int] = None

class ExtractResp(BaseModel):
  name: Optional[str] = None
  stats: ExtractStats
  skills: List[ExtractSkill]

# ====== 工具方法 ======
def _meaningful_desc(s: str) -> bool:
  t = (s or "").strip()
  if not t or t.lower() in {"0","1","-","—","无","暂无","null","none","n/a","N/A"}:
    return False
  return (len(t) >= 6 or
          re.search(r"[，。；、,.]", t) or
          re.search(r"(提高|降低|回复|免疫|伤害|回合|命中|几率|状态|先手|消除|减少|增加|额外|倍)", t))

def _strip_prefix_noise(s: str) -> str:
  # 去掉技能名后的常见噪音（元素/类型/威力/PP/冷却/数字等）
  for _ in range(6):
    s = re.sub(r"""
        ^\s*(?:\d+|
               [风火水木金土冰雷毒岩光暗普]|
               物理|法术|特殊|状态|类型|
               威力|PP|耗能|冷却|cd|CD|命中率?)[:：]?\s*
    """, "", s, flags=re.X)
  return s.strip()

# ====== 主入口：智能识别（六维 + 技能 + 可选名称） ======
@router.post("/utils/extract", response_model=ExtractResp)
def extract(payload: ExtractReq):
  text = (payload.text or "").strip()
  if not text:
    raise HTTPException(status_code=400, detail="empty text")

  # 1) 抓六维：第一组连续 6 个数字
  nums = list(re.finditer(r"\d+", text))
  stats = ExtractStats()
  six = None
  for i in range(len(nums) - 5):
    grp = nums[i:i+6]
    vals = [int(n.group()) for n in grp]
    if all(30 <= v <= 300 for v in vals):  # 宽松范围
      six = (grp, vals)
      break

  name = None
  tail_after_stats = text
  if six:
    grp, vals = six
    stats.hp, stats.speed, stats.attack, stats.defense, stats.magic, stats.resist = vals
    tail_after_stats = text[grp[-1].end():].strip()
    # 六维前尝试找名字（第一个 2~12 汉字）
    head = text[:grp[0].start()]
    m_name = re.search(r"[\u4e00-\u9fff]{2,12}", head)
    if m_name:
      name = m_name.group(0)

  # 2) 抓技能：优先在六维之后
  search_base = tail_after_stats or text
  m_skill_name = re.search(r"[\u4e00-\u9fff]{2,20}", search_base)
  skills: List[ExtractSkill] = []
  if m_skill_name:
    sk_name = m_skill_name.group(0)
    desc = _strip_prefix_noise(search_base[m_skill_name.end():])
    if not _meaningful_desc(desc):
      # 兜底：全文找一段像描述的句子
      m_desc = re.search(r"(无视|若|当|命中|使|令|提高|降低|回复|免疫|伤害|回合|几率|状态).{4,}", text)
      if m_desc:
        desc = m_desc.group(0).strip()
    skills.append(ExtractSkill(name=sk_name, description=desc if _meaningful_desc(desc) else ""))

  return ExtractResp(name=name, stats=stats, skills=skills)