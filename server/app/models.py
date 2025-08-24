# server/app/models.py
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Table, ForeignKey, JSON, Text,
    UniqueConstraint, Boolean, Index
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from sqlalchemy.ext.associationproxy import association_proxy

from .db import Base

# 多对多：怪物 <-> 标签
monster_tag = Table(
    "monster_tag",
    Base.metadata,
    Column("monster_id", ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)


class Monster(Base):
    __tablename__ = "monsters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 名称：用 name 替代 name_final，并作为唯一键
    name: Mapped[str] = mapped_column(String(100), index=True, unique=True, nullable=False)

    # 基础属性
    element: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    role: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)

    # 新增获取/持有相关
    possess: Mapped[bool] = mapped_column(Boolean, default=False)         # 是否已拥有（本地勾选）
    new_type: Mapped[bool | None] = mapped_column(Boolean, nullable=True) # 当前是否可获取（爬虫/人工判断）
    type: Mapped[str | None] = mapped_column(String(64), index=True, nullable=True)  # 获取渠道分类
    method: Mapped[str | None] = mapped_column(Text, nullable=True)       # 获取方式具体描述

    # 原始六维
    hp: Mapped[float] = mapped_column(Float, default=0.0)
    speed: Mapped[float] = mapped_column(Float, default=0.0)
    attack: Mapped[float] = mapped_column(Float, default=0.0)
    defense: Mapped[float] = mapped_column(Float, default=0.0)
    magic: Mapped[float] = mapped_column(Float, default=0.0)
    resist: Mapped[float] = mapped_column(Float, default=0.0)

    # 说明/附加信息
    explain_json: Mapped[dict] = mapped_column(JSON, default=dict)

    # 时间
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    tags = relationship("Tag", secondary=monster_tag, back_populates="monsters")

    # 关联对象关系：怪物 <-> MonsterSkill <-> 技能
    monster_skills = relationship(
        "MonsterSkill",
        back_populates="monster",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # 便捷代理：仍可通过 m.skills 直接拿到 Skill 列表（兼容读取）
    skills = association_proxy("monster_skills", "skill")

    # 1:1 派生（新五轴）
    derived = relationship("MonsterDerived", back_populates="monster", uselist=False, cascade="all, delete-orphan")

    # —— 新增：收藏关系（关联对象 + 代理至 Collection）——
    collection_links = relationship(
        "CollectionItem",
        back_populates="monster",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    collections = association_proxy("collection_links", "collection")

    def __repr__(self) -> str:
        return f"<Monster id={self.id} name={self.name!r} element={self.element!r}>"


class MonsterDerived(Base):
    __tablename__ = "monster_derived"

    monster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True
    )

    # —— 新五轴（0~120）——
    # 体防：体力/防御 + 护盾/治疗/减伤/反伤/免疫 等硬生存能力
    body_defense: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 体抗：体力/抗性 + 净化/状态免疫/抗性提升 等抗异常能力
    body_resist: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 削防抗：降防/降抗/破甲，联合命中时加成
    debuff_def_res: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 削攻法：降攻/降法/降命中/封技 抑制输出
    debuff_atk_mag: Mapped[int] = mapped_column(Integer, default=0, index=True)
    # 特殊：PP 压制/中毒(剧毒)/自爆/禁疗/疲劳 等非常规博弈
    special_tactics: Mapped[int] = mapped_column(Integer, default=0, index=True)

    # 追踪信息（按需保留）
    formula: Mapped[str] = mapped_column(String(64), default="kbxy@v2025-08-24")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monster = relationship("Monster", back_populates="derived")

    def __repr__(self) -> str:
        return f"<MonsterDerived monster_id={self.monster_id} body_defense={self.body_defense}>"


class Tag(Base):
    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    monsters = relationship("Monster", secondary=monster_tag, back_populates="tags")

    def __repr__(self) -> str:
        return f"<Tag id={self.id} name={self.name!r}>"


class Skill(Base):
    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # 唯一标识维度
    name: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    element: Mapped[str | None] = mapped_column(String(16), index=True, nullable=True)
    kind: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)  # 物理/法术/特殊
    power: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)

    # 描述
    description: Mapped[str] = mapped_column(Text, default="")

    # 与怪物的关联对象关系
    monster_skills = relationship(
        "MonsterSkill",
        back_populates="skill",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    # 便捷代理：可通过 skill.monsters 直接看到怪物
    monsters = association_proxy("monster_skills", "monster")

    __table_args__ = (
        UniqueConstraint("name", "element", "kind", "power", name="uq_skill_name_elem_kind_power"),
        Index("ix_skill_name_like", "name"),
    )

    def __repr__(self) -> str:
        ekp = f"{self.element}/{self.kind}/{self.power}"
        return f"<Skill id={self.id} name={self.name!r} {ekp}>"


class MonsterSkill(Base):
    """
    关联对象：怪物-技能 多对多
    - 记录是否精选（selected）与可选等级（level）以及关系级描述（可选）
    """
    __tablename__ = "monster_skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    monster_id: Mapped[int] = mapped_column(Integer, ForeignKey("monsters.id", ondelete="CASCADE"), index=True)
    skill_id: Mapped[int] = mapped_column(Integer, ForeignKey("skills.id", ondelete="CASCADE"), index=True)

    # 关系级字段
    selected: Mapped[bool] = mapped_column(Boolean, default=False)
    level: Mapped[int | None] = mapped_column(Integer, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monster = relationship("Monster", back_populates="monster_skills")
    skill = relationship("Skill", back_populates="monster_skills")

    __table_args__ = (
        UniqueConstraint("monster_id", "skill_id", name="uq_monster_skill_pair"),
    )

    def __repr__(self) -> str:
        return f"<MonsterSkill monster_id={self.monster_id} skill_id={self.skill_id} selected={self.selected}>"


# ===================== 新增：收藏夹 =====================

class Collection(Base):
    """
    收藏夹：按名称唯一（单用户场景）；多用户时再加 user_id 并改为 (user_id, name) 唯一。
    """
    __tablename__ = "collections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    color: Mapped[str | None] = mapped_column(String(16), nullable=True)

    items_count: Mapped[int] = mapped_column(Integer, default=0)  # 冗余计数，批量增删时维护（可选）
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关联对象：Collection <-> CollectionItem <-> Monster
    items = relationship(
        "CollectionItem",
        back_populates="collection",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    monsters = association_proxy("items", "monster")

    def __repr__(self) -> str:
        return f"<Collection id={self.id} name={self.name!r} count={self.items_count}>"


class CollectionItem(Base):
    """
    关联对象：收藏夹-怪物 多对多
    复合主键确保唯一：每个怪在同一收藏夹里只能出现一次。
    """
    __tablename__ = "collection_items"

    collection_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("collections.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    monster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    collection = relationship("Collection", back_populates="items")
    monster = relationship("Monster", back_populates="collection_links")

    __table_args__ = (
        Index("ix_collection_items_monster_id", "monster_id"),
    )

    def __repr__(self) -> str:
        return f"<CollectionItem collection_id={self.collection_id} monster_id={self.monster_id}>"


# —— 任务/导入作业：保持不变 —— #

class ImportJob(Base):
    __tablename__ = "import_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="done")  # done/processing/failed
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<ImportJob id={self.id} key={self.key!r} status={self.status!r}>"


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)  # uuid
    type: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending/running/done/failed
    progress: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)
    result_json: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def __repr__(self) -> str:
        return f"<Task id={self.id} type={self.type!r} status={self.status!r}>"


# ===================== 惰性建表工具 =====================

def ensure_collections_tables(bind) -> None:
    """
    在首次使用收藏夹能力前调用：
        ensure_collections_tables(db.get_bind())
    将仅为 Collection / CollectionItem 两张表执行 create_all（幂等）。
    """
    Base.metadata.create_all(
        bind,
        tables=[Collection.__table__, CollectionItem.__table__],
    )