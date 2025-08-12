# server/app/models.py
from datetime import datetime
from sqlalchemy import (
    Column,
    Integer,
    String,
    Float,
    DateTime,
    Table,
    ForeignKey,
    JSON,
    Text,
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

    # —— 原始六维（只存原始，不再存“控/攻/生/速/PP”五维）
    base_hp: Mapped[float] = mapped_column(Float, default=0.0)       # 体力
    base_speed: Mapped[float] = mapped_column(Float, default=0.0)    # 速度
    base_attack: Mapped[float] = mapped_column(Float, default=0.0)   # 攻击
    base_defense: Mapped[float] = mapped_column(Float, default=0.0)  # 防御
    base_magic: Mapped[float] = mapped_column(Float, default=0.0)    # 法术
    base_resist: Mapped[float] = mapped_column(Float, default=0.0)   # 抗性

    # 解释/衍生（例如：raw_stats、skill_names、你后续的倾向分等）
    explain_json: Mapped[dict] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # 关系
    tags = relationship("Tag", secondary=monster_tag, back_populates="monsters", cascade="all,delete")
    skills = relationship("Skill", secondary=monster_skill, back_populates="monsters", cascade="all,delete")

    def __repr__(self) -> str:
        return f"<Monster id={self.id} name={self.name_final!r} element={self.element!r}>"


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