"""REST router for ``/api/v1/project-specs/*`` — per-project spec browser.

Provides a filesystem view of ``/opt/projects/<slug>/docs/`` for every
project. The frontend's ``<KbTree />`` component (built for the KB
browser at ``/kb``) consumes the same ``KnowledgeDoc``-shaped response,
so a single page (``/project-specs``) can render the unified tree
without adaptation.

Why this exists (Director observation 2026-05-13):
Designer / Implementer / Auditor agents write spec documents into
``/opt/projects/<slug>/docs/`` (single source of truth), but the
Director had no UI to browse them — only ``ssh`` + ``nano``. This
router closes that gap.

Permissions (v1):
- All endpoints require ``ri`` role (Director). The v1 cut keeps the
  scope tight while the feature is validated. Per-project membership
  filtering (``project_members`` table) can be added later for the
  ``ha`` / ``shu`` cuts.

Path safety:
- ``slug`` is validated against the kebab-case regex.
- ``path`` must start with ``docs/`` and contain no ``..`` segments.
- Resolved absolute path must stay within ``/opt/projects/<slug>/``.

Edit semantics:
- ``PUT`` only accepts edits to existing files. Creating new spec
  documents is reserved for agents (Designer / Implementer / Auditor)
  — Director uses ``PUT`` for typo fixes / small corrections.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.core.security import require_ri_role
from backend.db.models.foundation import User
from backend.schemas.project_specs import (
    ProjectSpecContent,
    ProjectSpecListResponse,
    ProjectSpecUpdate,
)
from backend.services import project_specs as project_specs_service
from backend.services.project_specs import ProjectSpecsError

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Project Specs"])


@router.get("/list", response_model=ProjectSpecListResponse)
def list_project_specs(
    _user: User = Depends(require_ri_role),
) -> ProjectSpecListResponse:
    """List every ``.md`` file under ``/opt/projects/*/docs/``.

    Returns a flat list sorted by ``relative_path``. The frontend wraps
    this into a hierarchical tree via :file:`src/lib/kbTreeBuilder.ts`.
    """
    docs = project_specs_service.list_all_specs()
    return ProjectSpecListResponse(documents=docs, count=len(docs))


@router.get("/content", response_model=ProjectSpecContent)
def get_project_spec_content(
    slug: str = Query(..., description="Project slug, e.g. 'nex-inbox'"),
    path: str = Query(
        ...,
        description="Path within the project, e.g. 'docs/specs/customer-requirements.md'",
    ),
    _user: User = Depends(require_ri_role),
) -> ProjectSpecContent:
    """Read a single ``.md`` file under ``/opt/projects/<slug>/``."""
    try:
        content = project_specs_service.read_content(slug, path)
    except ProjectSpecsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return ProjectSpecContent(
        relative_path=f"{slug}/{path}",
        content=content,
    )


@router.put("/content", status_code=status.HTTP_200_OK)
def update_project_spec_content(
    payload: ProjectSpecUpdate,
    slug: str = Query(..., description="Project slug"),
    path: str = Query(..., description="Path within the project"),
    _user: User = Depends(require_ri_role),
) -> dict[str, str]:
    """Overwrite a single ``.md`` file. Director (``ri``) only.

    The file must already exist — this endpoint does **not** create new
    documents. New spec docs are produced by the agents (Designer /
    Implementer / Auditor) directly in the project repo.
    """
    try:
        project_specs_service.write_content(slug, path, payload.content)
    except ProjectSpecsError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return {"relative_path": f"{slug}/{path}", "status": "updated"}
