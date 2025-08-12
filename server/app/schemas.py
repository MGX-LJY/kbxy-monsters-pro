from pydantic import BaseModel, Field
from typing import List, Optional, Any

class MonsterIn(BaseModel):
    name_final: str
    element: Optional[str] = None
    role: Optional[str] = None
    base_offense: float = 0
    base_survive: float = 0
    base_control: float = 0
    base_tempo: float = 0
    base_pp: float = 0
    tags: List[str] = []

class MonsterOut(MonsterIn):
    id: int
    explain_json: dict = Field(default_factory=dict)

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
