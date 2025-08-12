# server/app/schemas.py
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# —— Skills —— #
class SkillIn(BaseModel):
    name: str = Field(..., description="技能名")
    description: Optional[str] = Field("", description="技能描述")

class SkillOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = ""

    class Config:
        from_attributes = True

# —— Derived 五维 —— #
class DerivedOut(BaseModel):
    offense: int = 0
    survive: int = 0
    control: int = 0
    tempo: int = 0
    pp_pressure: int = 0

# —— AutoMatch —— #
class AutoMatchIn(BaseModel):
    commit: bool = False  # True=写库（role/tags + derived），False=只返回建议

class AutoMatchOut(BaseModel):
    monster_id: int
    role: str
    tags: List[str]
    derived: DerivedOut
    committed: bool = False

# —— Monsters —— #
class MonsterIn(BaseModel):
    name_final: str
    element: Optional[str] = None
    role: Optional[str] = None

    # 原始六维（只保留这一套）
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

    tags: List[str] = []
    explain_json: Dict[str, Any] = {}

    # 派生五维（服务端计算）
    derived: Optional[DerivedOut] = None

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