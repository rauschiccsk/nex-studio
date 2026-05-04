"""Remove ``credentials`` from kb_documents.doc_category and clean up rows.

Companion to migration 038 (which created the standalone ``credentials``
table). After 2026-05-04 design, the ``credentials`` value is no longer
a valid ``kb_documents.doc_category``:

* The Phase A seed (kb_sync) registered 2 rows pointing at
  ``/home/icc/knowledge/credentials/{CREDENTIALS,MUFIS}.md``.
* These rows are deleted here. The actual on-disk move is performed
  manually on ANDROS (out-of-band of CI test DBs that don't have the
  files anyway).
* The CHECK constraint is recreated without ``credentials``.

Revision ID: 039
Revises: 038
Create Date: 2026-05-04
"""

from typing import Sequence, Union

from alembic import op

revision: str = "039"
down_revision: Union[str, None] = "038"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CATEGORIES_WITH_CREDENTIALS = (
    "standards",
    "decisions",
    "lessons",
    "patterns",
    "design",
    "behavior",
    "session",
    "icc",
    "infrastructure",
    "customers",
    "shuhari",
    "templates",
    "service-manuals",
    "deployment",
    "quarantine",
    "credentials",
    "project-status",
    "project-history",
    "project-architect",
    "project-other",
)

_CATEGORIES_WITHOUT_CREDENTIALS = tuple(c for c in _CATEGORIES_WITH_CREDENTIALS if c != "credentials")


def _check_clause(values: Sequence[str]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"doc_category IN ({quoted})"


def upgrade() -> None:
    # 1. Delete any kb_documents rows that still reference 'credentials'.
    #    (Idempotent — empty in CI, 2 rows on ANDROS pre-migration.)
    op.execute("DELETE FROM kb_documents WHERE doc_category = 'credentials'")

    # 2. Recreate the CHECK constraint without 'credentials'.
    op.drop_constraint("ck_kb_documents_doc_category", "kb_documents", type_="check")
    op.create_check_constraint(
        "ck_kb_documents_doc_category",
        "kb_documents",
        _check_clause(_CATEGORIES_WITHOUT_CREDENTIALS),
    )


def downgrade() -> None:
    # Restore the constraint that includes 'credentials'. We do NOT
    # re-insert deleted kb_documents rows — the credentials table is the
    # source of truth post-038 and downgrade is a manual recovery path.
    op.drop_constraint("ck_kb_documents_doc_category", "kb_documents", type_="check")
    op.create_check_constraint(
        "ck_kb_documents_doc_category",
        "kb_documents",
        _check_clause(_CATEGORIES_WITH_CREDENTIALS),
    )
