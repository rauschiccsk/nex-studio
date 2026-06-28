"""Add the per-agent ``helper_model`` column (v2.0.0, CR-V2-038).

The AI Agent dynamically spawns ephemeral HELPER agents (Agent/Task tool) for parallel/bulk work in
Programovanie (charter §4). Those helpers default to the CLI's cheap/fast model (Haiku) — a sensible
default (the AI Agent does the hard core itself on its own Opus+max turn, and delegates bulk cheaply).
This adds an OPTIONAL per-(user, role) override so the Manažér can raise the helper model to Opus for
high-stakes builds ("identically to Dedo"), at higher token cost. Director decision 2026-06-28:
Haiku default + Opus option.

Net-new nullable ``VARCHAR(64)`` on ``user_agent_settings`` (same shape as ``model``). Purely additive —
NULL = "use the dispatch default" (Haiku), the correct default for every existing row. No CHECK (the
dispatchable model IDs are validated by the pydantic enum at the API layer, like ``model``/``effort``,
so the set can evolve without DDL churn). Only the AI Agent's row is consulted at dispatch (only the AI
Agent spawns helpers); an auditor row's value is simply unused.

Idempotent: ``ADD COLUMN IF NOT EXISTS`` / ``DROP COLUMN IF EXISTS``.

Revision ID: 077
Revises: 076
Create Date: 2026-06-28

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "077"
down_revision: Union[str, None] = "076"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE user_agent_settings ADD COLUMN IF NOT EXISTS helper_model VARCHAR(64)")


def downgrade() -> None:
    op.execute("ALTER TABLE user_agent_settings DROP COLUMN IF EXISTS helper_model")
