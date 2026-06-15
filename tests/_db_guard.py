"""Production-DB isolation guard helpers (CR-NS-076).

Pure, unit-testable helpers backing the root ``conftest.py`` guard that
guarantees the test suite can NEVER write to the cockpit/PROD database.

Background: ``backend.db.session.SessionLocal`` is bound to the production
``settings.database_url`` at import time. A test path that calls the shared
``SessionLocal()`` and commits *without* the per-test monkeypatch writes
straight into the live cockpit DB, outside the SAVEPOINT rollback. That is
how a full pipeline tree leaked into ``nexstudio`` on 2026-06-08.
"""


def database_name(url: str) -> str:
    """Return the database NAME segment of a SQLAlchemy/DB URL.

    Strips the driver, credentials, host:port and any query string, leaving
    just the final path segment (the database name).

    >>> database_name("postgresql+pg8000://u:p@host:5432/nexstudio?sslmode=require")
    'nexstudio'
    """
    return url.rsplit("/", 1)[-1].split("?")[0]


def assert_test_db_distinct(production_url: str, test_url: str) -> None:
    """Abort the run if the test DB is not a DISTINCT database from PROD.

    Compares the database NAME segment of each URL and raises ``RuntimeError``
    when they match — catching a mis-set ``TEST_DATABASE_URL`` that would make
    tests (and the ``test_engine`` ``create_all``/``drop_all``) operate on the
    cockpit/PROD database.
    """
    prod_name = database_name(production_url)
    test_name = database_name(test_url)
    if prod_name == test_name:
        raise RuntimeError(
            "Test isolation guard (CR-NS-076): the test database "
            f"({test_name!r}) must be a DISTINCT database from the production "
            f"database ({prod_name!r}). Refusing to run — tests would read/write "
            "and drop_all against the cockpit/PROD DB. Point TEST_DATABASE_URL "
            "at a separate database (default: nexstudio_test)."
        )
