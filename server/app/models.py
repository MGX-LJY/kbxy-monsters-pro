# server/app/models.py
from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, DateTime, Table, ForeignKey, JSON, Text, UniqueConstraint
)
from sqlalchemy.orm import relationship, Mapped, mapped_column
from .db import Base

# 多对多：怪物 <-> 标签
monster_tag = Table(
    "monster_tag",
    Base.metadata,
    Column("monster_id", ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True),
    Column("tag_id", ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
)

# 多对多：怪物 <-> 技能
monster_skill = Table(
    "monster_skill",
    Base.metadata,
    Column("monster_id", ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True),
    Column("skill_id", ForeignKey("skills.id", ondelete="CASCADE"), primary_key=True),
)


class Monster(Base):
    __tablename__ = "monsters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name_final: Mapped[str] = mapped_column(String(100), index=True, nullable=False)
    element: Mapped[str | None] = mapped_column(String(10), index=True, nullable=True)
    role: Mapped[str | None] = mapped_column(String(20), index=True, nullable=True)

    # —— 仅保留原始六维 —— #
    hp: Mapped[float] = mapped_column(Float, default=0.0)       # 体力
    speed: Mapped[float] = mapped_column(Float, default=0.0)    # 速度
    attack: Mapped[float] = mapped_column(Float, default=0.0)   # 攻击
    defense: Mapped[float] = mapped_column(Float, default=0.0)  # 防御
    magic: Mapped[float] = mapped_column(Float, default=0.0)    # 法术
    resist: Mapped[float] = mapped_column(Float, default=0.0)   # 抗性

    explain_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    tags = relationship("Tag", secondary=monster_tag, back_populates="monsters")
    skills = relationship("Skill", secondary=monster_skill, back_populates="monsters")

    # 1:1 派生五维
    derived = relationship("MonsterDerived", back_populates="monster", uselist=False, cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Monster id={self.id} name={self.name_final!r} element={self.element!r}>"


class MonsterDerived(Base):
    __tablename__ = "monster_derived"

    monster_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("monsters.id", ondelete="CASCADE"), primary_key=True
    )

    # 派生五维（对外用 int；内部计算后四舍五入）
    offense: Mapped[int] = mapped_column(Integer, default=0)
    survive: Mapped[int] = mapped_column(Integer, default=0)
    control: Mapped[int] = mapped_column(Integer, default=0)
    tempo: Mapped[int] = mapped_column(Integer, default=0)
    pp_pressure: Mapped[int] = mapped_column(Integer, default=0)

    # 追踪信息
    formula: Mapped[str] = mapped_column(String(64), default="kw@v2025-08-12")
    inputs: Mapped[dict] = mapped_column(JSON, default=dict)
    weights: Mapped[dict] = mapped_column(JSON, default=dict)
    signals: Mapped[dict] = mapped_column(JSON, default=dict)

    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    monster = relationship("Monster", back_populates="derived")

    def __repr__(self) -> str:
        return f"<MonsterDerived monster_id={self.monster_id} offense={self.offense}>"


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
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    monsters = relationship("Monster", secondary=monster_skill, back_populates="skills")
    def __repr__(self) -> str:
        return f"<Skill id={self.id} name={self.name!r}>"


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