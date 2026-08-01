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

    # ---------- 通知表 ----------
    op.create_table(
        "notifications",
        sa.Column("notification_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=True),
        sa.Column("read_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_notifications_user", "notifications", ["user_id", "read_at"])

    op.create_table(
        "notification_templates",
        sa.Column("template_key", sa.String(128), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("recipient_role", sa.String(32), nullable=False),
        sa.Column("channels", postgresql.JSONB(), nullable=True),
        sa.Column("title_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
    )

    # ---------- LBS 位置表（PostGIS）----------
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.create_table(
        "lbs_locations",
        sa.Column("location_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("heading", sa.Float(), nullable=True),
        sa.Column("speed", sa.Float(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.execute("SELECT AddGeometryColumn('lbs_locations', 'location', 4326, 'POINT', 2)")
    op.execute("CREATE INDEX idx_lbs_locations_geom ON lbs_locations USING GIST (location)")
    op.create_index("idx_lbs_locations_resource", "lbs_locations", ["resource_id"])

    # ---------- 陪驾业务扩展表 ----------
    op.create_table(
        "escort_coach_profiles",
        sa.Column("profile_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("car_model", sa.String(64), nullable=True),
        sa.Column("license_plate", sa.String(32), nullable=True),
        sa.Column("service_areas", postgresql.JSONB(), nullable=True),
        sa.Column("hourly_rate", sa.Numeric(10, 2), nullable=True),
        sa.Column("coach_level", sa.String(16), nullable=False, server_default="BRONZE"),
        sa.Column("level_updated_at", sa.DateTime(), nullable=True),
        sa.Column("bio", sa.Text(), nullable=True),
        sa.Column("verified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.String(64), nullable=True),
    )
    op.create_index("idx_coach_profiles_user", "escort_coach_profiles", ["user_id"], unique=True)

    op.create_table(
        "escort_reviews",
        sa.Column("review_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("evaluator_id", sa.String(64), nullable=False),
        sa.Column("evaluatee_id", sa.String(64), nullable=False),
        sa.Column("evaluator_role", sa.String(16), nullable=False),
        sa.Column("ratings", postgresql.JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_reviews_evaluatee", "escort_reviews", ["evaluatee_id"])
    op.create_index("idx_reviews_deal", "escort_reviews", ["deal_id"])

    op.create_table(
        "escort_service_records",
        sa.Column("record_id", sa.String(64), primary_key=True),
        sa.Column("deal_id", sa.String(64), nullable=False),
        sa.Column("coach_id", sa.String(64), nullable=False),
        sa.Column("student_id", sa.String(64), nullable=False),
        sa.Column("start_at", sa.DateTime(), nullable=False),
        sa.Column("end_at", sa.DateTime(), nullable=True),
        sa.Column("start_lat", sa.Float(), nullable=True),
        sa.Column("start_lng", sa.Float(), nullable=True),
        sa.Column("end_lat", sa.Float(), nullable=True),
        sa.Column("end_lng", sa.Float(), nullable=True),
        sa.Column("duration_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_service_records_coach", "escort_service_records", ["coach_id", "start_at"])
    op.create_index("idx_service_records_deal", "escort_service_records", ["deal_id"])

    op.create_table(
        "friendships",
        sa.Column("friendship_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("friend_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_friendships_user", "friendships", ["user_id", "status"])
    op.create_index("idx_friendships_pair", "friendships", ["user_id", "friend_id"], unique=True)

    op.create_table(
        "credit_logs",
        sa.Column("log_id", sa.String(64), primary_key=True),
        sa.Column("user_id", sa.String(64), nullable=False),
        sa.Column("delta", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("deal_id", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_credit_logs_user", "credit_logs", ["user_id", "created_at"])

    # ---------- 核心表扩展字段 ----------
    # tasks 表新增字段
    op.add_column("tasks", sa.Column("order_type", sa.String(16), nullable=True))
    op.add_column("tasks", sa.Column("scheduled_at", sa.DateTime(), nullable=True))
    op.add_column("tasks", sa.Column("coach_level_pref", sa.String(16), nullable=True))

    # deals 表新增字段
    op.add_column("deals", sa.Column("service_started_at", sa.DateTime(), nullable=True))
    op.add_column("deals", sa.Column("service_ended_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    # 核心表扩展字段
    op.drop_column("deals", "service_ended_at")
    op.drop_column("deals", "service_started_at")
    op.drop_column("tasks", "coach_level_pref")
    op.drop_column("tasks", "scheduled_at")
    op.drop_column("tasks", "order_type")

    # 陪驾业务扩展表（反向 drop）
    op.drop_table("credit_logs")
    op.drop_table("friendships")
    op.drop_table("escort_service_records")
    op.drop_table("escort_reviews")
    op.drop_table("escort_coach_profiles")

    op.drop_table("lbs_locations")
    op.drop_table("notification_templates")
    op.drop_table("notifications")
    op.drop_table("files")
    op.drop_table("payments")
    op.drop_table("business_rule_history")
    op.drop_table("business_rules")
