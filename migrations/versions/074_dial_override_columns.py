"""Add the Miera autonómie per-project / per-build override columns (v2.0.0, CR-V2-008 / AUTON-6).

The 4-level Miera autonómie dial resolves per build with the order ``per-build → per-project →
global``, first non-NULL wins (design §2.3). The GLOBAL layer is the ``system_settings`` KV
default (``DEFAULT_SETTINGS['miera_autonomie']`` — no migration). This migration adds the two
nullable override layers:

  * ``projects.miera_autonomie``       — per-project override; NULL = inherit the global.
  * ``pipeline_state.miera_autonomie`` — per-build override; NULL = inherit the per-project.

Both are net-new nullable ``VARCHAR(32)`` columns — purely additive, NO backfill needed (NULL is
the correct "inherit the next layer up" default for every existing row), NO CHECK constraint (the
dial value set lives in one place in the orchestrator resolver, which degrades an unrecognised
stored value to the next layer — the value set evolves with the dial without DDL churn).

Idempotent: ``ADD COLUMN IF NOT EXISTS`` / ``DROP COLUMN IF EXISTS`` so a re-run (or a clean DB
whose ``create_all`` already built the columns) never errors.

NB on the revision number: the build plan §6 migration table aspirationally reserved "076" for this
migration, with 074 (deploy/acceptance audit-log) and 075 (drop cr/bug flow_type) reserved for later
CRs (Milestone D customers/deploy + CR-V2-031). Those CRs have NOT landed yet, and the repo enforces
strictly CONTIGUOUS migration numbering (``test_alembic_migrations.test_migration_files_form_contiguous_chain``),
so this migration takes the next contiguous number **074** chaining after the current head **073** —
the migration number is a label, only the ``down_revision`` chain is load-bearing. The later
deploy-log / drop-cr-bug CRs take 075/076 when they land. (Flagged for the Manažér: a plan-vs-repo
numbering reconciliation; the resolver/columns/contract are unchanged by the number.)

Revision ID: 074
Revises: 073
Create Date: 2026-06-26

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "074"
down_revision: Union[str, None] = "073"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE projects ADD COLUMN IF NOT EXISTS miera_autonomie VARCHAR(32)")
    op.execute("ALTER TABLE pipeline_state ADD COLUMN IF NOT EXISTS miera_autonomie VARCHAR(32)")


def downgrade() -> None:
    op.execute("ALTER TABLE pipeline_state DROP COLUMN IF EXISTS miera_autonomie")
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS miera_autonomie")
