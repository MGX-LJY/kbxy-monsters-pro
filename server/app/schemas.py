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


# ===================== 收藏夹（MVP 用） =====================

class CollectionIn(BaseModel):
    """
    创建收藏夹：仅需名称，可选颜色。
    多用户场景可在后续加入 user_id 相关字段。
    """
    name: str = Field(..., min_length=1, max_length=64, description="收藏夹名称（唯一）")
    color: Optional[str] = Field(None, max_length=16, description="颜色（#RGB/#RRGGBB 或预设名，可选）")


class CollectionUpdateIn(BaseModel):
    """
    更新收藏夹的名称/颜色（二选其一或同时提供）。
    """
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
    """
    批量操作收藏夹成员：
      - action = add    -> 将 ids 加入收藏夹（已存在的跳过）
      - action = remove -> 将 ids 从收藏夹移出（不存在的跳过）
      - action = set    -> 用 ids 覆盖收藏夹成员（先清空再加入）
    定位收藏夹优先使用 collection_id；缺省时可用 name。
    后端可选择：当按 name 未找到时自动创建（与“惰性建表”配合）。
    """
    collection_id: Optional[int] = Field(None, description="收藏夹 ID（优先使用）")
    name: Optional[str] = Field(None, description="收藏夹名称（当未提供 ID 时使用；可触发按名创建）")
    ids: List[int] = Field(..., description="怪物 ID 列表（去重后处理）")
    action: Literal["add", "remove", "set"] = Field("add", description="批量操作类型")


# -------- 路由兼容别名（你路由里引用的名字） --------
class CollectionCreateIn(CollectionIn):
    """与 CollectionIn 等价，作为 /collections POST 的兼容别名。"""
    pass


class BulkSetMembersIn(CollectionBulkSetIn):
    """与 CollectionBulkSetIn 等价，额外允许在按 name 创建新收藏夹时指定颜色。"""
    color_for_new: Optional[str] = Field(
        None, max_length=16, description="（可选）当按 name 惰性创建收藏夹时使用的颜色"
    )


class BulkSetMembersOut(BaseModel):
    """批量成员操作结果"""
    collection_id: int
    added: int
    removed: int
    skipped: int
    missing_monsters: List[int] = Field(default_factory=list)