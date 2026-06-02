"""Drop dead Migration tooling tables (CR-NS-007 Phase 1a).

Removes the pre-agent Migration tooling subsystem tables, whose models,
routes, schemas and services were deleted in CR-NS-007 Phase 1a:

* ``migration_id_map``
* ``migration_category_status``
* ``migration_batches``

Zero frontend callers, zero live code coupling. ``downgrade()`` recreates the
three tables by mirroring their original ``create_table`` blocks
(006_create_migration_batch, 007_create_migration_category_status,
022_create_remaining_domain_models) so the chain stays reversible.

Revision ID: 047
Revises: 046
Create Date: 2026-06-02

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "047"
down_revision: Union[str, None] = "046"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # FK-safe order (reverse of creation): migration_id_map.batch_id references
    # migration_batches.id, so the child table is dropped first. ``drop_table``
    # cascades the table's own indexes in PostgreSQL.
    op.drop_table("migration_id_map")
    op.drop_table("migration_category_status")
    op.drop_table("migration_batches")


def downgrade() -> None:
    # Recreate in FK-safe order: parents (batches, category_status) before the
    # child (id_map, whose batch_id references migration_batches.id).
    op.create_table(
        "migration_batches",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=10), nullable=False),
        sa.Column(
            "direction",
            sa.String(length=10),
            server_default="extract",
            nullable=False,
        ),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=True),
        sa.Column("target_count", sa.Integer(), nullable=True),
        sa.Column("error_count", sa.Integer(), server_default="0", nullable=True),
        sa.Column("error_log", sa.Text(), nullable=True),
        sa.Column("started_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("completed_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'completed', 'failed')",
            name="ck_migration_batches_status",
        ),
        sa.CheckConstraint(
            "direction IN ('extract', 'load')",
            name="ck_migration_batches_direction",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_migration_batches_project_id"),
        "migration_batches",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_category"),
        "migration_batches",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_direction"),
        "migration_batches",
        ["direction"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_batches_status"),
        "migration_batches",
        ["status"],
        unique=False,
    )

    op.create_table(
        "migration_category_status",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("category", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("last_run_at", postgresql.TIMESTAMP(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            postgresql.TIMESTAMP(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "project_id",
            "category",
            name="uq_migration_category_status_project_category",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'in_progress', 'completed', 'failed')",
            name="ck_migration_category_status_status",
        ),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_migration_category_status_project_id"),
        "migration_category_status",
        ["project_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_category_status_category"),
        "migration_category_status",
        ["category"],
        unique=False,
    )
    op.create_index(
        op.f("ix_migration_category_status_status"),
        "migration_category_status",
        ["status"],
        unique=False,
    )

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
