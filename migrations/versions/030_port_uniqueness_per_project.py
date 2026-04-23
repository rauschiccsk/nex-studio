"""Per-project port uniqueness — CHECK constraint + pre-existing data sanitisation.

A project should never have the same port number in two of its port
columns (backend / frontend / db / ui_design). NEX Studio shipped
without this guard, which let the nex-horizont row (created
2026-04-22) end up with backend_port=frontend_port=db_port=9100.
Surfaced by the NEX Test Krok 0 audit on 2026-04-23.

Upgrade order:

1. Sanitise pre-existing rows that would fail the new CHECK. The
   only such row today is ``nex-horizont`` — we null the duplicate
   slots (keep backend_port, drop the others). Conservative: the
   project row and its real allocation (backend_port=9100) are
   preserved; the bad frontend/db values disappear and can be
   re-set manually if they were intentional.
2. Add CK_projects_ports_distinct — six pair-wise ``IS DISTINCT``
   predicates that allow NULLs freely but reject equal non-NULL
   values.

Revision ID: 030
Revises: 029
Create Date: 2026-04-23
"""

from typing import Sequence, Union

from alembic import op

revision: str = "030"
down_revision: Union[str, None] = "029"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CHECK_NAME = "ck_projects_ports_distinct"

_CHECK_EXPR = """
    (backend_port IS NULL OR frontend_port IS NULL OR backend_port <> frontend_port)
AND (backend_port IS NULL OR db_port       IS NULL OR backend_port <> db_port)
AND (backend_port IS NULL OR ui_design_port IS NULL OR backend_port <> ui_design_port)
AND (frontend_port IS NULL OR db_port      IS NULL OR frontend_port <> db_port)
AND (frontend_port IS NULL OR ui_design_port IS NULL OR frontend_port <> ui_design_port)
AND (db_port       IS NULL OR ui_design_port IS NULL OR db_port <> ui_design_port)
"""


def upgrade() -> None:
    # 1. Sanitise the pre-existing nex-horizont row so the constraint can be added.
    op.execute(
        """
        UPDATE projects
        SET frontend_port = NULL,
            db_port = NULL
        WHERE slug = 'nex-horizont'
          AND backend_port = 9100
          AND frontend_port = 9100
          AND db_port = 9100
        """
    )

    # 2. Add the pair-wise distinctness CHECK.
    op.create_check_constraint(_CHECK_NAME, "projects", _CHECK_EXPR)


def downgrade() -> None:
    op.drop_constraint(_CHECK_NAME, "projects", type_="check")
    # No restore for the nex-horizont nulled columns — the original
    # values were the bug we fixed, restoring them would reintroduce it.
