"""Tests for the ReportConfig model."""

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError

from backend.db.models.foundation import User
from backend.db.models.projects import Project
from backend.db.models.reports import ReportConfig


def _make_user(db_session, **overrides) -> User:
    defaults = {
        "username": f"user_{uuid.uuid4().hex[:8]}",
        "email": f"{uuid.uuid4().hex[:8]}@example.com",
        "password_hash": "hashed_password_placeholder",
        "role": "ri",
    }
    defaults.update(overrides)
    user = User(**defaults)
    db_session.add(user)
    db_session.flush()
    return user


def _make_project(db_session, **overrides) -> Project:
    user = _make_user(db_session)
    defaults = {
        "name": f"Project {uuid.uuid4().hex[:8]}",
        "slug": f"project-{uuid.uuid4().hex[:8]}",
        "category": "multimodule",
        "description": "Test project",
        "created_by": user.id,
    }
    defaults.update(overrides)
    project = Project(**defaults)
    db_session.add(project)
    db_session.flush()
    return project


def _make_report_config(db_session, *, project=None, **overrides) -> ReportConfig:
    if project is None and "project_id" not in overrides:
        project = _make_project(db_session)
    defaults = {
        "project_id": project.id if project else None,
    }
    defaults.update(overrides)
    cfg = ReportConfig(**defaults)
    db_session.add(cfg)
    db_session.flush()
    return cfg


class TestReportConfigModel:
    """Unit tests for ReportConfig ORM model."""

    def test_create_report_config(self, db_session):
        cfg = _make_report_config(db_session)
        assert cfg.id is not None
        assert cfg.created_at is not None
        assert cfg.updated_at is not None

    def test_senior_rate_default(self, db_session):
        cfg = _make_report_config(db_session)
        db_session.expire(cfg)
        assert cfg.senior_hourly_rate_eur == Decimal("75.0000")

    def test_junior_rate_default(self, db_session):
        cfg = _make_report_config(db_session)
        db_session.expire(cfg)
        assert cfg.junior_hourly_rate_eur == Decimal("35.0000")

    def test_rates_custom_values(self, db_session):
        project = _make_project(db_session)
        cfg = _make_report_config(
            db_session,
            project=project,
            senior_hourly_rate_eur=Decimal("100.0000"),
            junior_hourly_rate_eur=Decimal("45.5000"),
        )
        db_session.expire(cfg)
        assert cfg.senior_hourly_rate_eur == Decimal("100.0000")
        assert cfg.junior_hourly_rate_eur == Decimal("45.5000")

    def test_project_id_not_nullable(self, db_session):
        cfg = ReportConfig(project_id=None)
        db_session.add(cfg)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_unique(self, db_session):
        project = _make_project(db_session)
        _make_report_config(db_session, project=project)

        dup = ReportConfig(project_id=project.id)
        db_session.add(dup)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_project_id_fk_invalid(self, db_session):
        cfg = ReportConfig(project_id=uuid.uuid4())
        db_session.add(cfg)
        with pytest.raises((IntegrityError, ProgrammingError)):
            db_session.flush()
        db_session.rollback()

    def test_cascade_delete_project(self, db_session):
        project = _make_project(db_session)
        _make_report_config(db_session, project=project)
        project_id = project.id

        db_session.execute(
            text("DELETE FROM projects WHERE id = :id"),
            {"id": str(project_id)},
        )
        db_session.flush()

        result = db_session.execute(
            text("SELECT count(*) FROM report_configs WHERE project_id = :id"),
            {"id": str(project_id)},
        )
        assert result.scalar() == 0
