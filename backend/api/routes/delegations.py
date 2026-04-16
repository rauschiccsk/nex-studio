"""REST router for :class:`~backend.db.models.delegations.Delegation`.

Exposes the standard CRUD surface for delegations (DESIGN.md §1.18
Delegation, §1.7 ``delegations`` table, §2.6 Tasks (feat-level
delegation trigger)) — the per-CC-agent execution record that backs the
``DelegationPage`` / ``DelegationStatus`` UI (DESIGN.md §3.1):

* ``GET    /``                → paginated list (filter by ``task_id``,
  ``feat_id``, ``bug_fix_task_id``, ``bug_id``, ``status`` and
  ``cc_agent``).
* ``GET    /{delegation_id}``  → single delegation by primary key.
* ``POST   /``                 → create a new delegation.
* ``PATCH  /{delegation_id}``  → partial update of the mutable
  lifecycle fields.
* ``DELETE /{delegation_id}``  → hard-delete a delegation (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.delegation` and handles commit / rollback itself
so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/delegations``)
is applied in ``backend/main.py`` via ``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.18 Delegation, §1.7 ``delegations``
table, §2.6 ``POST /feats/{id}/delegate``, §3.1 ``DelegationStatus`` /
``CCOutput`` and §6 REST API Architecture):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``task_id``, ``feat_id``, ``bug_fix_task_id`` and
  ``bug_id`` are the delegation's "parent" references — a delegation
  belongs to at most one work item for its lifetime, so these FKs are
  immutable. All four use ``ON DELETE SET NULL`` at the DB level so the
  delegation row survives deletion of the originating work item.
  :class:`~backend.schemas.delegation.DelegationUpdate` deliberately
  omits all immutable / server-managed fields, plus ``cc_agent`` and
  ``prompt`` (which together form the delegation's execution contract
  and must not be rewritten after the fact).
* ``cc_agent`` is constrained by the ``ck_delegations_cc_agent`` DB
  CHECK (``ubuntu_cc``). ``status`` is constrained by the
  ``ck_delegations_status`` DB CHECK (``pending | running | done |
  failed``). Invalid values surface at schema validation time
  (HTTP 422) via the Pydantic ``Literal`` types.
* List filters (``task_id``, ``feat_id``, ``bug_fix_task_id``,
  ``bug_id``, ``status``, ``cc_agent``) match the indexed columns
  (``ix_delegations_status``, ``ix_delegations_started_at`` and the
  ``task_id`` index inherited from the FK declaration) and back the
  natural lookup paths — "show every delegation for this task / feat
  / bug fix / bug", "show all running delegations", "show all
  delegations for the ubuntu agent".
* List ordering (``started_at DESC``) is owned by the service so the
  most recently started delegations appear first — matching the
  ``DelegationPage`` "active delegation + live output" convention
  (DESIGN.md §3.1) and the indexed column
  (``ix_delegations_started_at``).
* Inbound FKs on ``delegations`` — ``execution_logs.delegation_id``
  (``ON DELETE CASCADE``), ``guardian_reviews.delegation_id``
  (``ON DELETE CASCADE``) and ``auto_fix_attempts.delegation_id``
  (``ON DELETE SET NULL``) — are handled at the DB level, so
  :func:`delete_delegation` needs no RESTRICT dependency check.
  Dependent execution logs and guardian reviews are cascaded; auto-fix
  attempts are silently NULL-ed out on flush.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.db.session import get_db
from backend.schemas.delegation import (
    DelegationCCAgent,
    DelegationCreate,
    DelegationRead,
    DelegationStatus,
    DelegationUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import delegation as delegation_service

router = APIRouter(tags=["Delegations"])


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


@router.get("", response_model=PaginatedResponse[DelegationRead])
def list_delegations(
    task_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the task this delegation executes — the core "
            "task-scoped delegation history (DESIGN.md §1.18). Hits the "
            "``ix_delegations_task_id`` index inherited from the FK."
        ),
    ),
    feat_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the feat this delegation executes (feat-level "
            "delegation trigger, DESIGN.md §2.6 ``POST "
            "/feats/{id}/delegate``)."
        ),
    ),
    bug_fix_task_id: Optional[UUID] = Query(
        default=None,
        description=("Filter by the bug-fix task this delegation executes (spawned from a bug fix workflow)."),
    ),
    bug_id: Optional[UUID] = Query(
        default=None,
        description=("Filter by the bug this delegation addresses directly."),
    ),
    status_filter: Optional[DelegationStatus] = Query(
        default=None,
        alias="status",
        description=(
            "Filter by lifecycle status (``pending`` | ``running`` | "
            "``done`` | ``failed``). Hits the ``ix_delegations_status`` "
            "index — backs the ``DelegationStatus`` panel filter "
            "(DESIGN.md §3.1)."
        ),
    ),
    cc_agent: Optional[DelegationCCAgent] = Query(
        default=None,
        description="Filter by the CC agent executing the delegation (``ubuntu_cc``).",
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[DelegationRead]:
    """Return a paginated list of delegations.

    Results are ordered by ``started_at DESC`` so the most recently
    started delegations appear first — matching the ``DelegationPage``
    "active delegation + live output" convention (DESIGN.md §3.1) and
    the indexed column (``ix_delegations_started_at``).
    """
    try:
        rows = delegation_service.list_delegations(
            db,
            task_id=task_id,
            feat_id=feat_id,
            bug_fix_task_id=bug_fix_task_id,
            bug_id=bug_id,
            status=status_filter,
            cc_agent=cc_agent,
            limit=limit,
            offset=skip,
        )
        total = delegation_service.count_delegations(
            db,
            task_id=task_id,
            feat_id=feat_id,
            bug_fix_task_id=bug_fix_task_id,
            bug_id=bug_id,
            status=status_filter,
            cc_agent=cc_agent,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[DelegationRead](
        items=[DelegationRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{delegation_id}", response_model=DelegationRead)
def get_delegation(
    delegation_id: UUID,
    db: Session = Depends(get_db),
) -> DelegationRead:
    """Return a single delegation by primary key."""
    try:
        delegation = delegation_service.get_by_id(db, delegation_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return DelegationRead.model_validate(delegation)


@router.post(
    "",
    response_model=DelegationRead,
    status_code=status.HTTP_201_CREATED,
)
def create_delegation(
    payload: DelegationCreate,
    db: Session = Depends(get_db),
) -> DelegationRead:
    """Create a new delegation.

    ``cc_agent``, ``status`` and ``started_at`` default to the DB-level
    ``server_default`` values (``ubuntu_cc``, ``pending`` and
    ``func.now()`` respectively) via the Pydantic schema when omitted.
    Nullable parent FKs (``task_id``, ``feat_id``, ``bug_fix_task_id``,
    ``bug_id``) default to ``None`` — exactly which is populated is a
    caller decision (a delegation is linked to at most one work item).
    Invalid or missing FK references are rejected by the DB-level FKs
    and surface as HTTP 422.
    """
    try:
        delegation = delegation_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(delegation)
    return DelegationRead.model_validate(delegation)


@router.patch("/{delegation_id}", response_model=DelegationRead)
def update_delegation(
    delegation_id: UUID,
    payload: DelegationUpdate,
    db: Session = Depends(get_db),
) -> DelegationRead:
    """Partially update a delegation's mutable lifecycle fields.

    Only ``status``, ``raw_output``, ``commit_hash``, ``started_at`` and
    ``completed_at`` are mutable — these are the lifecycle fields
    stamped as the delegation progresses (pending → running → done /
    failed). ``id``, ``task_id``, ``feat_id``, ``bug_fix_task_id``,
    ``bug_id``, ``cc_agent``, ``prompt`` and ``created_at`` are
    immutable — the delegation identity, the agent contract and the
    prompt injected into the agent must not be rewritten after the
    fact; ``updated_at`` is refreshed by the ORM on flush via
    ``onupdate=func.now()``. Fields omitted from the payload are left
    unchanged.
    """
    try:
        delegation = delegation_service.update(db, delegation_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(delegation)
    return DelegationRead.model_validate(delegation)


@router.delete(
    "/{delegation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_delegation(
    delegation_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a delegation by primary key.

    Inbound FKs — ``execution_logs.delegation_id``
    (``ON DELETE CASCADE``), ``guardian_reviews.delegation_id``
    (``ON DELETE CASCADE``) and ``auto_fix_attempts.delegation_id``
    (``ON DELETE SET NULL``) — are handled at the DB level, so
    dependent execution logs and guardian reviews are cascaded and
    auto-fix attempts are silently NULL-ed out on flush. No RESTRICT
    dependency check is required. Deletion is reserved for test
    fixtures / admin tooling; routine operation retains the full
    delegation history for reporting (DESIGN.md §1.7).
    """
    try:
        delegation_service.delete(db, delegation_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
