"""Invariants for the single-source-of-truth KB category list.

Per ICC Clean Code §2 (DRY), ``KB_CATEGORIES`` is the canonical list
consumed by the Pydantic ``Literal``, the SQLAlchemy CHECK constraint
and the ``GET /kb-documents/categories`` endpoint. These tests guard
against drift between the tuple itself and its derived artifacts.
"""

from __future__ import annotations

import re

from backend.constants.kb_categories import KB_CATEGORIES
from backend.db.models.kb import KbDocument
from backend.schemas.kb_document import KbDocumentCategory


def test_kb_categories_is_non_empty_unique_tuple():
    assert isinstance(KB_CATEGORIES, tuple)
    assert len(KB_CATEGORIES) > 0
    assert len(set(KB_CATEGORIES)) == len(KB_CATEGORIES), "duplicate categories"


def test_kb_categories_match_pydantic_literal():
    # ``Literal`` exposes its allowed values via ``__args__``.
    literal_values = set(KbDocumentCategory.__args__)  # type: ignore[attr-defined]
    assert literal_values == set(KB_CATEGORIES)


def test_kb_categories_match_db_check_constraint():
    constraints = [
        c for c in KbDocument.__table__.constraints
        if getattr(c, "name", None) == "ck_kb_documents_doc_category"
    ]
    assert len(constraints) == 1
    expr = str(constraints[0].sqltext)
    # Extract the quoted values from "doc_category IN ('a','b',...)".
    quoted = set(re.findall(r"'([^']+)'", expr))
    assert quoted == set(KB_CATEGORIES)
