# server/app/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field

# —— Skills —— #
class SkillIn(BaseModel):
    name: str = Field(..., description="技能名")
    element: Optional[str] = Field(None, description="技能属性（风/火/.../特殊）")
    kind: Optional[str] = Field(None, description="类型：物理/法术/特殊")
    power: Optional[int] = Field(None, description="威力")
    description: Optional[str] = Field("", description="技能描述")


class SkillOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
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


# —— AutoMatch（保留，当前未直接使用） —— #
class AutoMatchIn(BaseModel):
    commit: bool = False  # True=写库，False=只返回建议（现由 /monsters/auto_match 接管）


class AutoMatchOut(BaseModel):
    monster_id: int
    role: str
    tags: List[str]
    derived: DerivedOut
    committed: bool = False


# —— Monsters —— #
class MonsterIn(BaseModel):
    # 用 name 取代 name_final
    name: str
    element: Optional[str] = None
    role: Optional[str] = None

    # 原始六维
    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    # 新增获取/持有相关
    possess: bool = False
    new_type: Optional[bool] = None
    type: Optional[str] = None
    method: Optional[str] = None

    # 标签与技能
    tags: List[str] = Field(default_factory=list)
    skills: List[SkillIn] = Field(default_factory=list)


class MonsterOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    role: Optional[str] = None

    # 原始六维
    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    # 新增获取/持有相关
    possess: Optional[bool] = None
    new_type: Optional[bool] = None
    type: Optional[str] = None
    method: Optional[str] = None

    # 标签与扩展字段
    tags: List[str] = Field(default_factory=list)
    explain_json: Dict[str, Any] = Field(default_factory=dict)

    # 时间
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    # 派生五维（服务端计算）
    derived: Optional[DerivedOut] = None

    class Config:
        from_attributes = True


class MonsterList(BaseModel):
    items: List[MonsterOut]
    total: int
    has_more: bool
    etag: str


# —— 导入（保持不变，如有需要再扩展） —— #
class ImportPreview(BaseModel):
    columns: List[str]
    total_rows: int
    sample: List[dict]
    hints: List[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    inserted: int
    updated: int
    skipped: int
    errors: List[dict] = Field(default_factory=list)


class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str = "Bad Request"
    status: int = 400
    code: str = "BAD_REQUEST"
    detail: str = ""
    trace_id: str = ""