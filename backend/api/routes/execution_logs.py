"""REST router for :class:`~backend.db.models.delegations.ExecutionLog`.

Exposes the standard CRUD surface for execution logs (DESIGN.md §1.19
ExecutionLog, §1.7 ``execution_logs`` table) — the per-CC-delegation
result record (status, tokens, cost, commit hash) that backs the
``DelegationStatus`` / ``CCOutput`` UI panels (DESIGN.md §3.1) and the
``ProjectMetricsCard`` reporting view (DESIGN.md §3.2):

* ``GET    /``                    → paginated list (filter by
  ``delegation_id``, ``task_id``, ``status`` and ``commit_verified``).
* ``GET    /{execution_log_id}``  → single execution log by primary
  key.
* ``POST   /``                    → create a new execution log.
* ``PATCH  /{execution_log_id}``  → partial update of the mutable
  metric / verification fields.
* ``DELETE /{execution_log_id}``  → hard-delete an execution log
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.execution_log` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/execution-logs``) is applied in ``backend/main.py`` via
``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.19 ExecutionLog, §1.7 ``execution_logs``
table and §6 REST API Architecture):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``delegation_id`` and ``task_id`` are the log's
  "parent" references — an execution log belongs to exactly one
  delegation (and optionally one task) for its lifetime, so both FKs
  are immutable. ``delegation_id`` uses ``ON DELETE CASCADE`` and
  ``task_id`` uses ``ON DELETE SET NULL`` at the DB level so cleanup
  happens automatically when the parent row is dropped.
  :class:`~backend.schemas.execution_log.ExecutionLogUpdate`
  deliberately omits all immutable / server-managed fields.
* ``status`` is constrained by the ``ck_execution_logs_status`` DB
  CHECK (``done | failed``). Invalid values surface at schema
  validation time (HTTP 422) via the Pydantic ``Literal`` type.
* ``commit_verified`` defaults to ``False`` via the DB-level
  ``server_default`` and is flipped to ``True`` only after the
  GitHub-API verification job confirms the reported ``commit_hash``
  exists on the target branch (DESIGN.md §1.7 "Commit verification").
* List filters (``delegation_id``, ``task_id``, ``status``,
  ``commit_verified``) match the indexed columns
  (``ix_execution_logs_delegation_id``, ``ix_execution_logs_task_id``)
  and back the natural lookup paths — "show every log for this
  delegation", "show every log for this task", "show all failed
  executions", "show all unverified commits" (for the GitHub
  verification job).
* List ordering (``created_at DESC``) is owned by the service so the
  most recently recorded executions appear first — matching the
  reporting views which surface the latest activity at the top.
* ``execution_logs`` has no inbound FKs, so :func:`delete_execution_log`
  needs no RESTRICT dependency check. Deletion is reserved for test
  fixtures / admin tooling; routine operation retains the full
  execution history for reporting (DESIGN.md §1.7).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ha_or_above
from backend.db.session import get_db
from backend.schemas.execution_log import (
    ExecutionLogCreate,
    ExecutionLogRead,
    ExecutionLogStatus,
    ExecutionLogUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import execution_log as execution_log_service

router = APIRouter(
    tags=["Execution Logs"],
    dependencies=[Depends(require_ha_or_above)],
)


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates/conflicts → 409, everything else (constraint / FK /
    validation failures) → 422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[ExecutionLogRead])
def list_execution_logs(
    delegation_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the delegation this log belongs to — the core "
            "delegation-scoped history query (DESIGN.md §1.19). Hits the "
            "``ix_execution_logs_delegation_id`` index."
        ),
    ),
    task_id: Optional[UUID] = Query(
        default=None,
        description=("Filter by the task this execution targeted. Hits the ``ix_execution_logs_task_id`` index."),
    ),
    status_filter: Optional[ExecutionLogStatus] = Query(
        default=None,
        alias="status",
        description=(
            "Filter by terminal status (``done`` | ``failed``). Backs "
            'the reporting views\' "all failed executions" lookup.'
        ),
    ),
    commit_verified: Optional[bool] = Query(
        default=None,
        description=(
            "Filter by GitHub-verification flag. Typically ``False`` to "
            "drive the GitHub verification job, ``True`` to list "
            "already-verified commits for reporting (DESIGN.md §1.7)."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ExecutionLogRead]:
    """Return a paginated list of execution logs.

    Results are ordered by ``created_at DESC`` so the most recently
    recorded executions appear first — matching the reporting
    conventions used throughout the UI.
    """
    try:
        rows = execution_log_service.list_execution_logs(
            db,
            delegation_id=delegation_id,
            task_id=task_id,
            status=status_filter,
            commit_verified=commit_verified,
            limit=limit,
            offset=skip,
        )
        total = execution_log_service.count_execution_logs(
            db,
            delegation_id=delegation_id,
            task_id=task_id,
            status=status_filter,
            commit_verified=commit_verified,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ExecutionLogRead](
        items=[ExecutionLogRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{execution_log_id}", response_model=ExecutionLogRead)
def get_execution_log(
    execution_log_id: UUID,
    db: Session = Depends(get_db),
) -> ExecutionLogRead:
    """Return a single execution log by primary key."""
    try:
        log = execution_log_service.get_by_id(db, execution_log_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ExecutionLogRead.model_validate(log)


@router.post(
    "",
    response_model=ExecutionLogRead,
    status_code=status.HTTP_201_CREATED,
)
def create_execution_log(
    payload: ExecutionLogCreate,
    db: Session = Depends(get_db),
) -> ExecutionLogRead:
    """Create a new execution log.

    ``commit_verified`` defaults to ``False`` via the Pydantic schema
    (mirroring the DB ``server_default='false'``) when omitted; the
    flag is flipped to ``True`` only after GitHub API verification
    (DESIGN.md §1.7 "Commit verification"). All other optional fields
    default to ``None`` when omitted. Invalid or missing FK references
    (``delegation_id``, ``task_id``) are rejected by the DB-level FKs
    and surface as HTTP 422.
    """
    try:
        log = execution_log_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(log)
    return ExecutionLogRead.model_validate(log)


@router.patch("/{execution_log_id}", response_model=ExecutionLogRead)
def update_execution_log(
    execution_log_id: UUID,
    payload: ExecutionLogUpdate,
    db: Session = Depends(get_db),
) -> ExecutionLogRead:
    """Partially update an execution log's mutable metric / verification fields.

    Only ``status``, ``duration_seconds``, ``input_tokens``,
    ``output_tokens``, ``total_cost_usd``, ``commit_hash`` and
    ``commit_verified`` are mutable. ``id``, ``delegation_id``,
    ``task_id`` and ``created_at`` are immutable — the log identity and
    its parent references must not be rewritten after the fact (the DB
    handles orphaning via ``ON DELETE CASCADE`` / ``ON DELETE SET
    NULL`` automatically); ``updated_at`` is refreshed by the ORM on
    flush via ``onupdate=func.now()``. Fields omitted from the payload
    are left unchanged.
    """
    try:
        log = execution_log_service.update(db, execution_log_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(log)
    return ExecutionLogRead.model_validate(log)


@router.delete(
    "/{execution_log_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_execution_log(
    execution_log_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an execution log by primary key.

    ``execution_logs`` has no inbound FKs, so no RESTRICT dependency
    check is required — simply drop the row. Deletion is reserved for
    test fixtures / admin tooling; routine operation retains the full
    execution history for reporting (DESIGN.md §1.7).
    """
    try:
        execution_log_service.delete(db, execution_log_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
