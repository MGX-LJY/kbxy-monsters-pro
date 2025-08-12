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

    # 原始六维（只传这 6 个）
    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    tags: List[str] = []
    skills: List[SkillIn] = []

class MonsterOut(BaseModel):
    id: int
    name_final: str
    element: Optional[str] = None
    role: Optional[str] = None

    # 原始六维
    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    # 派生（仅用于展示/排序，不落库）
    sum: float = 0
    offense: float = 0     # = attack
    survive: float = 0     # = hp
    control: float = 0     # = (defense + magic) / 2
    tempo: float = 0       # = speed
    pp: float = 0          # = resist

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