"""Embedded agent terminal service — PTY-backed claude CLI processes.

Spawns ``claude --append-system-prompt …`` inside the backend container
under a PTY, broadcasts stdout to all attached WebSocket listeners,
forwards user input to the PTY master fd, and updates the audit row in
``agent_terminal_sessions`` on lifecycle events (spawn / end / idle / crash).

Memory layout
-------------
Module-level state holds a dict of **active** sessions only. Each entry
is a :class:`_RuntimeSession` with:

* a :class:`ptyprocess.PtyProcess` handle (claude CLI process under PTY)
* an output ring buffer (last 64 KB of bytes for re-attach replay)
* a set of :class:`asyncio.Queue` listeners (each WS connection = one queue)
* an asyncio reader task that pumps PTY → buffer + listeners

State is **not persistent across BE restart** — by design, per the
session-lifecycle policy approved 2026-05-13. On startup, all DB rows
with ``ended_at IS NULL`` are marked ``terminated_by='server_restart'``.

Thread-safety
-------------
All mutation goes through ``asyncio.Lock`` per session. The reader task
holds the lock briefly while appending to buffer + fanning out to
listeners; ``attach`` holds it briefly to snapshot buffer + register
listener atomically (no race where chunks land between snapshot and
registration).
"""

from __future__ import annotations

import asyncio
import collections
import errno
import logging
import os
import re
import signal
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Optional

import ptyprocess
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.db.models.agent_terminal import AgentTerminalSession

logger = logging.getLogger(__name__)

PROJECTS_ROOT = Path("/opt/projects")
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$|^[a-z]$")
_VALID_ROLES = frozenset({"designer", "implementer", "auditor"})

# Output ring buffer: ~64 KB ≈ 10 000 lines of typical claude output.
# Chunks are bytes (raw PTY output incl. ANSI escapes). The deque
# trims oldest entries as new ones arrive.
_BUFFER_MAX_CHUNKS = 512  # each chunk up to ~128 B; aggregate ≈ 64 KB

#: Idle TTL — sessions with no IO from user (input) for this many seconds
#: get auto-killed by :func:`idle_cleanup`. 24h matches the policy
#: approved 2026-05-13.
IDLE_TTL_SECONDS = 24 * 3600

#: Grace period between SIGTERM and SIGKILL when ending a session.
SIGTERM_GRACE_SECONDS = 5


class AgentTerminalError(ValueError):
    """Raised on invalid input (bad slug/role, missing project, etc.)."""


class SessionConflictError(AgentTerminalError):
    """Active session for (user, role) already exists."""


class SessionNotFoundError(AgentTerminalError):
    """No active in-memory session for the given id."""


@dataclass
class _RuntimeSession:
    """In-memory runtime state for one active session."""

    id: uuid.UUID
    user_id: uuid.UUID
    role: str
    project_slug: str
    process: ptyprocess.PtyProcess
    output_buffer: collections.deque[bytes] = field(
        default_factory=lambda: collections.deque(maxlen=_BUFFER_MAX_CHUNKS),
    )
    listeners: set[asyncio.Queue[Optional[bytes]]] = field(default_factory=set)
    reader_task: Optional[asyncio.Task] = None
    last_input_at: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_sessions: dict[uuid.UUID, _RuntimeSession] = {}
_registry_lock = asyncio.Lock()


# ---------------------------------------------------------------------------
# Validation helpers
# ---------------------------------------------------------------------------


def _validate_role(role: str) -> None:
    if role not in _VALID_ROLES:
        raise AgentTerminalError(f"Invalid role: {role!r}")


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise AgentTerminalError(f"Invalid slug: {slug!r}")


def _resolve_agent_spec(slug: str, role: str) -> Path:
    """Return the validated path to ``.claude/agents/<role>/CLAUDE.md``.

    Raises:
        AgentTerminalError: project root missing or agent spec missing.
    """
    _validate_slug(slug)
    _validate_role(role)
    project_root = PROJECTS_ROOT / slug
    if not project_root.is_dir():
        raise AgentTerminalError(f"Project not found: {slug}")
    spec = project_root / ".claude" / "agents" / role / "CLAUDE.md"
    if not spec.is_file():
        raise AgentTerminalError(
            f"Agent spec missing for {slug}/{role}: expected {spec}",
        )
    return spec


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def spawn(
    *,
    user_id: uuid.UUID,
    role: str,
    project_slug: str,
    db: Session,
) -> AgentTerminalSession:
    """Spawn a new claude CLI process under PTY for ``(user, role, project)``.

    Returns the persisted :class:`AgentTerminalSession` row. The runtime
    state is registered in module-level ``_sessions`` keyed by the row id.

    Raises:
        AgentTerminalError: invalid role/slug or missing agent spec.
        SessionConflictError: an active session already exists for this
            ``(user_id, role)`` pair (enforced both via the DB partial
            unique index and an in-memory pre-check for a clean 409).
    """
    spec_path = _resolve_agent_spec(project_slug, role)
    append_prompt = spec_path.read_text(encoding="utf-8")

    existing = db.execute(
        select(AgentTerminalSession).where(
            AgentTerminalSession.user_id == user_id,
            AgentTerminalSession.role == role,
            AgentTerminalSession.ended_at.is_(None),
        ),
    ).scalar_one_or_none()
    if existing is not None:
        raise SessionConflictError(
            f"Active {role} session already running for user {user_id} (session_id={existing.id})",
        )

    env = {**os.environ, "TERM": "xterm-256color", "FORCE_COLOR": "1"}
    project_root = PROJECTS_ROOT / project_slug
    proc = ptyprocess.PtyProcess.spawn(
        ["claude", "--append-system-prompt", append_prompt],
        cwd=str(project_root),
        env=env,
        dimensions=(40, 120),
    )

    row = AgentTerminalSession(
        user_id=user_id,
        role=role,
        project_slug=project_slug,
        pid=proc.pid,
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    runtime = _RuntimeSession(
        id=row.id,
        user_id=user_id,
        role=role,
        project_slug=project_slug,
        process=proc,
    )

    async with _registry_lock:
        _sessions[row.id] = runtime

    runtime.reader_task = asyncio.create_task(
        _pump_output(runtime),
        name=f"agent-terminal-reader-{row.id}",
    )

    logger.info(
        "Spawned agent terminal session: id=%s user=%s role=%s project=%s pid=%s",
        row.id,
        user_id,
        role,
        project_slug,
        proc.pid,
    )
    return row


async def attach(session_id: uuid.UUID) -> AsyncIterator[bytes]:
    """Async iterator yielding bytes from the PTY: history first, then live.

    Caller (the WebSocket endpoint) consumes this iterator until it
    returns (session ended) or the WS disconnects. On WS disconnect, the
    `finally` block in the caller's loop is responsible for cleanup;
    this iterator's own `finally` removes the listener queue.
    """
    runtime = _sessions.get(session_id)
    if runtime is None:
        raise SessionNotFoundError(f"No active session: {session_id}")

    q: asyncio.Queue[Optional[bytes]] = asyncio.Queue(maxsize=256)
    async with runtime.lock:
        # Snapshot buffer + register listener atomically. From this point
        # the reader broadcasts new chunks to ``q`` directly, so there is
        # no gap and no duplication.
        history = list(runtime.output_buffer)
        runtime.listeners.add(q)

    try:
        for chunk in history:
            yield chunk
        while True:
            chunk = await q.get()
            if chunk is None:
                return  # process ended (sentinel)
            yield chunk
    finally:
        async with runtime.lock:
            runtime.listeners.discard(q)


async def write_input(session_id: uuid.UUID, data: bytes) -> None:
    """Forward keystrokes from the WS client to the PTY master fd."""
    runtime = _sessions.get(session_id)
    if runtime is None:
        raise SessionNotFoundError(f"No active session: {session_id}")
    runtime.last_input_at = time.time()
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, runtime.process.write, data)


async def resize(session_id: uuid.UUID, rows: int, cols: int) -> None:
    """Update PTY winsize after browser resize."""
    runtime = _sessions.get(session_id)
    if runtime is None:
        raise SessionNotFoundError(f"No active session: {session_id}")
    runtime.process.setwinsize(rows, cols)


async def end_session(
    session_id: uuid.UUID,
    *,
    terminated_by: str,
    db: Session,
) -> None:
    """Stop a running session. SIGTERM, grace, SIGKILL. DB row finalized.

    Idempotent — if the session has already ended (no runtime entry,
    or DB row already has ``ended_at`` set), this is a no-op.

    Args:
        session_id: id of the session to end
        terminated_by: one of ``'idle'``, ``'user'``, ``'crash'``,
            ``'server_restart'`` — recorded on the audit row
        db: SQLAlchemy session for the DB row update
    """
    runtime = _sessions.get(session_id)
    if runtime is None:
        # Possibly the reader task already finalized via crash path —
        # ensure DB row reflects something terminal.
        _finalize_db_row(
            session_id,
            terminated_by=terminated_by,
            exit_code=None,
            db=db,
        )
        return

    try:
        runtime.process.kill(signal.SIGTERM)
    except Exception:  # noqa: BLE001 — process may already be dead
        pass

    for _ in range(SIGTERM_GRACE_SECONDS * 10):
        if not runtime.process.isalive():
            break
        await asyncio.sleep(0.1)
    if runtime.process.isalive():
        try:
            runtime.process.kill(signal.SIGKILL)
        except Exception:  # noqa: BLE001
            pass

    await _cleanup_after_exit(runtime, terminated_by=terminated_by, db=db)


async def idle_cleanup(db: Session) -> int:
    """Kill sessions idle for > :data:`IDLE_TTL_SECONDS`. Returns count killed.

    Invoked periodically from the FastAPI lifespan task (every 5 min in
    production). "Idle" = no user input in TTL window. PTY output alone
    does not reset the clock — long-running claude generations are
    legitimate and should not extend the lease indefinitely.
    """
    now = time.time()
    to_kill: list[uuid.UUID] = [
        sid for sid, runtime in _sessions.items() if now - runtime.last_input_at > IDLE_TTL_SECONDS
    ]
    for sid in to_kill:
        try:
            await end_session(sid, terminated_by="idle", db=db)
        except Exception:
            logger.exception("idle_cleanup: failed to end session %s", sid)
    if to_kill:
        logger.info("idle_cleanup killed %d sessions", len(to_kill))
    return len(to_kill)


def mark_orphaned_on_startup(db: Session) -> int:
    """Mark all ``ended_at IS NULL`` rows as ``server_restart``-terminated.

    Invoked from the FastAPI lifespan on startup. Sessions cannot
    survive a BE container restart (PTY processes live in the container
    namespace), so every active row from the previous boot is an
    orphan — finalize it for audit cleanliness.

    Returns the number of rows finalized.
    """
    rows = (
        db.execute(
            select(AgentTerminalSession).where(
                AgentTerminalSession.ended_at.is_(None),
            ),
        )
        .scalars()
        .all()
    )
    from sqlalchemy import func

    for row in rows:
        row.ended_at = func.now()
        row.terminated_by = "server_restart"
    db.commit()
    if rows:
        logger.info("Marked %d orphan sessions as server_restart", len(rows))
    return len(rows)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _pump_output(runtime: _RuntimeSession) -> None:
    """Reader task: read PTY → append to buffer + broadcast to listeners.

    Terminates when the process exits (EOF / EIO from PTY). On exit,
    finalizes the DB row via :func:`_cleanup_after_exit` with
    ``terminated_by='crash'`` if exit code != 0, else ``'user'``.

    The reader uses ``run_in_executor`` because ptyprocess reads are
    blocking; using ``loop.add_reader`` would be slightly more efficient
    but requires manual ``read()`` calls on the master fd, which
    duplicates ptyprocess's existing edge-case handling.
    """
    loop = asyncio.get_running_loop()
    try:
        while True:
            chunk = await loop.run_in_executor(None, _safe_read, runtime.process)
            if chunk is None:
                break
            async with runtime.lock:
                runtime.output_buffer.append(chunk)
                for q in runtime.listeners:
                    try:
                        q.put_nowait(chunk)
                    except asyncio.QueueFull:
                        # Slow listener — drop oldest item, retry.
                        try:
                            q.get_nowait()
                            q.put_nowait(chunk)
                        except Exception:
                            pass
    except Exception:
        logger.exception("agent_terminal reader crashed for session %s", runtime.id)

    # Process has exited (cleanly or otherwise). Finalize via a fresh
    # DB session so we don't depend on the spawn-time session being open.
    from backend.db.session import SessionLocal

    exit_code = runtime.process.exitstatus
    terminated_by = "user" if exit_code == 0 else "crash"
    db = SessionLocal()
    try:
        await _cleanup_after_exit(runtime, terminated_by=terminated_by, db=db)
    finally:
        db.close()


def _safe_read(proc: ptyprocess.PtyProcess) -> Optional[bytes]:
    """Blocking PTY read. Returns ``None`` on EOF / EIO."""
    try:
        return proc.read(4096)
    except EOFError:
        return None
    except OSError as exc:
        if exc.errno == errno.EIO:
            return None
        raise


async def _cleanup_after_exit(
    runtime: _RuntimeSession,
    *,
    terminated_by: str,
    db: Session,
) -> None:
    """Send sentinel to listeners, finalize DB row, drop runtime entry."""
    async with runtime.lock:
        for q in list(runtime.listeners):
            try:
                q.put_nowait(None)
            except Exception:  # noqa: BLE001
                pass
        runtime.listeners.clear()

    _finalize_db_row(
        runtime.id,
        terminated_by=terminated_by,
        exit_code=runtime.process.exitstatus,
        db=db,
    )

    async with _registry_lock:
        _sessions.pop(runtime.id, None)


def _finalize_db_row(
    session_id: uuid.UUID,
    *,
    terminated_by: str,
    exit_code: Optional[int],
    db: Session,
) -> None:
    """Update the audit row with ``ended_at`` + ``exit_code`` + ``terminated_by``.

    Idempotent — if the row already has ``ended_at``, no-op. Tolerant of
    a missing row (no-op + log).
    """
    from sqlalchemy import func

    row = db.get(AgentTerminalSession, session_id)
    if row is None:
        logger.warning("finalize: row not found for session %s", session_id)
        return
    if row.ended_at is not None:
        return
    row.ended_at = func.now()
    row.exit_code = exit_code
    row.terminated_by = terminated_by
    db.commit()


# Exposed for tests — direct access to the registry for assertion.
def _get_runtime_for_test(session_id: uuid.UUID) -> Optional[_RuntimeSession]:
    return _sessions.get(session_id)
