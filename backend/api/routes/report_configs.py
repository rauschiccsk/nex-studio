"""REST router for :class:`~backend.db.models.reports.ReportConfig`.

Exposes the standard CRUD surface for per-project report configurations
— the senior / junior hourly rate (EUR) inputs used by the reporting
pipeline to convert AI and human time expenditure into monetary human-
cost estimates (DESIGN.md §1.9 Reporting Configuration, §1.23
``ReportConfig``, §6.5 reporting pipeline, business rule R-01) — that
back the ``ReportsPage`` / ``ProjectMetricsCard`` /
``AIvsHumanRatioDisplay`` UI (DESIGN.md §3.1, §3.2) and the
``SettingsPage`` rate-override form:

* ``GET    /``              → paginated list (filter by ``project_id``).
* ``GET    /{config_id}``   → single configuration by primary key.
* ``POST   /``              → create a new report configuration.
* ``PATCH  /{config_id}``   → partial update of the mutable rate fields.
* ``DELETE /{config_id}``   → hard-delete a configuration (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.report_config` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix (``/api/v1/report-configs``)
is applied in ``backend/main.py`` via ``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.9 Reporting Configuration, §1.23
``ReportConfig``, §6.5 reporting pipeline, business rule R-01, and
:class:`backend.db.models.reports.ReportConfig`):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``project_id`` is the row identity —
  ``UNIQUE(project_id)`` (``uq_report_configs_project_id``) — and must
  not be rewritten after the fact (DESIGN.md §1.9: "one config per
  project"). :class:`ReportConfigUpdate` deliberately omits it and the
  service enforces the contract defensively via an ``allowed_fields``
  allow-list.
* Both hourly rate columns carry DB-level server defaults
  (``senior_hourly_rate_eur = 75.0000``,
  ``junior_hourly_rate_eur = 35.0000``). The Pydantic schema mirrors
  those defaults, so ``POST`` callers may omit the rates and have the
  schema / DB supply the canonical values — matching the ORM defaults
  exactly.
* Unique constraint on ``project_id`` is enforced both at the DB layer
  and pre-emptively by the service, so duplicate-create attempts
  surface as HTTP 409 (not 500 / ``IntegrityError``). Invalid foreign
  keys (``project_id``) are rejected by the DB-level FK on commit and
  surface as HTTP 422.
* ``report_configs`` has **no inbound foreign keys** — no other table
  references it. ``DELETE`` is a straightforward hard-delete with no
  RESTRICT dependency check. The outbound FK ``project_id``
  (``ON DELETE CASCADE``) keeps the row self-consistent when the
  parent project is deleted; deleting the configuration itself is the
  explicit inverse, used to reset the rate model to defaults (a fresh
  row with the schema / DB defaults can be inserted via ``POST``
  afterwards).
* List filter (``project_id``) maps to the unique-indexed column and
  backs the reporting / settings UI: "load this project's report
  configuration". Since ``project_id`` is unique, filtering by it
  returns at most one row; the list endpoint still returns the
  paginated envelope for consistency with the rest of the CRUD surface
  (and to support the unfiltered admin listing).
* List ordering (``created_at DESC``) is owned by the service so the
  most recently created configuration appears first, matching the rest
  of the service layer.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ri_role
from backend.db.session import get_db
from backend.schemas.pagination import PaginatedResponse
from backend.schemas.report_config import (
    ReportConfigCreate,
    ReportConfigRead,
    ReportConfigUpdate,
)
from backend.services import report_config as report_config_service

router = APIRouter(
    tags=["Report Configs"],
    dependencies=[Depends(require_ri_role)],
)


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates / conflicts → 409, everything else (constraint / FK /
    validation failures) → 422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[ReportConfigRead])
def list_report_configs(
    project_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the project the report configuration belongs to. "
            "Hits the unique-indexed ``uq_report_configs_project_id`` "
            "column — backs the per-project ``ReportsPage`` / "
            "``SettingsPage`` query (DESIGN.md §3.1). Since "
            "``project_id`` is unique, this returns at most one row."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ReportConfigRead]:
    """Return a paginated list of report configurations.

    Results are ordered by ``created_at DESC`` (newest first) — owned by
    the service layer, matching the rest of the CRUD surface.
    """
    try:
        rows = report_config_service.list_report_configs(
            db,
            project_id=project_id,
            limit=limit,
            offset=skip,
        )
        total = report_config_service.count_report_configs(
            db,
            project_id=project_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ReportConfigRead](
        items=[ReportConfigRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{config_id}", response_model=ReportConfigRead)
def get_report_config(
    config_id: UUID,
    db: Session = Depends(get_db),
) -> ReportConfigRead:
    """Return a single report configuration by primary key."""
    try:
        cfg = report_config_service.get_by_id(db, config_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ReportConfigRead.model_validate(cfg)


@router.post(
    "",
    response_model=ReportConfigRead,
    status_code=status.HTTP_201_CREATED,
)
def create_report_config(
    payload: ReportConfigCreate,
    db: Session = Depends(get_db),
) -> ReportConfigRead:
    """Create a new report configuration.

    ``senior_hourly_rate_eur`` and ``junior_hourly_rate_eur`` default to
    the values set by the Pydantic schema / DB ``server_default`` when
    omitted (``75.0000`` / ``35.0000``). The
    ``UNIQUE(project_id)`` invariant is validated by the service
    pre-flush so a duplicate-project attempt surfaces as HTTP 409 (not
    a raw 500 / ``IntegrityError``). Invalid ``project_id`` (not
    matching an existing project) is rejected by the DB-level FK on
    commit and surfaces as HTTP 422.
    """
    try:
        cfg = report_config_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(cfg)
    return ReportConfigRead.model_validate(cfg)


@router.patch("/{config_id}", response_model=ReportConfigRead)
def update_report_config(
    config_id: UUID,
    payload: ReportConfigUpdate,
    db: Session = Depends(get_db),
) -> ReportConfigRead:
    """Partially update a report configuration's mutable fields.

    Only ``senior_hourly_rate_eur`` and ``junior_hourly_rate_eur`` are
    mutable — adjusting the cost-model inputs is the sole legitimate
    mutation on this row. ``id``, ``project_id``, ``created_at`` and
    ``updated_at`` are immutable — the row identity (the project it
    configures) must not be rewritten after the fact, and ``updated_at``
    is auto-stamped by the ORM on flush via ``onupdate=func.now()``.
    Fields omitted from the payload are left unchanged (PATCH
    semantics).
    """
    try:
        cfg = report_config_service.update(db, config_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(cfg)
    return ReportConfigRead.model_validate(cfg)


@router.delete(
    "/{config_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_report_config(
    config_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a report configuration by primary key.

    ``report_configs`` has no inbound foreign keys — no other table
    references it — so no RESTRICT dependency check is required. The
    outbound FK ``project_id`` (``ON DELETE CASCADE``) keeps the row
    self-consistent when the parent project is deleted; deleting the
    configuration itself is the explicit inverse, used to reset the
    rate model to defaults (a fresh row with the schema / DB defaults
    can be inserted via ``POST`` afterwards).
    """
    try:
        report_config_service.delete(db, config_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
