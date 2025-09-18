# server/app/schemas.py
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any, Literal
from pydantic import BaseModel, Field

# —— Skills —— #
class SkillIn(BaseModel):
    name: str = Field(..., description="技能名")
    element: Optional[str] = Field(None, description="技能属性（风/火/.../特殊）")
    kind: Optional[str] = Field(None, description="类型：物理/法术/特殊")
    power: Optional[int] = Field(None, description="威力")
    pp: Optional[int] = Field(None, description="PP值")
    description: Optional[str] = Field("", description="技能描述")
    selected: Optional[bool] = Field(None, description="是否为推荐技能")

class SkillOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None
    kind: Optional[str] = None
    power: Optional[int] = None
    pp: Optional[int] = None
    description: Optional[str] = ""

    class Config:
        from_attributes = True


# —— AutoMatch —— #
class AutoMatchIn(BaseModel):
    commit: bool = False

class AutoMatchOut(BaseModel):
    monster_id: int
    tags: List[str]
    committed: bool = False

# —— Monsters —— #
class MonsterIn(BaseModel):
    name: str
    element: Optional[str] = None

    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    possess: bool = False
    type: Optional[str] = None
    method: Optional[str] = None

    tags: List[str] = Field(default_factory=list)
    skills: List[SkillIn] = Field(default_factory=list)

class MonsterOut(BaseModel):
    id: int
    name: str
    element: Optional[str] = None

    hp: float = 0
    speed: float = 0
    attack: float = 0
    defense: float = 0
    magic: float = 0
    resist: float = 0

    possess: Optional[bool] = None
    type: Optional[str] = None
    method: Optional[str] = None

    tags: List[str] = Field(default_factory=list)

    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


    # ---- 新增：图片 URL ----
    image_url: Optional[str] = None

    class Config:
        from_attributes = True

class MonsterList(BaseModel):
    items: List[MonsterOut]
    total: int
    has_more: bool
    etag: str

class ProblemDetail(BaseModel):
    type: str = "about:blank"
    title: str = "Bad Request"
    status: int = 400
    code: str = "BAD_REQUEST"
    detail: str = ""
    trace_id: str = ""

# ===================== 收藏夹（MVP 用） =====================
class CollectionIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64, description="收藏夹名称（唯一）")
    color: Optional[str] = Field(None, max_length=16, description="颜色（#RGB/#RRGGBB 或预设名，可选）")

class CollectionUpdateIn(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=64, description="新名称")
    color: Optional[str] = Field(None, max_length=16, description="新颜色")

class CollectionOut(BaseModel):
    id: int
    name: str
    color: Optional[str] = None
    items_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class CollectionList(BaseModel):
    items: List[CollectionOut]
    total: int
    has_more: bool
    etag: str

class CollectionBulkSetIn(BaseModel):
    collection_id: Optional[int] = Field(None, description="收藏夹 ID（优先使用）")
    name: Optional[str] = Field(None, description="收藏夹名称（当未提供 ID 时使用；可触发按名创建）")
    ids: List[int] = Field(..., description="怪物 ID 列表（去重后处理）")
    action: Literal["add", "remove", "set"] = Field("add", description="批量操作类型")

class CollectionCreateIn(CollectionIn):
    pass

class BulkSetMembersIn(CollectionBulkSetIn):
    color_for_new: Optional[str] = Field(
        None, max_length=16, description="（可选）当按 name 惰性创建收藏夹时使用的颜色"
    )

class BulkSetMembersOut(BaseModel):
    collection_id: int
    added: int
    removed: int
    skipped: int
    missing_monsters: List[int] = Field(default_factory=list)