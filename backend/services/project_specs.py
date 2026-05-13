"""Service layer for the per-project specs browser (``/api/v1/project-specs``).

Reads ``.md`` files under ``/opt/projects/<slug>/docs/`` for any project
that physically exists on disk. The router layer applies RBAC (ri only
for the v1 cut) and path traversal validation before invoking this
service.

Single source of truth — these files are produced and edited by the
three agents (Designer / Implementer / Auditor) directly in the
project repo. The UI exposed by this service is read-mostly with a
Director (ri) override for typo fixes.

Design notes:
- Scans ``/opt/projects/<slug>/docs/`` recursively for ``*.md`` files.
- Hidden directories (``.git``, ``__pycache__``, ``node_modules``, ...)
  are skipped — mirrors the KB scanner pattern.
- All returned paths are ``<slug>/docs/...`` (relative to
  ``/opt/projects``), which is the format KbTree expects for the
  unified hierarchical view.
"""

from __future__ import annotations

import re
from pathlib import Path

from backend.schemas.project_specs import ProjectSpecDoc

PROJECTS_ROOT = Path("/opt/projects")

#: Directories skipped during the recursive scan — same set as
#: :data:`backend.services.knowledge_manager._HIDDEN_DIRS`.
_HIDDEN_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".github",
        ".venv",
        "__pycache__",
        "node_modules",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
        ".idea",
        ".vscode",
    }
)

#: Slug regex — same kebab-case rule as ``init.sh`` validation.
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]*[a-z0-9]$|^[a-z]$")


class ProjectSpecsError(ValueError):
    """Raised on invalid slug or path traversal attempt."""


def _validate_slug(slug: str) -> None:
    if not _SLUG_RE.match(slug):
        raise ProjectSpecsError(f"Invalid slug: {slug!r}")


def _project_docs_dir(slug: str) -> Path:
    """Resolve and return the docs directory for a given project slug.

    Returns the absolute path even if the directory does not exist
    (caller decides how to handle missing).
    """
    _validate_slug(slug)
    return PROJECTS_ROOT / slug / "docs"


def list_all_specs() -> list[ProjectSpecDoc]:
    """Return all ``.md`` files under every ``/opt/projects/*/docs/``.

    Top-level entries in :data:`PROJECTS_ROOT` are filtered to those
    that (a) match the slug regex and (b) contain a ``docs/`` subdir.
    Hidden directories are skipped during the recursive scan.

    Order: deterministic — sorted by ``relative_path`` ascending so the
    UI gets stable layout across reloads.
    """
    if not PROJECTS_ROOT.is_dir():
        return []

    out: list[ProjectSpecDoc] = []
    for project_dir in sorted(PROJECTS_ROOT.iterdir()):
        if not project_dir.is_dir():
            continue
        slug = project_dir.name
        if not _SLUG_RE.match(slug):
            continue
        docs_dir = project_dir / "docs"
        if not docs_dir.is_dir():
            continue
        out.extend(_scan_docs(slug, docs_dir))

    out.sort(key=lambda d: d.relative_path)
    return out


def _scan_docs(slug: str, docs_dir: Path) -> list[ProjectSpecDoc]:
    """Recursive scan of ``docs_dir`` for ``.md`` files."""
    out: list[ProjectSpecDoc] = []
    for path in docs_dir.rglob("*.md"):
        # Skip files under hidden directories.
        if any(part in _HIDDEN_DIRS for part in path.parts):
            continue
        if not path.is_file():
            continue
        rel_to_root = path.relative_to(PROJECTS_ROOT)
        parent_rel = rel_to_root.parent.as_posix()
        out.append(
            ProjectSpecDoc(
                relative_path=rel_to_root.as_posix(),
                filename=path.name,
                category=parent_rel,
                size_bytes=path.stat().st_size,
            )
        )
    return out


def read_content(slug: str, path_within_project: str) -> str:
    """Read a single ``.md`` file under ``/opt/projects/<slug>/``.

    ``path_within_project`` is the part after the slug, e.g.
    ``docs/specs/customer-requirements.md``. Must start with ``docs/``
    and contain no ``..`` segments.

    Raises:
        ProjectSpecsError: invalid slug, path traversal attempt, path
            outside ``docs/``, or file not found.
    """
    abs_path = _resolve_doc_path(slug, path_within_project)
    if not abs_path.is_file():
        raise ProjectSpecsError(
            f"File not found: {slug}/{path_within_project}",
        )
    return abs_path.read_text(encoding="utf-8")


def write_content(slug: str, path_within_project: str, content: str) -> None:
    """Overwrite a single ``.md`` file. Used by the Director (ri) edit flow.

    Same path validation as :func:`read_content`. The file must already
    exist — this endpoint is **edit only**, not create. New documents
    are produced by the agents, not by the UI.

    Raises:
        ProjectSpecsError: invalid slug / path or file not found.
    """
    abs_path = _resolve_doc_path(slug, path_within_project)
    if not abs_path.is_file():
        raise ProjectSpecsError(
            f"File not found (cannot create via UI): {slug}/{path_within_project}",
        )
    abs_path.write_text(content, encoding="utf-8")


def _resolve_doc_path(slug: str, path_within_project: str) -> Path:
    """Validate + resolve. Common helper for read + write paths."""
    _validate_slug(slug)

    if ".." in path_within_project.split("/"):
        raise ProjectSpecsError("Path traversal not allowed")
    if not path_within_project.startswith("docs/"):
        raise ProjectSpecsError("Path must be inside docs/")
    if not path_within_project.endswith(".md"):
        raise ProjectSpecsError("Only .md files supported")

    project_root = PROJECTS_ROOT / slug
    abs_path = (project_root / path_within_project).resolve()

    # Defense in depth — even though we banned ``..`` above, ensure the
    # resolved path stays within the project root.
    try:
        abs_path.relative_to(project_root.resolve())
    except ValueError as exc:
        raise ProjectSpecsError("Resolved path escapes project root") from exc

    return abs_path
