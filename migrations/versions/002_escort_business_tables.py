"""陪驾业务扩展表 + 共享基础设施表

Revision ID: 002
Revises: 001
Create Date: 2026-07-31
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- 规则配置表 ----------
    op.create_table(
        "business_rules",
        sa.Column("rule_key", sa.String(128), primary_key=True),
        sa.Column("rule_value", postgresql.JSONB(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.String(64), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_business_rules_category", "business_rules", ["category"])

    op.create_table(
        "business_rule_history",
        sa.Column("history_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("rule_key", sa.String(128), nullable=False),
        sa.Column("old_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("changed_by", sa.String(64), nullable=True),
        sa.Column("changed_at", sa.DateTime(), nullable=False),
        sa.Column("change_reason", sa.Text(), nullable=True),
    )
    op.create_index("idx_rule_history_key", "business_rule_history", ["rule_key"])


def downgrade() -> None:
    op.drop_table("business_rule_history")
    op.drop_table("business_rules")
