"""SQLAlchemy 2.0 ORM 模型，对应 7 张数据库表。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    Numeric,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""

    pass


class TaskModel(Base):
    """任务表（含复合任务和子任务，用 parent_task_id 建立层级）。"""

    __tablename__ = "tasks"

    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    demander_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    title: Mapped[str | None] = mapped_column(String(256), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    supplier_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assigned_resource_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    custom_fields: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class ResourceModel(Base):
    """资源表。"""

    __tablename__ = "resources"

    resource_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    capabilities: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 'metadata' 是 DeclarativeBase 的保留属性名，Python 属性用 metadata_，
    # 数据库列名仍为 metadata（由 mapped_column 第一参数指定）
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class DealModel(Base):
    """交易表。"""

    __tablename__ = "deals"

    deal_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(64), nullable=False)
    supplier_id: Mapped[str] = mapped_column(String(64), nullable=False)
    demander_id: Mapped[str] = mapped_column(String(64), nullable=False)
    final_amount: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # 'metadata' 是 DeclarativeBase 的保留属性名，Python 属性用 metadata_，
    # 数据库列名仍为 metadata（由 mapped_column 第一参数指定）
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class UserModel(Base):
    """用户表。"""

    __tablename__ = "users"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    user_type: Mapped[str] = mapped_column(String(32), nullable=False)
    roles: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 'metadata' 是 DeclarativeBase 的保留属性名，Python 属性用 metadata_，
    # 数据库列名仍为 metadata（由 mapped_column 第一参数指定）
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TrustProfileModel(Base):
    """信任档案表（按 domain 隔离）。"""

    __tablename__ = "trust_profiles"

    user_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_tag: Mapped[str] = mapped_column(String(32), primary_key=True)
    overall_score: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False)
    dimension_scores: Mapped[dict] = mapped_column(JSONB, nullable=False)
    last_updated: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class TrustEvaluationModel(Base):
    """评价记录表。"""

    __tablename__ = "trust_evaluations"

    evaluator_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluatee_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    task_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_tag: Mapped[str] = mapped_column(String(32), nullable=False)
    ratings: Mapped[dict] = mapped_column(JSONB, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class EventModel(Base):
    """事件日志表（用于审计与回放）。"""

    __tablename__ = "events"

    event_id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_layer: Mapped[str] = mapped_column(String(16), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deal_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CompositeDependencyModel(Base):
    """复合任务 DAG 依赖关系表。"""

    __tablename__ = "composite_dependencies"

    composite_task_id: Mapped[str] = mapped_column(String(64), nullable=False)
    subtask_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    depends_on_id: Mapped[str] = mapped_column(String(64), primary_key=True)
