"""初始 schema：8 张表 + 索引

Revision ID: 001
Revises:
Create Date: 2026-07-28
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # tasks
    op.create_table(
        "tasks",
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("task_type", sa.String(32), nullable=False),
        sa.Column("demander_id", sa.String(64), nullable=False),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("title", sa.String(256), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=True),
        sa.Column("assigned_resource_id", sa.String(64), nullable=True),
        sa.Column("parent_task_id", sa.String(64), nullable=True),
        sa.Column("custom_fields", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_tasks_demander", "tasks", ["demander_id"])
    op.create_index("idx_tasks_status", "tasks", ["status", "domain_tag"])
    op.create_index("idx_tasks_parent", "tasks", ["parent_task_id"])

    # resources
    op.create_table(
        "resources",
        sa.Column("resource_id", sa.String(64), primary_key=True),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("capabilities", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_resources_supplier", "resources", ["supplier_id"])
    op.create_index("idx_resources_available", "resources", ["domain_tag", "status"])

    # deals
    op.create_table(
        "deals",
        sa.Column("deal_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(64), nullable=False),
        sa.Column("supplier_id", sa.String(64), nullable=False),
        sa.Column("demander_id", sa.String(64), nullable=False),
        sa.Column("final_amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_deals_task", "deals", ["task_id"])
    op.create_index("idx_deals_supplier", "deals", ["supplier_id"])

    # users
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("user_type", sa.String(32), nullable=False),
        sa.Column("roles", postgresql.JSONB(), nullable=True),
        sa.Column("metadata", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # trust_profiles
    op.create_table(
        "trust_profiles",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("domain_tag", sa.String(32), primary_key=True),
        sa.Column("overall_score", sa.Numeric(4, 3), nullable=False),
        sa.Column("dimension_scores", postgresql.JSONB(), nullable=False),
        sa.Column("last_updated", sa.DateTime(), nullable=False),
    )

    # trust_evaluations
    op.create_table(
        "trust_evaluations",
        sa.Column("evaluator_id", sa.String(64), primary_key=True),
        sa.Column("evaluatee_id", sa.String(64), primary_key=True),
        sa.Column("task_id", sa.String(64), primary_key=True),
        sa.Column("domain_tag", sa.String(32), nullable=False),
        sa.Column("ratings", postgresql.JSONB(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_evaluations_user", "trust_evaluations", ["evaluatee_id", "domain_tag"])

    # events
    op.create_table(
        "events",
        sa.Column("event_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_layer", sa.String(16), nullable=False),
        sa.Column("task_id", sa.String(64), nullable=True),
        sa.Column("deal_id", sa.String(64), nullable=True),
        sa.Column("user_id", sa.String(64), nullable=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("idx_events_task", "events", ["task_id"])
    op.create_index("idx_events_deal", "events", ["deal_id"])
    op.create_index("idx_events_user", "events", ["user_id"])
    op.create_index("idx_events_type_time", "events", ["event_type", "created_at"])

    # composite_dependencies
    op.create_table(
        "composite_dependencies",
        sa.Column("composite_task_id", sa.String(64), nullable=False),
        sa.Column("subtask_id", sa.String(64), primary_key=True),
        sa.Column("depends_on_id", sa.String(64), primary_key=True),
    )
    op.create_index("idx_deps_composite", "composite_dependencies", ["composite_task_id"])


def downgrade() -> None:
    op.drop_table("composite_dependencies")
    op.drop_table("events")
    op.drop_table("trust_evaluations")
    op.drop_table("trust_profiles")
    op.drop_table("users")
    op.drop_table("deals")
    op.drop_table("resources")
    op.drop_table("tasks")
