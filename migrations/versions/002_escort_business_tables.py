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

    # ---------- 支付记录表 ----------
    op.create_table(
        "payments",
        sa.Column("payment_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("gateway", sa.String(16), nullable=False),
        sa.Column("trade_no", sa.String(128), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("refunded_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_payments_deal", "payments", ["deal_id"])
    op.create_index("idx_payments_user", "payments", ["user_id", "status"])

    # ---------- 文件存储表 ----------
    op.create_table(
        "files",
        sa.Column("file_id", sa.String(64), primary_key=True),
        sa.Column("uploader_id", sa.String(64), nullable=False),
        sa.Column("url", sa.String(512), nullable=False),
        sa.Column("file_type", sa.String(32), nullable=False),
        sa.Column("biz_type", sa.String(32), nullable=False),
        sa.Column("biz_id", sa.String(64), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mime", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_files_biz", "files", ["biz_type", "biz_id"])


def downgrade() -> None:
    op.drop_table("files")
    op.drop_table("payments")
    op.drop_table("business_rule_history")
    op.drop_table("business_rules")
