"""R1 dispatch resilience — durable single-flight + lost-work baseline + session TTL (v0.7.0).

Adds the columns the cockpit's own dispatch path needs to survive a backend restart and to surface
agent work lost to a timeout/envelope-loss (F-007 / R1):

* ``pipeline_state.dispatch_baseline_sha`` (VARCHAR(40), nullable) — repo HEAD captured at dispatch
  start; the ``baseline..HEAD`` audit anchor for lost-work detection.
* ``pipeline_state.dispatch_in_flight`` (BOOLEAN NOT NULL DEFAULT false) — the durable single-flight flag.
* ``orchestrator_session.last_input_at`` (TIMESTAMPTZ NOT NULL DEFAULT now()) — last activity, for the
  7-day TTL retention task. Existing rows are backfilled from ``created_at``.

Idempotent (``ADD COLUMN IF NOT EXISTS`` + guarded backfill / DEFAULT / NOT NULL) so a re-run, or a clean
DB whose ``create_all`` already built the columns, never errors.

Revision ID: 066
Revises: 065
Create Date: 2026-06-16

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pipeline_state: dispatch baseline + durable single-flight flag.
    op.execute("ALTER TABLE pipeline_state ADD COLUMN IF NOT EXISTS dispatch_baseline_sha VARCHAR(40)")
    op.execute("ALTER TABLE pipeline_state ADD COLUMN IF NOT EXISTS dispatch_in_flight BOOLEAN NOT NULL DEFAULT false")

    # orchestrator_session.last_input_at — add nullable, backfill from created_at, then enforce the
    # final shape (DEFAULT now() + NOT NULL) so a NOT NULL add over existing rows never fails and the
    # backfill mirrors ``default=created_at`` rather than a blanket now().
    op.execute("ALTER TABLE orchestrator_session ADD COLUMN IF NOT EXISTS last_input_at TIMESTAMP WITH TIME ZONE")
    op.execute("UPDATE orchestrator_session SET last_input_at = created_at WHERE last_input_at IS NULL")
    op.execute("ALTER TABLE orchestrator_session ALTER COLUMN last_input_at SET DEFAULT now()")
    op.execute("ALTER TABLE orchestrator_session ALTER COLUMN last_input_at SET NOT NULL")


def downgrade() -> None:
    op.execute("ALTER TABLE orchestrator_session DROP COLUMN IF EXISTS last_input_at")
    op.execute("ALTER TABLE pipeline_state DROP COLUMN IF EXISTS dispatch_in_flight")
    op.execute("ALTER TABLE pipeline_state DROP COLUMN IF EXISTS dispatch_baseline_sha")
