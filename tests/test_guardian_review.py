"""Tests for the GuardianReview model."""

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.delegations import Delegation
from backend.db.models.guardian import GuardianReview


def _make_delegation(db_session, **overrides) -> Delegation:
    defaults = {
        "prompt": "Implement feature X",
    }
    defaults.update(overrides)
    delegation = Delegation(**defaults)
    db_session.add(delegation)
    db_session.flush()
    return delegation


def _make_review(
    db_session,
    *,
    delegation: Delegation | None = None,
    **overrides,
) -> GuardianReview:
    if delegation is None:
        delegation = _make_delegation(db_session)
    defaults = {
        "delegation_id": delegation.id,
        "layer": "layer1",
        "risk_level": "low",
    }
    defaults.update(overrides)
    return GuardianReview(**defaults)


class TestGuardianReviewModel:
    """Unit tests for the GuardianReview ORM model."""

    def test_create_review(self, db_session):
        """Can insert a guardian review with minimal required fields."""
        review = _make_review(db_session)
        db_session.add(review)
        db_session.flush()

        assert review.id is not None
        assert review.created_at is not None
        # Reviews are immutable — no updated_at column per DESIGN.md §1.21
        assert not hasattr(review, "updated_at") or getattr(review, "updated_at", None) is None

    def test_findings_default_empty_list(self, db_session):
        """findings defaults to an empty JSONB array via server_default."""
        review = _make_review(db_session)
        db_session.add(review)
        db_session.flush()

        db_session.expire(review)
        assert review.findings == []

    def test_passed_default_false(self, db_session):
        """passed defaults to FALSE via server_default."""
        review = _make_review(db_session)
        db_session.add(review)
        db_session.flush()

        db_session.expire(review)
        assert review.passed is False

    def test_findings_stored_as_jsonb(self, db_session):
        """findings JSONB is persisted correctly."""
        findings = [
            {
                "severity": "MUST_FIX",
                "rule": "no-console-log",
                "file_path": "src/app.ts",
                "line_range": "12-15",
                "description": "console.log in production code",
                "suggestion": "Use logger instead",
                "confidence": 0.95,
            },
            {
                "severity": "WARNING",
                "rule": "unused-import",
                "file_path": "src/utils.ts",
                "line_range": None,
                "description": "Unused import",
                "suggestion": None,
                "confidence": 0.8,
            },
        ]
        review = _make_review(db_session, findings=findings)
        db_session.add(review)
        db_session.flush()

        db_session.expire(review)
        assert len(review.findings) == 2
        assert review.findings[0]["severity"] == "MUST_FIX"
        assert review.findings[0]["confidence"] == 0.95
        assert review.findings[1]["line_range"] is None

    def test_duration_ms_nullable(self, db_session):
        """duration_ms can be NULL."""
        review = _make_review(db_session)
        db_session.add(review)
        db_session.flush()
        assert review.duration_ms is None

    def test_duration_ms_stored(self, db_session):
        """duration_ms is persisted when provided."""
        review = _make_review(db_session, duration_ms=1234)
        db_session.add(review)
        db_session.flush()
        assert review.duration_ms == 1234

    def test_passed_true(self, db_session):
        """passed can be set to TRUE explicitly."""
        review = _make_review(db_session, passed=True)
        db_session.add(review)
        db_session.flush()
        assert review.passed is True

    def test_delegation_id_not_nullable(self, db_session):
        """delegation_id=NULL must be rejected."""
        review = _make_review(db_session, delegation_id=None)
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_layer_not_nullable(self, db_session):
        """layer=NULL must be rejected."""
        review = _make_review(db_session, layer=None)
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_risk_level_not_nullable(self, db_session):
        """risk_level=NULL must be rejected."""
        review = _make_review(db_session, risk_level=None)
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("layer", ["layer1", "layer2", "layer3"])
    def test_valid_layers(self, db_session, layer):
        """All valid layer values must be accepted."""
        review = _make_review(db_session, layer=layer)
        db_session.add(review)
        db_session.flush()
        assert review.layer == layer

    def test_layer_check_constraint(self, db_session):
        """Invalid layer values must be rejected."""
        review = _make_review(db_session, layer="layer4")
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("risk_level", ["low", "medium", "high", "critical"])
    def test_valid_risk_levels(self, db_session, risk_level):
        """All valid risk_level values must be accepted."""
        review = _make_review(db_session, risk_level=risk_level)
        db_session.add(review)
        db_session.flush()
        assert review.risk_level == risk_level

    def test_risk_level_check_constraint(self, db_session):
        """Invalid risk_level values must be rejected."""
        review = _make_review(db_session, risk_level="extreme")
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_delegation_id_fk_invalid(self, db_session):
        """delegation_id must reference an existing delegation."""
        review = _make_review(db_session, delegation_id=uuid.uuid4())
        db_session.add(review)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_delegation_cascade_delete(self, db_session):
        """Deleting a delegation cascades to its guardian reviews."""
        delegation = _make_delegation(db_session)
        review = _make_review(db_session, delegation=delegation)
        db_session.add(review)
        db_session.flush()
        review_id = review.id

        db_session.execute(
            text("DELETE FROM delegations WHERE id = :id"),
            {"id": str(delegation.id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT id FROM guardian_reviews WHERE id = :id"),
            {"id": str(review_id)},
        )
        assert result.scalar() is None

    def test_multiple_reviews_per_delegation(self, db_session):
        """A delegation can have multiple guardian reviews (Layer 1/2/3)."""
        delegation = _make_delegation(db_session)
        for layer in ["layer1", "layer2", "layer3"]:
            review = _make_review(db_session, delegation=delegation, layer=layer)
            db_session.add(review)
        db_session.flush()

        result = db_session.execute(
            text("SELECT COUNT(*) FROM guardian_reviews WHERE delegation_id = :did"),
            {"did": str(delegation.id)},
        )
        assert result.scalar() == 3
