"""Tests for the GuardianPrecedent model."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.guardian import GuardianPrecedent


class TestGuardianPrecedentModel:
    """Unit tests for GuardianPrecedent ORM model."""

    def test_create_precedent(self, db_session):
        """Can insert a valid guardian precedent."""
        precedent = GuardianPrecedent(
            pattern_hash="a" * 64,
            pattern_description="No console.log in production",
            verdict="allow",
        )
        db_session.add(precedent)
        db_session.flush()

        assert precedent.id is not None
        assert precedent.created_at is not None
        # Precedents are immutable — no updated_at column per DESIGN.md §1.22
        assert precedent.created_by is None

    def test_unique_pattern_hash(self, db_session):
        """Duplicate pattern_hash must be rejected."""
        p1 = GuardianPrecedent(
            pattern_hash="b" * 64,
            pattern_description="desc1",
            verdict="block",
        )
        db_session.add(p1)
        db_session.flush()

        p2 = GuardianPrecedent(
            pattern_hash="b" * 64,
            pattern_description="desc2",
            verdict="notice",
        )
        db_session.add(p2)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_verdict_check_constraint(self, db_session):
        """Invalid verdict value must be rejected by CHECK constraint."""
        p = GuardianPrecedent(
            pattern_hash="c" * 64,
            pattern_description="desc",
            verdict="invalid",
        )
        db_session.add(p)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    @pytest.mark.parametrize("verdict", ["allow", "notice", "block"])
    def test_all_valid_verdicts(self, db_session, verdict):
        """All three verdict values must be accepted."""
        p = GuardianPrecedent(
            pattern_hash=uuid.uuid4().hex + uuid.uuid4().hex,
            pattern_description=f"test {verdict}",
            verdict=verdict,
        )
        db_session.add(p)
        db_session.flush()
        assert p.verdict == verdict

    def test_pattern_hash_not_nullable(self, db_session):
        """pattern_hash=NULL must be rejected."""
        p = GuardianPrecedent(
            pattern_hash=None,
            pattern_description="desc",
            verdict="allow",
        )
        db_session.add(p)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_pattern_description_not_nullable(self, db_session):
        """pattern_description=NULL must be rejected."""
        p = GuardianPrecedent(
            pattern_hash="d" * 64,
            pattern_description=None,
            verdict="allow",
        )
        db_session.add(p)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_verdict_not_nullable(self, db_session):
        """verdict=NULL must be rejected."""
        p = GuardianPrecedent(
            pattern_hash="e" * 64,
            pattern_description="desc",
            verdict=None,
        )
        db_session.add(p)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()
