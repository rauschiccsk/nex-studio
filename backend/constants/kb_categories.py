"""Single source of truth for ``kb_documents.doc_category`` values.

This tuple is the canonical list of allowed knowledge-base document
categories. It is consumed by:

* :mod:`backend.schemas.kb_document` — to build the Pydantic ``Literal``
  type used in request/response validation.
* :mod:`backend.db.models.kb` — to build the
  ``ck_kb_documents_doc_category`` CHECK constraint string.
* :mod:`backend.api.routes.kb_documents` — for the
  ``GET /categories`` endpoint that the frontend consumes.

Per ICC Clean Code §2 (DRY): there is exactly one place where this
list lives. Every consumer imports from here.

The membership of this tuple is enforced at the DB layer by the CHECK
constraint generated from it. Adding a new category is a single-line
change here plus a migration that ALTERs the constraint to include the
new value.
"""

from __future__ import annotations

KB_CATEGORIES: tuple[str, ...] = (
    # Original — NEX Studio pipeline / ICC-wide reference docs
    "standards",
    "decisions",
    "lessons",
    "patterns",
    "design",
    "behavior",
    "session",
    # Added in migration 037 — filesystem-derived categories from kb_sync
    "icc",
    "infrastructure",
    "customers",
    "shuhari",
    "templates",
    "service-manuals",
    "deployment",
    "quarantine",
    "credentials",
    "project-status",
    "project-history",
    "project-architect",
    "project-other",
)
