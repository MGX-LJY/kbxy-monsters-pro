# server/app/schemas.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# —— Skill —— #
class SkillIn(BaseModel):
    name: str = Field(..., description="技能名")
    description: Optional[str] = Field("", description="技能描述")

class SkillOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = ""

    class Config:
        from_attributes = True

# —— Monster —— #
class MonsterIn(BaseModel):
    name_final: str
    element: Optional[str] = None
    role: Optional[str] = None

    # 后端采用五维：攻/生/控/速/PP
    base_offense: float = 0
    base_survive: float = 0
    base_control: float = 0
    base_tempo: float = 0
    base_pp: float = 0

    tags: List[str] = []
    # 新增：可携带多个技能（可空）
    skills: List[SkillIn] = []

class MonsterOut(BaseModel):
    id: int
    name_final: str
    element: Optional[str] = None
    role: Optional[str] = None
    base_offense: float = 0
    base_survive: float = 0
    base_control: float = 0
    base_tempo: float = 0
    base_pp: float = 0
    tags: List[str] = []
    explain_json: Dict[str, Any] = {}

    class Config:
        from_attributes = True

class MonsterList(BaseModel):
    items: List[MonsterOut]
    total: int
    has_more: bool
    etag: str

class ImportPreview(BaseModel):
    columns: List[str]
    total_rows: int
    sample: List[dict]
    hints: List[str] = []

class ImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    errors: List[dict] = []

class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str = "Bad Request"
    status: int = 400
    code: str = "BAD_REQUEST"
    detail: str = ""
    trace_id: str = ""
