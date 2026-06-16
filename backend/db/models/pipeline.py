"""Orchestration pipeline models — F-007 Orchestration Cockpit (CR-NS-018).

Backend-owned single source of truth for the multi-agent pipeline. Two
tables:

* :class:`PipelineState` — one row per version (``version_id`` UNIQUE). A
  single ``SELECT`` answers "who is on turn and what's next" — the root
  problem F-007 solves. Created lazily by the orchestrator when a pipeline
  actually starts via the cockpit (never eager-seeded).
* :class:`PipelineMessage` — append-only typed message log (the
  ``.dedo-channel`` replacement). Director decisions land here as typed
  messages, giving a queryable audit trail.

Enums follow the codebase convention (``String`` + DB ``CHECK`` constraint,
not native PG ENUM). Phase 1 of F-007 §12.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, TIMESTAMP, UUID

from backend.db.models.base import Base, TimestampMixin, UUIDMixin

# Shared stage set (F-007 §3.1). String + CHECK rather than native enum.
_STAGES = (
    "'kickoff', 'gate_a', 'gate_b', 'gate_c', 'gate_d', 'gate_e', 'task_plan', 'build', 'gate_g', 'release', 'done'"
)
# Actors / message participants (F-007 §3.1, §4.2). ``system`` is message-only.
_ACTORS = "'coordinator', 'designer', 'customer', 'implementer', 'auditor', 'director'"
_PARTICIPANTS = "'coordinator', 'designer', 'customer', 'implementer', 'auditor', 'director', 'system'"


class PipelineState(Base, UUIDMixin, TimestampMixin):
    """Current orchestration state for one version's pipeline (F-007 §4.1)."""

    __tablename__ = "pipeline_state"

    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
    )
    flow_type = Column(String(16), nullable=False)
    current_stage = Column(String(16), nullable=False)
    current_actor = Column(String(16), nullable=False)
    # 'awaiting_director' is 17 chars — needs > 16.
    status = Column(String(20), nullable=False)
    #: Human-readable "what happens next" sentence rendered on the board.
    next_action = Column(Text, nullable=False, server_default="")
    is_regate = Column(Boolean, nullable=False, server_default="false")
    iteration = Column(Integer, nullable=False, server_default="0")
    #: Transient return marker (E7 route_to_designer, CR-NS-034): "build" while a Designer spec-fix turn
    #: is dispatched mid-build, so the dispatch-completion handler returns to _run_build_round (not a
    #: gate); cleared on the Designer's DONE. Persisted (not in-memory like gate_e_dispatch) because the
    #: route is an internal executor — the action route can't compute a transient marker for it.
    returns_to = Column(String(20), nullable=True)
    #: WS-D (CR-NS-036): when the pipeline ENTERED its current Director-wait status
    #: (``awaiting_director`` / ``blocked``). Maintained by the ``status`` ``set`` event listener
    #: below — set on entry, preserved across wait→wait, cleared on leaving. Powers the future
    #: metrics page's Director-wait time (now − ``awaiting_director_since``). Nullable; NULL whenever
    #: the pipeline isn't waiting on the Director.
    awaiting_director_since = Column(TIMESTAMP(timezone=True), nullable=True)
    #: E5 (CR-NS-043): accumulated total Director-wait time for this version (seconds). The status
    #: listener folds each finished wait interval (now − awaiting_director_since) in here on EXIT, so
    #: the metrics page has the lifetime total; a live open wait is added on top at read time. Starts
    #: fresh — versions finished before this column show 0 (no backfill, documented).
    total_director_wait_seconds = Column(Float, nullable=False, server_default="0")
    #: R1 dispatch resilience (v0.7.0, D1/D2). Repo HEAD captured at the START of a dispatch
    #: (``_begin_dispatch``), FROZEN across that dispatch's parse-retries (Seam #4) and reset to NULL on
    #: settle (the ``status`` set listener below + the ``pipeline_runner._run`` backstop). On an agent
    #: envelope-loss (timeout/crash) the engine audits ``dispatch_baseline_sha..HEAD`` so committed-but-lost
    #: work is surfaced to the Director, never silently lost. Distinct from the per-task ``Task.baseline_sha``
    #: (verify anchor) — a turn-start snapshot, not a verify anchor (Seam #7). Nullable; NULL when idle.
    dispatch_baseline_sha = Column(String(40), nullable=True)
    #: R1 durable single-flight (D2, CR-NS-027 hardening): True while a dispatch is in flight for this
    #: version. Enforced at the DB level so it survives a backend restart, complementing — not replacing —
    #: the in-memory ``pipeline_runner._ACTIVE_DISPATCH`` guard. Set by ``_begin_dispatch``; cleared on every
    #: settle (the ``status`` listener below) + the ``_run`` backstop + startup orphan recovery.
    dispatch_in_flight = Column(Boolean, nullable=False, server_default="false")

    __table_args__ = (
        UniqueConstraint("version_id", name="uq_pipeline_state_version_id"),
        CheckConstraint(
            # 'fast_fix' (F-009, CR-NS-094): the lightweight fast-fix lane — a distinct flow_type
            # (NOT reusing cr/bug, which are full-pipeline labels today) that traverses the shorter
            # kickoff→build→release→done path. Additive; the existing three are unchanged.
            "flow_type IN ('new_version', 'cr', 'bug', 'fast_fix')",
            name="ck_pipeline_state_flow_type",
        ),
        CheckConstraint(
            f"current_stage IN ({_STAGES})",
            name="ck_pipeline_state_current_stage",
        ),
        CheckConstraint(
            f"current_actor IN ({_ACTORS})",
            name="ck_pipeline_state_current_actor",
        ),
        CheckConstraint(
            "status IN ('agent_working', 'awaiting_director', 'blocked', 'paused', 'done')",
            name="ck_pipeline_state_status",
        ),
    )


class PipelineMessage(Base, UUIDMixin):
    """Append-only typed message in a version's pipeline (F-007 §4.2).

    Append-only — no ``updated_at`` (carries ``created_at`` only).
    """

    __tablename__ = "pipeline_message"

    version_id = Column(
        UUID(as_uuid=True),
        ForeignKey("versions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage = Column(String(16), nullable=False)
    author = Column(String(16), nullable=False)
    recipient = Column(String(16), nullable=False)
    kind = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    status = Column(String(16), nullable=False, server_default="pending")
    payload = Column(JSONB, nullable=True)
    created_at = Column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    # Monotonic insertion order (CR-NS-018). ``created_at`` uses ``func.now()``,
    # which is constant within a transaction, so same-transaction messages (a
    # worker's gate_report + the Coordinator's verify gate_report) tie on
    # ``created_at`` and order non-deterministically. ``seq`` disambiguates →
    # the board always shows the worker's report before its verification.
    seq = Column(BigInteger, Identity(), nullable=False)

    __table_args__ = (
        CheckConstraint(
            f"stage IN ({_STAGES})",
            name="ck_pipeline_message_stage",
        ),
        CheckConstraint(
            f"author IN ({_PARTICIPANTS})",
            name="ck_pipeline_message_author",
        ),
        CheckConstraint(
            f"recipient IN ({_PARTICIPANTS})",
            name="ck_pipeline_message_recipient",
        ),
        CheckConstraint(
            "kind IN ('kickoff', 'question', 'answer', 'gate_report', 'directive', "
            "'approval', 'return', 'verdict', 'notification')",
            name="ck_pipeline_message_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'delivered', 'answered', 'archived')",
            name="ck_pipeline_message_status",
        ),
        Index("ix_pipeline_message_version_created", "version_id", "created_at"),
        Index("ix_pipeline_message_version_seq", "version_id", "seq"),
    )


#: Statuses in which the pipeline is waiting on a Director decision (WS-D, CR-NS-036).
_DIRECTOR_WAIT_STATUSES = frozenset({"awaiting_director", "blocked"})


@event.listens_for(PipelineState.status, "set")
def _stamp_awaiting_director_since(target, value, oldvalue, initiator):
    """Maintain :attr:`PipelineState.awaiting_director_since` on every ``status`` change (WS-D).

    * ENTER a Director-wait status from a non-wait status → stamp ``now``.
    * wait → wait (e.g. ``blocked`` → ``awaiting_director``) → keep the original clock (don't reset).
    * LEAVE to any non-wait status → clear (``None``).

    All status writes go through this ORM attribute (no bulk ``UPDATE`` bypasses it), so this is the
    single, caller-agnostic source of truth — no need to touch the ~18 transition sites individually.
    ``oldvalue`` may be SQLAlchemy's ``NO_VALUE`` sentinel for a never-loaded attribute; ``not in``
    then treats it as a non-wait prior, which yields the correct stamp-on-entry behaviour.
    """
    if value == oldvalue:
        return
    if value in _DIRECTOR_WAIT_STATUSES:
        if oldvalue not in _DIRECTOR_WAIT_STATUSES:
            target.awaiting_director_since = datetime.now(timezone.utc)
    else:
        # LEAVE a wait status → fold the finished interval into the accumulated total (E5, CR-NS-043),
        # then clear. Only when we were actually waiting (awaiting_director_since set) — a non-wait→
        # non-wait set or an initial stamp has it None and contributes nothing.
        if target.awaiting_director_since is not None:
            elapsed = (datetime.now(timezone.utc) - target.awaiting_director_since).total_seconds()
            target.total_director_wait_seconds = (target.total_director_wait_seconds or 0.0) + elapsed
        target.awaiting_director_since = None


@event.listens_for(PipelineState.status, "set")
def _clear_dispatch_on_settle(target, value, oldvalue, initiator):
    """Clear the durable single-flight flag + dispatch baseline the moment the pipeline SETTLES (R1, D2).

    A dispatch is in flight only while ``status == 'agent_working'``. Any settle (``awaiting_director`` /
    ``blocked`` / ``paused`` / ``done``) means the dispatch has ended → drop ``dispatch_in_flight`` and reset
    ``dispatch_baseline_sha`` to NULL. This is the DRY "settle paths" clear the design calls for: every status
    write goes through this ORM attribute, so the ~18 transition sites need no individual touch, and a fresh
    dispatch re-captures the baseline from a clean NULL. ``pipeline_runner._run`` keeps a backstop clear for a
    settle that never goes through an ORM status set. A re-entry that keeps ``agent_working`` (the fast_fix
    one-touch chain) is NOT a settle, so the flag + baseline survive the chain (Seam #4). The lost-work audit
    reads the baseline BEFORE the settling status write, so the value is captured before this clears it."""
    if value == oldvalue or value == "agent_working":
        return
    target.dispatch_in_flight = False
    target.dispatch_baseline_sha = None
