"""Switch project_modules.code to kebab-case identifiers.

Replaces the NEX Genesis 8.3 legacy of 2–6 uppercase alnum codes
(``PAB``, ``MM``, ``GSC``) with Clean-Code-style intention-revealing
identifiers (``partner-catalog``, ``module-manager``). Widens the
column to ``VARCHAR(50)`` to fit the new naming, renames the two
existing rows in place and locks the format with a CHECK constraint
that mirrors the Pydantic regex on :mod:`backend.schemas.project_module`.

Existing rows at migration time (``2026-04-23``):

* ``nex-test`` / ``MM``  → ``module-manager``
* ``nex-test`` / ``PAB`` → ``partner-catalog``
* ``nex-horizont`` / ``PAB`` → ``partner-catalog``

The UPDATE runs *before* the CHECK is added so the rename stays
deterministic and atomic; hard-coded ``WHERE`` clauses are used in
favour of a mapping table — only three rows exist, and a one-shot
rename is the whole point of the migration.

Revision ID: 032
Revises: 031
Create Date: 2026-04-23
"""

from typing import Sequence, Union

from alembic import op
from sqlalchemy import String
from sqlalchemy.dialects.postgresql import VARCHAR

revision: str = "032"
down_revision: Union[str, None] = "031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHECK_NAME = "ck_project_modules_code_format"
# Mirrors ``backend.schemas.project_module.MODULE_CODE_PATTERN``:
# starts with a lowercase letter, ends with lowercase letter/digit,
# interior may contain kebab-case segments. Single-character codes
# are rejected because the anchor requires both start + end chars.
_CHECK_EXPR = r"code ~ '^[a-z][a-z0-9-]*[a-z0-9]$'"


def upgrade() -> None:
    # 1. Widen column so the rename fits.
    op.alter_column(
        "project_modules",
        "code",
        existing_type=VARCHAR(length=10),
        type_=String(length=50),
        existing_nullable=False,
    )

    # 2. Rename existing rows. Scoped by project slug + old code so an
    #    accidental re-run on partially-migrated data stays a no-op.
    op.execute(
        """
        UPDATE project_modules pm
        SET code = 'module-manager'
        FROM projects p
        WHERE pm.project_id = p.id
          AND p.slug = 'nex-test'
          AND pm.code = 'MM'
        """
    )
    op.execute(
        """
        UPDATE project_modules pm
        SET code = 'partner-catalog'
        FROM projects p
        WHERE pm.project_id = p.id
          AND pm.code = 'PAB'
          AND p.slug IN ('nex-test', 'nex-horizont')
        """
    )

    # 3. Lock the format so future inserts cannot regress.
    op.create_check_constraint(_CHECK_NAME, "project_modules", _CHECK_EXPR)


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "project_modules", type_="check")

    op.execute(
        """
        UPDATE project_modules pm
        SET code = 'MM'
        FROM projects p
        WHERE pm.project_id = p.id
          AND p.slug = 'nex-test'
          AND pm.code = 'module-manager'
        """
    )
    op.execute(
        """
        UPDATE project_modules pm
        SET code = 'PAB'
        FROM projects p
        WHERE pm.project_id = p.id
          AND pm.code = 'partner-catalog'
          AND p.slug IN ('nex-test', 'nex-horizont')
        """
    )

    op.alter_column(
        "project_modules",
        "code",
        existing_type=String(length=50),
        type_=VARCHAR(length=10),
        existing_nullable=False,
    )
