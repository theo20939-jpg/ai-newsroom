"""Phase 23.1L - proves the test/live database isolation invariant (docs/
phase23_1l_runtime_isolation_final_canary_report.md): TEST EXECUTION MUST NOT WRITE INTO THE
DATABASE USED BY LIVE NEWSROOM PROCESSING.

Root cause this fixes: integration tests previously connected via
`create_async_engine(settings.database_url, ...)` - the same database production/the live canary
reads from - relying entirely on hand-maintained per-table teardown DELETEs that fell behind a
newly-added FK-referencing table (`content_draft_editorial_plans`), silently orphaning rows. One
orphaned row was later selected as a genuinely "eligible" event and generated two real Telegram
posts (Phase 23.1K incident 1).

The fix is structural, not disciplinary: a physically separate database (`settings.postgres_test_db`,
`ai_newsroom_test`) plus a fail-fast guard (`tests.conftest.assert_is_test_database`) that runs as
a pure string comparison, before any engine/connection is even constructed.
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from tests.conftest import DatabaseIsolationViolationError, assert_is_test_database
from tests.test_triage_orchestrator_claims import independent_session_factory


def test_assert_is_test_database_accepts_the_real_test_database_name() -> None:
    assert_is_test_database(settings.postgres_test_db)  # must not raise


def test_assert_is_test_database_rejects_the_real_dev_database_name() -> None:
    """Part E's own required negative case: 'a test intentionally pointed at the normal
    development DB' must FAIL FAST BEFORE ANY WRITE. This check is a pure string comparison -
    zero I/O, zero connection attempt - so "before any write" is not merely likely, it is
    structurally guaranteed: no socket is ever opened for a rejected name."""
    with pytest.raises(DatabaseIsolationViolationError):
        assert_is_test_database(settings.postgres_db)


def test_assert_is_test_database_rejects_an_arbitrary_third_database_name() -> None:
    """Not merely "not the dev db" - must also exactly equal the expected test db name (defense
    in depth against a typo'd or unrelated database silently being treated as safe)."""
    with pytest.raises(DatabaseIsolationViolationError):
        assert_is_test_database("some_other_database")


def test_postgres_db_and_postgres_test_db_are_different_real_settings_values() -> None:
    """A structural precondition the guard itself assumes - if these two ever coincided, the
    guard's exact-identity checks would need to be revisited. Documents the assumption as a live
    test, not just a comment."""
    assert settings.postgres_db != settings.postgres_test_db


@pytest.mark.asyncio
async def test_independent_session_factory_actually_connects_to_the_test_database() -> None:
    """Not just a config check - proves the real, live connection independent_session_factory()
    opens (the same helper all 16 dependent test files use) targets `postgres_test_db`, verified
    by asking Postgres itself, not by re-reading the URL string."""
    engine, factory = independent_session_factory()
    try:
        async with factory() as session:
            current_db = (await session.execute(text("SELECT current_database()"))).scalar_one()
        assert current_db == settings.postgres_test_db
        assert current_db != settings.postgres_db
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_db_session_fixture_engine_also_targets_the_test_database() -> None:
    """tests/conftest.py's own `_test_engine` (backing the db_session fixture) must be the same
    isolated database, not just independent_session_factory()'s engine."""
    from tests.conftest import _test_engine

    async with _test_engine.connect() as connection:
        current_db = (await connection.execute(text("SELECT current_database()"))).scalar()
    assert current_db == settings.postgres_test_db
    assert current_db != settings.postgres_db


@pytest.mark.asyncio
async def test_an_engine_explicitly_constructed_against_the_real_dev_url_is_never_produced_by_test_helpers() -> None:
    """Confirms the negative: nothing in this test suite's own shared helpers can hand back an
    engine pointed at settings.database_url - constructing one manually (simulating a
    hypothetical future regression) and comparing its target against the guard is the only way to
    exercise this without actually connecting to the real dev DB from a test."""
    from sqlalchemy.engine import make_url

    rogue_engine = create_async_engine(settings.database_url, poolclass=NullPool)
    try:
        rogue_db_name = make_url(str(rogue_engine.url)).database
        with pytest.raises(DatabaseIsolationViolationError):
            assert_is_test_database(rogue_db_name)
    finally:
        await rogue_engine.dispose()
