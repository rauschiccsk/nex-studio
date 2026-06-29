"""Widen the message-kind + block-reason CHECKs for the interactive consultation (v2.0.0, CR-V2-041).

The AI Agent translates a problem (Auditor upfront findings; later any mid-build blocker) into a queue of
plain-language DECISIONS the Manažér answers one-at-a-time by click — the production "Dedo on the screen"
(design: docs/architecture/interactive-consultation-design.md). This needs two new enum values:

  * ``pipeline_message.kind`` += ``'consultation'`` — the AI Agent's ai_agent→manazer decision queue
    (the decisions[] live in the message JSONB ``payload``).
  * ``pipeline_state.block_reason`` += ``'decision_needed'`` — distinct from ``agent_question`` (a single
    free-text Q) so the cockpit renders Decision Cards, not a free-text answer box.

Both are CHECK-constraint value widenings on existing String columns (the codebase's String+CHECK
convention) — drop + re-add each CHECK with the widened list. No data migration, no new column (the
consultation cursor is derived from the append-only message log). Idempotent: DROP CONSTRAINT IF EXISTS.

Revision ID: 078
Revises: 077
Create Date: 2026-06-29

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "078"
down_revision: Union[str, None] = "077"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_KIND_NEW = "kickoff,question,answer,gate_report,directive,approval,return,verdict,notification,consultation"
_KIND_OLD = "kickoff,question,answer,gate_report,directive,approval,return,verdict,notification"
_REASON_NEW = "agent_question,decision_needed,agent_error,system_error,parse_exhaustion"
_REASON_OLD = "agent_question,agent_error,system_error,parse_exhaustion"


def _in_list(csv: str) -> str:
    return ", ".join(f"'{v}'" for v in csv.split(","))


def _set_kind(values_csv: str) -> None:
    op.execute("ALTER TABLE pipeline_message DROP CONSTRAINT IF EXISTS ck_pipeline_message_kind")
    op.execute(
        f"ALTER TABLE pipeline_message ADD CONSTRAINT ck_pipeline_message_kind CHECK (kind IN ({_in_list(values_csv)}))"
    )


def _set_reason(values_csv: str) -> None:
    op.execute("ALTER TABLE pipeline_state DROP CONSTRAINT IF EXISTS ck_pipeline_state_block_reason")
    op.execute(
        f"ALTER TABLE pipeline_state ADD CONSTRAINT ck_pipeline_state_block_reason "
        f"CHECK (block_reason IS NULL OR block_reason IN ({_in_list(values_csv)}))"
    )


def upgrade() -> None:
    _set_kind(_KIND_NEW)
    _set_reason(_REASON_NEW)


def downgrade() -> None:
    _set_kind(_KIND_OLD)
    _set_reason(_REASON_OLD)
