"""Create remaining domain model tables.

Creates the six remaining domain tables that were not covered by earlier
migrations:

* ``bug_fix_tasks``
* ``migration_id_map``
* ``delegations``
* ``auto_fix_attempts``
* ``execution_logs``
* ``guardian_reviews``

This migration intentionally does NOT touch any pre-existing tables.
Existing tables (``feats``, ``migration_batches``, ``migration_category_status``,
``project_members``, ``project_modules``, ``raw_specifications``, etc.) are
already correctly defined by their original migrations (001-021); any
``alter_column`` / ``add_column`` / ``drop_column`` here would either duplicate
prior DDL or attempt to drop columns that never existed, both of which
would break ``alembic upgrade head`` on a fresh database.

Revision ID: 022
Revises: 021
Create Date: 2026-04-16

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "022"
down_revision: Union[str, None] = "021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "bug_fix_tasks",
        sa.Column("bug_id", sa.UUID(), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), server_default="", nullable=False),
        sa.Column("task_type", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="todo", nullable=False),
        sa.Column("estimated_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_minutes", sa.Integer(), nullable=True),
        sa.Column("checklist_type", sa.String(length=30), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('todo', 'in_progress', 'done', 'failed')",
            name="ck_bug_fix_tasks_status",
        ),
        sa.CheckConstraint(
            "task_type IN ('backend', 'frontend', 'migration', 'test', 'docs')",
            name="ck_bug_fix_tasks_task_type",
        ),
        sa.ForeignKeyConstraint(["bug_id"], ["bugs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("bug_id", "number", name="uq_bug_fix_tasks_bug_id_number"),
    )
    op.create_index(op.f("ix_bug_fix_tasks_bug_id"), "bug_fix_tasks", ["bug_id"], unique=False)
    op.create_index(op.f("ix_bug_fix_tasks_status"), "bug_fix_tasks", ["status"], unique=False)

    op.create_table(
        "migration_id_map",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column("source_key", sa.String(length=255), nullable=False),
        sa.Column("target_id", sa.String(length=36), nullable=False),
        sa.Column("batch_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["batch_id"], ["migration_batches.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id",
            "category",
            "source_key",
            name="uq_migration_id_map_project_category_source_key",
        ),
    )
    op.create_index(
        "ix_migration_id_map_project_category",
        "migration_id_map",
        ["project_id", "category"],
        unique=False,
    )
    op.create_index(
        "ix_migration_id_map_source_key",
        "migration_id_map",
        ["source_key"],
        unique=False,
    )

    op.create_table(
        "delegations",
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("feat_id", sa.UUID(), nullable=True),
        sa.Column("bug_fix_task_id", sa.UUID(), nullable=True),
        sa.Column("bug_id", sa.UUID(), nullable=True),
        sa.Column("cc_agent", sa.String(length=20), server_default="ubuntu_cc", nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("raw_output", sa.Text(), nullable=True),
        sa.Column("commit_hash", sa.String(length=40), nullable=True),
        sa.Column(
            "started_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("cc_agent IN ('ubuntu_cc')", name="ck_delegations_cc_agent"),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'done', 'failed')",
            name="ck_delegations_status",
        ),
        sa.ForeignKeyConstraint(["bug_fix_task_id"], ["bug_fix_tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["bug_id"], ["bugs.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["feat_id"], ["feats.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_delegations_started_at", "delegations", ["started_at"], unique=False)
    op.create_index("ix_delegations_status", "delegations", ["status"], unique=False)
    op.create_index(op.f("ix_delegations_task_id"), "delegations", ["task_id"], unique=False)

    op.create_table(
        "auto_fix_attempts",
        sa.Column("feat_id", sa.UUID(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("error_description", sa.Text(), nullable=False),
        sa.Column("fix_description", sa.Text(), nullable=True),
        sa.Column("delegation_id", sa.UUID(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["delegation_id"], ["delegations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["feat_id"], ["feats.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "feat_id",
            "attempt_number",
            name="uq_auto_fix_attempts_feat_id_attempt_number",
        ),
    )
    op.create_index(op.f("ix_auto_fix_attempts_feat_id"), "auto_fix_attempts", ["feat_id"], unique=False)

    op.create_table(
        "execution_logs",
        sa.Column("delegation_id", sa.UUID(), nullable=False),
        sa.Column("task_id", sa.UUID(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_cost_usd", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("commit_hash", sa.String(length=40), nullable=True),
        sa.Column("commit_verified", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("status IN ('done', 'failed')", name="ck_execution_logs_status"),
        sa.ForeignKeyConstraint(["delegation_id"], ["delegations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_execution_logs_delegation_id"), "execution_logs", ["delegation_id"], unique=False)
    op.create_index(op.f("ix_execution_logs_task_id"), "execution_logs", ["task_id"], unique=False)

    op.create_table(
        "guardian_reviews",
        sa.Column("delegation_id", sa.UUID(), nullable=False),
        sa.Column("layer", sa.String(length=10), nullable=False),
        sa.Column("risk_level", sa.String(length=10), nullable=False),
        sa.Column(
            "findings",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default="[]",
            nullable=False,
        ),
        sa.Column("passed", sa.Boolean(), server_default="false", nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "layer IN ('layer1', 'layer2', 'layer3')",
            name="ck_guardian_reviews_layer",
        ),
        sa.CheckConstraint(
            "risk_level IN ('low', 'medium', 'high', 'critical')",
            name="ck_guardian_reviews_risk_level",
        ),
        sa.ForeignKeyConstraint(["delegation_id"], ["delegations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_guardian_reviews_delegation_id", "guardian_reviews", ["delegation_id"], unique=False)
    op.create_index("ix_guardian_reviews_layer", "guardian_reviews", ["layer"], unique=False)
    op.create_index("ix_guardian_reviews_risk_level", "guardian_reviews", ["risk_level"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_guardian_reviews_risk_level", table_name="guardian_reviews")
    op.drop_index("ix_guardian_reviews_layer", table_name="guardian_reviews")
    op.drop_index("ix_guardian_reviews_delegation_id", table_name="guardian_reviews")
    op.drop_table("guardian_reviews")

    op.drop_index(op.f("ix_execution_logs_task_id"), table_name="execution_logs")
    op.drop_index(op.f("ix_execution_logs_delegation_id"), table_name="execution_logs")
    op.drop_table("execution_logs")

    op.drop_index(op.f("ix_auto_fix_attempts_feat_id"), table_name="auto_fix_attempts")
    op.drop_table("auto_fix_attempts")

    op.drop_index(op.f("ix_delegations_task_id"), table_name="delegations")
    op.drop_index("ix_delegations_status", table_name="delegations")
    op.drop_index("ix_delegations_started_at", table_name="delegations")
    op.drop_table("delegations")

    op.drop_index("ix_migration_id_map_source_key", table_name="migration_id_map")
    op.drop_index("ix_migration_id_map_project_category", table_name="migration_id_map")
    op.drop_table("migration_id_map")

    op.drop_index(op.f("ix_bug_fix_tasks_status"), table_name="bug_fix_tasks")
    op.drop_index(op.f("ix_bug_fix_tasks_bug_id"), table_name="bug_fix_tasks")
    op.drop_table("bug_fix_tasks")
