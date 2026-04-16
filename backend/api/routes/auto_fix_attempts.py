"""REST router for :class:`~backend.db.models.delegations.AutoFixAttempt`.

Exposes the standard CRUD surface for auto-fix attempts (DESIGN.md §1.20
AutoFixAttempt, §2 ``auto_fix_attempts`` table) — the per-feat retry
history that powers the auto-fix telemetry surfaced on the
``DelegationStatus`` / ``GuardianPanel`` UI (DESIGN.md §3.1):

* ``GET    /``                       → paginated list (filter by
  ``feat_id`` and ``delegation_id``).
* ``GET    /{auto_fix_attempt_id}``  → single auto-fix attempt by
  primary key.
* ``POST   /``                       → create a new auto-fix attempt
  (``attempt_number`` is auto-assigned by the service layer as
  ``MAX(attempt_number) + 1`` per feat).
* ``PATCH  /{auto_fix_attempt_id}``  → partial update of the mutable
  fields.
* ``DELETE /{auto_fix_attempt_id}``  → hard-delete an auto-fix attempt
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.auto_fix_attempt` and handles commit/rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/auto-fix-attempts``) is applied in ``backend/main.py`` via
``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.20 AutoFixAttempt, §2
``auto_fix_attempts`` table and §6 REST API Architecture):

* ``id``, ``attempt_number``, ``created_at`` and ``updated_at`` are
  server-managed and therefore immutable. ``feat_id`` is an immutable
  foreign key — an auto-fix attempt belongs to exactly one feat for
  its lifetime. :class:`~backend.schemas.auto_fix_attempt.AutoFixAttemptUpdate`
  deliberately omits all immutable / server-managed fields.
* ``attempt_number`` is auto-assigned by the service layer as
  ``MAX(attempt_number) + 1`` for the supplied ``feat_id`` (starts at
  ``1`` for the first attempt). Concurrent-create races on the same
  feat surface as HTTP 409 via the DB-level
  ``UNIQUE(feat_id, attempt_number)`` constraint
  (``uq_auto_fix_attempts_feat_id_attempt_number``) — re-validated
  defensively by the service before flush.
* List filters (``feat_id``, ``delegation_id``) match the indexed
  column (``ix_auto_fix_attempts_feat_id``) and cover the natural
  lookup paths — "show every attempt for this feat" (feat-scoped
  retry history) and "which attempt spawned this delegation" (reverse
  lookup from the delegation panel).
* List ordering (``attempt_number ASC``) is owned by the service so
  attempts appear in their stable, human-readable retry sequence
  (attempt 1, attempt 2, …) — mirroring the numbering convention used
  across the Tasks / Delegation UI.
* ``auto_fix_attempts`` has no inbound FKs, so :func:`delete_auto_fix_attempt`
  needs no RESTRICT dependency check. ``delegation_id`` on this table
  uses ``ON DELETE SET NULL``, so deleting the referenced delegation
  silently nulls the reference without impacting this row.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.auto_fix_attempt import (
    AutoFixAttemptCreate,
    AutoFixAttemptRead,
    AutoFixAttemptUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import auto_fix_attempt as auto_fix_attempt_service

router = APIRouter(tags=["Auto Fix Attempts"])


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


@router.get("", response_model=PaginatedResponse[AutoFixAttemptRead])
def list_auto_fix_attempts(
    feat_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the feat the attempt belongs to. Hits the "
            "``ix_auto_fix_attempts_feat_id`` index — the core "
            "feat-scoped retry-history query (DESIGN.md §1.20)."
        ),
    ),
    delegation_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Reverse-lookup filter — which attempt spawned a given "
            "delegation (used by the ``DelegationStatus`` panel, "
            "DESIGN.md §3.1)."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[AutoFixAttemptRead]:
    """Return a paginated list of auto-fix attempts.

    Results are ordered by ``attempt_number ASC`` (attempt 1, attempt 2,
    …) — owned by the service layer, matching the retry-numbering
    convention used across the Tasks / Delegation UI (DESIGN.md §3.1).
    """
    try:
        rows = auto_fix_attempt_service.list_auto_fix_attempts(
            db,
            feat_id=feat_id,
            delegation_id=delegation_id,
            limit=limit,
            offset=skip,
        )
        total = auto_fix_attempt_service.count_auto_fix_attempts(
            db,
            feat_id=feat_id,
            delegation_id=delegation_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[AutoFixAttemptRead](
        items=[AutoFixAttemptRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{auto_fix_attempt_id}", response_model=AutoFixAttemptRead)
def get_auto_fix_attempt(
    auto_fix_attempt_id: UUID,
    db: Session = Depends(get_db),
) -> AutoFixAttemptRead:
    """Return a single auto-fix attempt by primary key."""
    try:
        attempt = auto_fix_attempt_service.get_by_id(db, auto_fix_attempt_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return AutoFixAttemptRead.model_validate(attempt)


@router.post(
    "",
    response_model=AutoFixAttemptRead,
    status_code=status.HTTP_201_CREATED,
)
def create_auto_fix_attempt(
    payload: AutoFixAttemptCreate,
    db: Session = Depends(get_db),
) -> AutoFixAttemptRead:
    """Create a new auto-fix attempt.

    ``attempt_number`` is auto-assigned by the service layer as
    ``MAX(attempt_number) + 1`` for the supplied ``feat_id`` (starts at
    ``1`` for the first attempt). ``fix_description`` and
    ``delegation_id`` default to ``NULL`` when omitted and are typically
    populated later via PATCH once the fix delegation is spawned /
    completes. Concurrent-create races on the same feat surface as HTTP
    409 via the DB-level ``UNIQUE(feat_id, attempt_number)`` constraint
    (re-validated defensively before flush). Missing or invalid
    ``feat_id`` / ``delegation_id`` foreign keys are rejected by the
    DB-level FKs and surface as HTTP 422.
    """
    try:
        attempt = auto_fix_attempt_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(attempt)
    return AutoFixAttemptRead.model_validate(attempt)


@router.patch("/{auto_fix_attempt_id}", response_model=AutoFixAttemptRead)
def update_auto_fix_attempt(
    auto_fix_attempt_id: UUID,
    payload: AutoFixAttemptUpdate,
    db: Session = Depends(get_db),
) -> AutoFixAttemptRead:
    """Partially update an auto-fix attempt's mutable fields.

    Only ``error_description``, ``fix_description`` and
    ``delegation_id`` are mutable. ``id``, ``feat_id``,
    ``attempt_number`` and ``created_at`` are immutable — the attempt
    identity and its position within the feat's retry sequence must not
    be rewritten after the fact; ``updated_at`` is refreshed by the ORM
    on flush via ``onupdate=func.now()``. Fields omitted from the
    payload are left unchanged.
    """
    try:
        attempt = auto_fix_attempt_service.update(db, auto_fix_attempt_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(attempt)
    return AutoFixAttemptRead.model_validate(attempt)


@router.delete(
    "/{auto_fix_attempt_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_auto_fix_attempt(
    auto_fix_attempt_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete an auto-fix attempt by primary key.

    ``auto_fix_attempts`` has no inbound FKs, so no RESTRICT dependency
    check is required. Deletion is reserved for test fixtures / admin
    tooling; routine operation retains the full retry history for
    reporting (DESIGN.md §1.20).
    """
    try:
        auto_fix_attempt_service.delete(db, auto_fix_attempt_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
