"""Generic paginated response envelope used by list endpoints.

All REST list endpoints return the same shape — ``items``, ``total``,
``skip`` and ``limit`` — so the envelope is defined once here and
parameterised by the per-resource ``Read`` schema at the router.

Example::

    @router.get("", response_model=PaginatedResponse[GuardianPrecedentRead])
    def list_precedents(...) -> PaginatedResponse[GuardianPrecedentRead]:
        ...
"""

from __future__ import annotations

from typing import Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Standard paginated list envelope.

    Attributes:
        items: Current page of rows (already serialised to the resource's
            ``Read`` schema).
        total: Unfiltered total matching the same query filters — used by
            the frontend to render page counts.
        skip: Offset (number of rows skipped) that produced this page.
        limit: Page size requested by the caller.
    """

    items: list[T]
    total: int = Field(..., ge=0)
    skip: int = Field(..., ge=0)
    limit: int = Field(..., ge=1, le=100)
