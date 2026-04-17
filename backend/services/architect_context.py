"""Context assembly service for the Architect AI.

Builds a single context string from Foundation and module-level design
documents plus the project module registry.  This context is passed as
the system prompt (or prepended to the user prompt) when invoking the
Claude subprocess for Architect conversations.

Design references:
    * DESIGN.md D-04 — per-module DESIGN.md (not one mega-document)
    * DESIGN.md D-11 — Claude MAX via CLI Subprocess
    * DESIGN.md §3.2 — ArchitectChat, ModuleContextBadge
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import and_
from sqlalchemy.orm import Session

from backend.db.models.projects import ProjectModule
from backend.db.models.specifications import DesignDocument

logger = logging.getLogger(__name__)


def _format_document(label: str, content: str) -> str:
    """Wrap a document in a labelled section."""
    return f"## {label}\n\n{content}"


def _format_module_registry(modules: list[ProjectModule]) -> str:
    """Format the module registry as a Markdown table."""
    if not modules:
        return "## Module Registry\n\nNo modules registered."

    lines: list[str] = [
        "## Module Registry",
        "",
        "| Code | Name | Category | Status |",
        "|------|------|----------|--------|",
    ]
    for m in modules:
        lines.append(f"| {m.code} | {m.name} | {m.category} | {m.status} |")
    return "\n".join(lines)


def build_architect_context(
    db: Session,
    project_id: UUID,
    module_id: UUID | None = None,
) -> str:
    """Assemble the full context string for an Architect session.

    Loads the following in order:
    1. Foundation DESIGN.md (``doc_type='design'``, ``module_id IS NULL``)
    2. Foundation BEHAVIOR.md (``doc_type='behavior'``, ``module_id IS NULL``)
    3. Module DESIGN.md + BEHAVIOR.md (if *module_id* is provided)
    4. Module registry — all modules with their status

    Parameters
    ----------
    db:
        Active SQLAlchemy session (sync, pg8000 driver).
    project_id:
        UUID of the project whose context to assemble.
    module_id:
        Optional UUID of the target module.  When ``None``, only
        foundation-level documents and the module registry are included.

    Returns
    -------
    str
        Concatenated Markdown context ready for the Claude prompt.

    Raises
    ------
    ValueError
        If the project has no foundation DESIGN.md at all (the minimum
        required document for Architect to operate).
    """
    sections: list[str] = []

    # ------------------------------------------------------------------
    # 1. Foundation DESIGN.md
    # ------------------------------------------------------------------
    foundation_design: DesignDocument | None = (
        db.query(DesignDocument)
        .filter(
            and_(
                DesignDocument.project_id == project_id,
                DesignDocument.module_id.is_(None),
                DesignDocument.doc_type == "design",
            )
        )
        .order_by(DesignDocument.version.desc())
        .first()
    )

    if foundation_design is None:
        raise ValueError(f"Project {project_id} has no foundation DESIGN.md. Cannot assemble Architect context.")

    sections.append(_format_document("Foundation DESIGN.md", foundation_design.content))

    # ------------------------------------------------------------------
    # 2. Foundation BEHAVIOR.md
    # ------------------------------------------------------------------
    foundation_behavior: DesignDocument | None = (
        db.query(DesignDocument)
        .filter(
            and_(
                DesignDocument.project_id == project_id,
                DesignDocument.module_id.is_(None),
                DesignDocument.doc_type == "behavior",
            )
        )
        .order_by(DesignDocument.version.desc())
        .first()
    )

    if foundation_behavior is not None:
        sections.append(_format_document("Foundation BEHAVIOR.md", foundation_behavior.content))

    # ------------------------------------------------------------------
    # 3. Module-level documents (only when module_id is provided)
    # ------------------------------------------------------------------
    if module_id is not None:
        module_design: DesignDocument | None = (
            db.query(DesignDocument)
            .filter(
                and_(
                    DesignDocument.project_id == project_id,
                    DesignDocument.module_id == module_id,
                    DesignDocument.doc_type == "design",
                )
            )
            .order_by(DesignDocument.version.desc())
            .first()
        )
        if module_design is not None:
            sections.append(_format_document("Module DESIGN.md", module_design.content))

        module_behavior: DesignDocument | None = (
            db.query(DesignDocument)
            .filter(
                and_(
                    DesignDocument.project_id == project_id,
                    DesignDocument.module_id == module_id,
                    DesignDocument.doc_type == "behavior",
                )
            )
            .order_by(DesignDocument.version.desc())
            .first()
        )
        if module_behavior is not None:
            sections.append(_format_document("Module BEHAVIOR.md", module_behavior.content))

    # ------------------------------------------------------------------
    # 4. Module registry
    # ------------------------------------------------------------------
    modules: list[ProjectModule] = (
        db.query(ProjectModule).filter(ProjectModule.project_id == project_id).order_by(ProjectModule.code).all()
    )

    sections.append(_format_module_registry(modules))

    return "\n\n---\n\n".join(sections)
