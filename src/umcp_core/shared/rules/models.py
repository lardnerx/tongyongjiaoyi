"""规则配置 ORM 模型。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from umcp_core.repositories.postgres.models import Base


class BusinessRuleModel(Base):
    """业务规则配置表。"""

    __tablename__ = "business_rules"

    rule_key: Mapped[str] = mapped_column(String(128), primary_key=True)
    rule_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BusinessRuleHistoryModel(Base):
    """规则变更历史表。"""

    __tablename__ = "business_rule_history"

    history_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    rule_key: Mapped[str] = mapped_column(String(128), nullable=False)
    old_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    changed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    changed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    change_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
