"""Create credentials table — separate from kb_documents.

Per CLAUDE.md §13 and the 2026-05-04 design discussion, credentials
files live OUTSIDE the KB root and are managed by a dedicated registry
table + ``ri``-gated REST API. This migration creates the registry
schema only; the on-disk store, the data move from ``kb_documents``
and the cleanup of the ``credentials`` value from
``ck_kb_documents_doc_category`` are handled in migration 039.

Revision ID: 038
Revises: 037
Create Date: 2026-05-04
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "038"
down_revision: Union[str, None] = "037"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "credentials",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("file_path", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("file_path", name="uq_credentials_file_path"),
    )


def downgrade() -> None:
    op.drop_table("credentials")
