"""REST router for :class:`~backend.db.models.guardian.GuardianReview`.

Exposes the standard CRUD surface for Guardian reviews (DESIGN.md §1.21
GuardianReview, §1.8 ``guardian_reviews`` table) — the Layer 1/2/3
review result attached to a delegation that backs the ``GuardianPanel``
UI (DESIGN.md §3.1):

* ``GET    /``                      → paginated list (filter by
  ``delegation_id``, ``layer``, ``risk_level`` and ``passed``).
* ``GET    /{guardian_review_id}``  → single Guardian review by primary
  key.
* ``POST   /``                      → create a new Guardian review.
* ``PATCH  /{guardian_review_id}``  → partial update of the mutable
  metric / precedent-filter fields.
* ``DELETE /{guardian_review_id}``  → hard-delete a Guardian review
  (HTTP 204).

All endpoints are synchronous ``def`` — pg8000 is a synchronous driver
and FastAPI dispatches sync endpoints to a thread pool automatically.
The router delegates every persistence operation to
:mod:`backend.services.guardian_review` and handles commit / rollback
itself so the service layer remains transaction-agnostic.

The router is prefix-less; the mount prefix
(``/api/v1/guardian-reviews``) is applied in ``backend/main.py`` via
``app.include_router`` (Task 4.27).

Design notes (per DESIGN.md §1.21 GuardianReview, §1.8
``guardian_reviews`` table and §6 REST API Architecture):

* ``id`` and ``created_at`` are server-managed and therefore
  immutable. There is **no** ``updated_at`` column — reviews are
  conceptually immutable per DESIGN.md §1.21, but the remaining
  updatable fields support post-hoc precedent filtering (see below).
  ``delegation_id`` is the review's parent reference — a review
  belongs to exactly one delegation for its lifetime, so the FK is
  immutable. ``delegation_id`` uses ``ON DELETE CASCADE`` at the DB
  level so the review is removed automatically when its parent
  delegation is dropped.
  :class:`~backend.schemas.guardian.GuardianReviewUpdate` deliberately
  omits all immutable / server-managed fields.
* ``layer`` is fixed at creation time (a review for ``layer1`` cannot
  become a ``layer2`` review) and is therefore excluded from the
  update schema and the service's allow-list.
* ``layer`` is constrained by the ``ck_guardian_reviews_layer`` DB
  CHECK (``layer1 | layer2 | layer3``) and ``risk_level`` by
  ``ck_guardian_reviews_risk_level`` (``low | medium | high |
  critical``). Invalid values surface at schema validation time
  (HTTP 422) via the Pydantic ``Literal`` aliases.
* ``findings`` defaults to ``[]`` and ``passed`` defaults to ``False``
  via DB-level ``server_default``; the Pydantic schema mirrors those
  defaults so callers may omit them on create.
* ``risk_level``, ``findings``, ``passed`` and ``duration_ms`` remain
  updatable to support post-hoc precedent filtering — applying a new
  ``allow`` precedent may flip ``passed`` from ``False`` to ``True``
  and prune matched entries from ``findings`` (DESIGN.md §1.21 /
  §1.22 interaction).
* List filters (``delegation_id``, ``layer``, ``risk_level``,
  ``passed``) match the indexed columns
  (``ix_guardian_reviews_delegation_id``,
  ``ix_guardian_reviews_layer``, ``ix_guardian_reviews_risk_level``)
  and back the natural lookup paths — "show every review for this
  delegation" (the core delegation-scoped query that drives the
  Guardian panel, DESIGN.md §3.1 ``GuardianPanel``), "show all
  Layer 2 reviews", "show all critical-risk reviews" and "show all
  blocking (``passed=False``) reviews".
* List ordering (``created_at DESC``) is owned by the service so the
  most recently recorded reviews appear first — matching the
  reporting / audit-log conventions used throughout the UI.
* ``guardian_reviews`` has no inbound FKs, so :func:`delete_guardian_review`
  needs no RESTRICT dependency check — simply drop the row. Deletion
  is reserved for test fixtures / admin tooling; routine operation
  retains the full review history (DESIGN.md §1.21).
"""

from __future__ import annotations

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from backend.core.security import require_ha_or_above
from backend.db.session import get_db
from backend.schemas.guardian import (
    GuardianReviewCreate,
    GuardianReviewLayer,
    GuardianReviewRead,
    GuardianReviewRiskLevel,
    GuardianReviewUpdate,
)
from backend.schemas.pagination import PaginatedResponse
from backend.services import guardian_review as guardian_review_service

router = APIRouter(
    tags=["Guardian Reviews"],
    dependencies=[Depends(require_ha_or_above)],
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


@router.get("", response_model=PaginatedResponse[GuardianReviewRead])
def list_guardian_reviews(
    delegation_id: Optional[UUID] = Query(
        default=None,
        description=(
            "Filter by the delegation this review belongs to — the core "
            "delegation-scoped query that drives the Guardian panel "
            "(DESIGN.md §3.1). Hits the ``ix_guardian_reviews_delegation_id`` "
            "index."
        ),
    ),
    layer: Optional[GuardianReviewLayer] = Query(
        default=None,
        description=(
            "Filter by Guardian pipeline layer (``layer1`` | ``layer2`` | "
            "``layer3``). Hits the ``ix_guardian_reviews_layer`` index."
        ),
    ),
    risk_level: Optional[GuardianReviewRiskLevel] = Query(
        default=None,
        description=(
            "Filter by maximum risk level of the changed files (``low`` | "
            "``medium`` | ``high`` | ``critical``). Hits the "
            "``ix_guardian_reviews_risk_level`` index."
        ),
    ),
    passed: Optional[bool] = Query(
        default=None,
        description=(
            "Filter by blocking flag — ``False`` lists reviews that stopped "
            "the pipeline, ``True`` lists reviews that passed cleanly."
        ),
    ),
    skip: int = Query(default=0, ge=0, description="Number of rows to skip."),
    limit: int = Query(default=50, ge=1, le=100, description="Maximum rows to return."),
    db: Session = Depends(get_db),
) -> PaginatedResponse[GuardianReviewRead]:
    """Return a paginated list of Guardian reviews.

    Results are ordered by ``created_at DESC`` so the most recently
    recorded reviews appear first — matching the reporting / audit-log
    conventions used throughout the UI.
    """
    try:
        rows = guardian_review_service.list_guardian_reviews(
            db,
            delegation_id=delegation_id,
            layer=layer,
            risk_level=risk_level,
            passed=passed,
            limit=limit,
            offset=skip,
        )
        total = guardian_review_service.count_guardian_reviews(
            db,
            delegation_id=delegation_id,
            layer=layer,
            risk_level=risk_level,
            passed=passed,
        )
    except ValueError as exc:
        raise _map_value_error(exc) from exc

    return PaginatedResponse[GuardianReviewRead](
        items=[GuardianReviewRead.model_validate(row) for row in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


@router.get("/{guardian_review_id}", response_model=GuardianReviewRead)
def get_guardian_review(
    guardian_review_id: UUID,
    db: Session = Depends(get_db),
) -> GuardianReviewRead:
    """Return a single Guardian review by primary key."""
    try:
        review = guardian_review_service.get_by_id(db, guardian_review_id)
    except ValueError as exc:
        raise _map_value_error(exc) from exc
    return GuardianReviewRead.model_validate(review)


@router.post(
    "",
    response_model=GuardianReviewRead,
    status_code=status.HTTP_201_CREATED,
)
def create_guardian_review(
    payload: GuardianReviewCreate,
    db: Session = Depends(get_db),
) -> GuardianReviewRead:
    """Create a new Guardian review.

    ``findings`` defaults to ``[]`` and ``passed`` to ``False`` via the
    Pydantic schema (mirroring the DB ``server_default`` values) when
    omitted; ``duration_ms`` is optional. An invalid or missing
    ``delegation_id`` FK reference is rejected by the DB-level FK and
    surfaces as HTTP 422.
    """
    try:
        review = guardian_review_service.create(db, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(review)
    return GuardianReviewRead.model_validate(review)


@router.patch("/{guardian_review_id}", response_model=GuardianReviewRead)
def update_guardian_review(
    guardian_review_id: UUID,
    payload: GuardianReviewUpdate,
    db: Session = Depends(get_db),
) -> GuardianReviewRead:
    """Partially update a Guardian review's mutable fields.

    Only ``risk_level``, ``findings``, ``passed`` and ``duration_ms``
    may be changed. ``id``, ``delegation_id``, ``layer`` and
    ``created_at`` are immutable — the review identity, its parent
    delegation and the pipeline layer that produced it must not be
    rewritten after the fact (DESIGN.md §1.21 "Reviews are
    immutable"). Post-hoc precedent filtering is the primary use case:
    applying a new ``allow`` precedent may flip ``passed`` from
    ``False`` to ``True`` and prune matched entries from ``findings``.
    Fields omitted from the payload are left unchanged.
    """
    try:
        review = guardian_review_service.update(db, guardian_review_id, payload)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    db.refresh(review)
    return GuardianReviewRead.model_validate(review)


@router.delete(
    "/{guardian_review_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
)
def delete_guardian_review(
    guardian_review_id: UUID,
    db: Session = Depends(get_db),
) -> Response:
    """Hard-delete a Guardian review by primary key.

    ``guardian_reviews`` has no inbound FKs, so no RESTRICT dependency
    check is required — simply drop the row. Deletion is reserved for
    test fixtures / admin tooling; routine operation retains the full
    review history (DESIGN.md §1.21).
    """
    try:
        guardian_review_service.delete(db, guardian_review_id)
        db.commit()
    except ValueError as exc:
        db.rollback()
        raise _map_value_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
