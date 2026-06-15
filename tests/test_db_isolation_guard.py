"""Tests for the CR-NS-076 production-DB isolation guard.

These verify that during a test run the shared ``SessionLocal`` / ``engine``
are bound to the TEST database (never the cockpit/PROD DB), and that the
distinctness guard aborts when the two are the same database.
"""

import pytest

from backend.config.settings import settings
from backend.db import session as db_session_module
from tests._db_guard import assert_test_db_distinct, database_name


def test_sessionlocal_binds_to_test_db_not_prod():
    """The live, shared ``SessionLocal()`` must bind to the TEST database.

    This is the core invariant: even without a per-test monkeypatch, opening
    the module-global session must NOT reach the production (cockpit) database.
    """
    live = db_session_module.SessionLocal()
    try:
        bound_db = live.get_bind().url.database
    finally:
        live.close()

    prod_db = database_name(settings.database_url)
    assert bound_db != prod_db, f"SessionLocal is bound to the production DB {bound_db!r} during tests"


def test_engine_module_attr_points_at_test_db():
    """The module-level ``engine`` is rebound to the test DB during the session."""
    assert db_session_module.engine.url.database != database_name(settings.database_url)


def test_database_name_extraction():
    """``database_name`` strips driver/credentials/host/query, leaving the DB name."""
    assert database_name("postgresql+pg8000://u:p@h:5432/nexstudio") == "nexstudio"
    assert database_name("postgresql://u:p@h/nexstudio_test?sslmode=require") == "nexstudio_test"


def test_assert_test_db_distinct_aborts_when_identical():
    """The guard raises when the test DB equals the production DB."""
    same = "postgresql+pg8000://u:p@h:5432/nexstudio"
    with pytest.raises(RuntimeError, match="DISTINCT"):
        assert_test_db_distinct(same, same)


def test_assert_test_db_distinct_passes_when_different():
    """No exception when the test DB is a distinct database from production."""
    assert (
        assert_test_db_distinct(
            "postgresql+pg8000://u:p@h/nexstudio",
            "postgresql+pg8000://u:p@h/nexstudio_test",
        )
        is None
    )
