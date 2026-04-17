"""Pydantic schemas for User domain objects.

Mirrors :mod:`backend.db.models.foundation.User`.  Field names and
constraints (max lengths, role values, defaults) match the SQLAlchemy
model exactly so that ``UserRead.model_validate(user_orm_instance)``
round-trips cleanly.

Role values correspond to the ``ck_users_role`` CHECK constraint on the
``users`` table (``ri | ha | shu``).  The ORM column is a ``String(10)``
guarded by a DB-level CHECK rather than a Python Enum, so ``Literal`` is
the narrowest faithful representation — consistent with the approach
used in :mod:`backend.schemas.guardian`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# Mirrors the CHECK constraint `role IN ('ri', 'ha', 'shu')` on the
# ``users`` table.
UserRole = Literal["ri", "ha", "shu"]


class UserCreate(BaseModel):
    """Payload for creating a new user.

    ``id``, ``created_at`` and ``updated_at`` are server-generated and
    therefore excluded.  ``is_active`` defaults to ``True`` in the
    database (``server_default='true'``); we mirror that default here so
    callers may omit it.

    The ``password`` field accepts a plaintext password (min 8, max 128
    characters).  The service layer hashes it with bcrypt before persisting
    to the ``password_hash`` column.
    """

    username: str = Field(
        ...,
        min_length=1,
        max_length=50,
        description="Login name, unique across the system.",
    )
    email: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Contact email, unique across the system.",
    )
    password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="Plaintext password (hashed with bcrypt before storage).",
    )
    role: UserRole = Field(
        ...,
        description="Access level: ri (Director/Senior), ha (Medior), shu (Junior).",
    )
    is_active: bool = Field(
        default=True,
        description="Soft-disable flag; False excludes the user from auth.",
    )


class UserUpdate(BaseModel):
    """Partial update for an existing user.

    ``id`` and ``created_at`` are immutable.  ``updated_at`` is managed
    by the ORM via ``onupdate=func.now()`` and must not be set by
    clients.  All remaining fields are optional to support PATCH-style
    semantics.
    """

    username: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=50,
        description="Updated login name.",
    )
    email: Optional[str] = Field(
        default=None,
        min_length=1,
        max_length=255,
        description="Updated contact email.",
    )
    role: Optional[UserRole] = Field(
        default=None,
        description="Updated role: ri | ha | shu.",
    )
    is_active: Optional[bool] = Field(
        default=None,
        description="Updated active flag.",
    )


class ChangePasswordRequest(BaseModel):
    """Payload for the ``POST /users/{id}/change-password`` endpoint.

    Only the new plaintext password is required — the service layer hashes
    it with bcrypt before persisting.
    """

    new_password: str = Field(
        ...,
        min_length=8,
        max_length=128,
        description="New plaintext password (min 8, max 128 characters).",
    )


class UserRead(BaseModel):
    """Serialised representation of a user row.

    Mirrors :class:`backend.db.models.foundation.User` columns except
    ``password_hash`` which is deliberately excluded to prevent leaking
    credential hashes to API clients.
    ``from_attributes=True`` enables construction directly from an ORM
    instance via ``UserRead.model_validate(obj)``.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str = Field(..., min_length=1, max_length=50)
    email: str = Field(..., min_length=1, max_length=255)
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
