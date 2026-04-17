"""Pydantic schemas for the project-scoped Architect endpoints.

These schemas are used by :mod:`backend.api.routes.architect` — the
project-scoped Architect router that exposes session create / list /
detail / close under ``/projects/{project_id}/architect`` and
``/architect/sessions/{session_id}``.

Separated from :mod:`backend.schemas.architect_session` (the generic
CRUD schemas) because the project-scoped endpoints derive
``project_id`` from the URL path and ``created_by`` from the JWT — the
create payload only needs the optional ``module_id``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

ArchitectSessionStatus = Literal["active", "closed"]


class ArchitectSessionCreate(BaseModel):
    """Payload for creating a new Architect session via the project-scoped endpoint.

    ``project_id`` is taken from the URL path parameter and
    ``created_by`` from the authenticated user — neither appears in the
    request body.  Only ``module_id`` is accepted (optional).
    """

    module_id: Optional[UUID] = Field(
        default=None,
        description=("Optional project module scope. ``None`` opens a Foundation / project-level session."),
    )


class ArchitectSessionRead(BaseModel):
    """Serialised representation returned by the project-scoped Architect endpoints.

    Contains the fields specified in the task: id, project_id,
    module_id, status, created_at.  Also includes created_by,
    closed_at and updated_at for completeness — these are present on
    the ORM model and useful for the frontend.
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    project_id: UUID
    module_id: Optional[UUID] = None
    status: ArchitectSessionStatus
    created_by: UUID
    closed_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ArchitectMessageSend(BaseModel):
    """Payload for sending a user message to the Architect AI.

    Used by ``POST /architect/sessions/{session_id}/message``.
    The session context (project, module) is resolved from the session.
    """

    content: str = Field(
        ...,
        min_length=1,
        description="User message content to send to the Architect AI.",
    )
