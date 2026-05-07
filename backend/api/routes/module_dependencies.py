"""REST router for :class:`~backend.db.models.projects.ModuleDependency`.

Exposes the standard CRUD surface for module dependency edges — the
join rows that materialise the per-project module DAG
(DESIGN.md §1.2 ``module_dependencies`` table, D-10 NEX Horizont module
seeding) — that back the ``ModuleGraph`` dependency-graph visualisation
and the ``ModuleRegistryPage`` (DESIGN.md §3.1, §3.2):

* ``GET    /``                 → paginated list (filter by ``module_id``
  and ``depends_on_module_id``).
* ``GET    /{dependency_id}``  → single edge by primary key.
* ``POST   /``                 → create a new dependency edge.
* ``PATCH  /{dependency_id}``  → partial update (no-op — the row has no
  mutable columns; retained for CRUD symmetry).
* ``DELETE /{dependency_id}``  → hard-delete an edge (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.module_dependency` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/module-dependencies``) is applied in ``backend/main.py`` via
``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.2 ``module_dependencies``, D-10 NEX
Horizont module seeding, and
:class:`backend.db.models.projects.ModuleDependency`):

* ``id``, ``created_at`` and ``updated_at`` are server-managed and
  therefore immutable. ``module_id`` and ``depends_on_module_id``
  together form the natural key
  (``uq_module_dependencies_module_id_depends_on_module_id``) and are
  both immutable — a dependency edge is either created or deleted,
  never rewritten in place (changing either endpoint produces a
  different edge). :class:`ModuleDependencyUpdate` deliberately
  exposes no mutable fields; ``PATCH`` exists for CRUD symmetry and
  returns the unmodified row.
* Self-loops (``module_id == depends_on_module_id``) are rejected by
  the service with a clean :class:`ValueError`, surfacing here as
  HTTP 409. Full multi-hop cycle detection is Architect /
  ``ModuleService`` territory (DESIGN.md §1.2 "Application-level cycle
  detection") — the router layer is not responsible for it.
* Unique constraint on ``(module_id, depends_on_module_id)`` is
  enforced both at the DB layer and pre-emptively by the service,
  so duplicate-edge attempts surface as HTTP 409 (not 500 /
  ``IntegrityError``).
* Invalid foreign keys (``module_id``, ``depends_on_module_id``) are
  rejected by the DB-level FK on ``flush`` / ``commit`` and propagate
  as a raw SQLAlchemy constraint error — the caller is expected to
  supply valid ``project_modules.id`` values (the schema-level UUID
  format check is enforced by Pydantic; existence is the DB's job).
* ``module_dependencies`` has **no** inbound foreign keys — no other
  table references it. Deletes are a straightforward hard-delete with
  no RESTRICT dependency check. Outbound FKs (``module_id``,
  ``depends_on_module_id``) both use ``ON DELETE CASCADE`` so deleting
  either parent module cleans up the edge automatically; this
  endpoint is the explicit inverse, removing a single edge from the
  DAG (the "break dependency" flow in the module-registry /
  dependency-graph UI).
* List filters (``module_id``, ``depends_on_module_id``) map to the
  two indexed FK columns and back the two canonical graph queries:
  "what does this module depend on" (outgoing edges, used by
  ``ModuleService.start_module()`` DESIGN.md §1.2 business rule) and
  "which modules depend on this one" (incoming edges, used by the
  dependency-graph visualisation in ``ModuleGraph`` —
  DESIGN.md §3.2).
* List ordering (``created_at DESC``) is owned by the service so the
  newest edge appears first, matching the typical Module Registry UI
  convention.
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ha_or_above
from backend.db.session import get_db
from backend.schemas.module_dependency import (
    ModuleDependencyCreate,
    ModuleDependencyRead,
    ModuleDependencyUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import module_dependency as module_dependency_service

router = APIRouter(
    tags=["Module Dependencies"],
    dependencies=[Depends(require_ha_or_above)],
)


def _map_value_error(exc: ValueError) -> HTTPException:
    """Translate a service-layer ``ValueError`` into an HTTP exception.

    Mirrors the ICC error-handling pattern: ``not found`` → 404,
    duplicates/conflicts/self-loops → 409, everything else
    (constraint / FK / validation failures) → 422.
    """
    message = str(exc)
    lowered = message.lower()
    if "not found" in lowered:
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    if "already exists" in lowered or "duplicate" in lowered or "conflict" in lowered or "self-loop" in lowered:
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=message)
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=message)


@router.get("", response_model=PaginatedResponse[ModuleDependencyRead])
def list_module_dependencies(
    module_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the dependent module — the module that requires "
            "the prerequisite to be done first. Backs the "
            "``ModuleService.start_module()`` prerequisite check "
            "(DESIGN.md §1.2) — 'what does this module depend on'."
        ),
    ),
    depends_on_module_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the prerequisite module — the module that other "
            "modules depend on. Backs the dependency-graph "
            "visualisation in ``ModuleGraph`` (DESIGN.md §3.2) — "
            "'which modules depend on this one'."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[ModuleDependencyRead]:
    """Return a paginated list of module dependency edges.

    Results are ordered by ``created_at DESC`` (newest first) — owned
    by the service layer, matching the typical Module Registry UI
    "newest first" convention.
    """
    try:
        rows = module_dependency_service.list_module_dependencies(
            db,
            module_id=module_id,
            depends_on_module_id=depends_on_module_id,
            limit=limit,
            offset=skip,
        )
        total = module_dependency_service.count_module_dependencies(
            db,
            module_id=module_id,
            depends_on_module_id=depends_on_module_id,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[ModuleDependencyRead](
        items=[ModuleDependencyRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{dependency_id}", response_model=ModuleDependencyRead)
def get_module_dependency(
    dependency_id: UUID,
    db: Session = Depends(get_db),
) -> ModuleDependencyRead:
    """Return a single module dependency edge by primary key."""
    try:
        dependency = module_dependency_service.get_by_id(db, dependency_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return ModuleDependencyRead.model_validate(dependency)


@router.post(
    "",
    response_model=ModuleDependencyRead,
    status_code=status.HTTP_201_CREATED,
)
def create_module_dependency(
    payload: ModuleDependencyCreate,
    db: Session = Depends(get_db),
) -> ModuleDependencyRead:
    """Create a new module dependency edge.

    Two invariants are validated by the service pre-flush so the caller
    receives a clean HTTP 409 (not a raw 500 / ``IntegrityError``):

    * Self-loops (``module_id == depends_on_module_id``) are rejected
      — a module cannot depend on itself (DESIGN.md §1.2).
    * ``UNIQUE(module_id, depends_on_module_id)`` — a duplicate edge
      is rejected pre-emptively.

    Invalid foreign keys (``module_id`` or ``depends_on_module_id``
    not matching an existing ``project_modules.id``) are rejected by
    the DB-level FK on commit and propagate as a raw SQLAlchemy
    constraint error — the caller is expected to supply valid
    ``project_modules.id`` values (the schema-level UUID format check
    is enforced by Pydantic; existence is the DB's job). Full
    multi-hop cycle detection is the caller's responsibility
    (Architect / ``ModuleService``) and is not performed here.
    """
    try:
        dependency = module_dependency_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(dependency)
    return ModuleDependencyRead.model_validate(dependency)


@router.patch("/{dependency_id}", response_model=ModuleDependencyRead)
def update_module_dependency(
    dependency_id: UUID,
    payload: ModuleDependencyUpdate,
    db: Session = Depends(get_db),
) -> ModuleDependencyRead:
    """Partially update a module dependency edge.

    :class:`ModuleDependency` has no mutable columns — ``id``,
    ``module_id``, ``depends_on_module_id``, ``created_at`` and
    ``updated_at`` are all immutable. ``module_id`` /
    ``depends_on_module_id`` form the natural key and must not be
    rewritten after the fact (a different pair is a different edge);
    ``updated_at`` is auto-stamped by the ORM on flush.

    :class:`ModuleDependencyUpdate` therefore exposes no fields; this
    endpoint exists only for symmetry with the rest of the CRUD
    surface. It confirms the row exists (returning HTTP 404 otherwise)
    and returns the unmodified instance. Redirecting an edge is a
    ``DELETE`` / ``POST`` operation, not an in-place edit.
    """
    try:
        dependency = module_dependency_service.update(db, dependency_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(dependency)
    return ModuleDependencyRead.model_validate(dependency)


@router.delete(
    "/{dependency_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_module_dependency(
    dependency_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a module dependency edge by primary key.

    ``module_dependencies`` has no inbound foreign keys, so no
    RESTRICT dependency check is required. Outbound FKs (``module_id``,
    ``depends_on_module_id``) both use ``ON DELETE CASCADE`` so
    deleting either parent module cleans up the edge automatically;
    this endpoint is the explicit inverse — the "break dependency"
    flow in the module-registry / dependency-graph UI.
    """
    try:
        module_dependency_service.delete(db, dependency_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
