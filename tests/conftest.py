"""Shared pytest fixtures.

Phase 5 introduces this project's first tests that touch a real PostgreSQL
connection (see docs/phase5_workflow_engine_planning.md, section 12/open
questions). Each db_session test wraps its work in an outer connection-level
transaction that is rolled back at teardown, using SQLAlchemy's
create_savepoint join mode so that inner `session.commit()` calls inside the
code under test only commit a SAVEPOINT - nothing a test does is ever
actually persisted, regardless of how many times the code under test calls
commit().

Uses a dedicated NullPool engine rather than database.session.engine: pytest
-asyncio gives each test function its own event loop by default, and asyncpg
connections cannot be reused across event loops. database.session.engine is
a module-level singleton with a pooled connection, so reusing it here would
intermittently hand a test a connection opened on a different test's loop
(sqlalchemy.exc.MissingGreenlet). NullPool opens a fresh physical connection
per checkout and never pools it, sidestepping that entirely without touching
the production engine.

Phase 18.9-R: this file also installs three independent, suite-wide barriers
against a real paid provider call ever being reachable from a pytest process
(docs/phase18_9r_test_provider_path_audit.md, docs/phase18_9_incident_snapshot.md -
a real, confirmed incident happened without them). All three are applied at module
import time - the earliest point pytest reaches, before any test or fixture runs, and
(critically for Barrier 2) before core.config.get_settings()'s own @lru_cache
construction can read the real .env. None of them depend on any individual test
remembering to opt in.
"""
import os

# ---------------------------------------------------------------------------
# Phase 18.9-R Barrier 2 (API credential isolation) - MUST be the first executable lines in
# this file, before ANY import (including stdlib-adjacent ones below) that could transitively
# import core.config and trigger its @lru_cache'd get_settings() singleton construction, which
# reads the real .env file. pydantic-settings' own precedence is constructor kwargs > os.environ
# > .env file, so setting this here guarantees the real OPENAI_API_KEY is never read into this
# process's Settings singleton at all - not merely overwritten after construction (an
# importlib.reload-based "fix after the fact" approach was tried and rejected during Phase 18.8's
# own test-authoring: it corrupted other modules' already-bound references to the settings
# singleton). This does not touch the real .env file on disk, and has no effect on already-running
# Docker containers (each reads its own env_file: .env once, at container start, entirely outside
# this process).
# ---------------------------------------------------------------------------
TEST_OPENAI_API_KEY_SENTINEL = "test-disabled-no-real-provider-access"
os.environ["OPENAI_API_KEY"] = TEST_OPENAI_API_KEY_SENTINEL

import uuid  # noqa: E402
from collections.abc import AsyncGenerator  # noqa: E402

import httpx  # noqa: E402
import pytest_asyncio  # noqa: E402
from redis.asyncio import Redis  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine  # noqa: E402
from sqlalchemy.pool import NullPool  # noqa: E402

from core.config import settings  # noqa: E402
from database.models.news_event import EventCategory, NewsEvent  # noqa: E402
from database.models.news_source import NewsSource, SourceType  # noqa: E402
from integrations.llm_gateway.providers.openai_adapter import OpenAIAdapter  # noqa: E402

_test_engine = create_async_engine(settings.test_database_url, poolclass=NullPool)

# Phase 18.9-R M5 (Redis isolation): a dedicated Redis logical database index for the entire test
# suite, structurally separate from production's index 0 (settings.redis_db) - real keyspace
# isolation via Redis's own native multi-database feature, not merely a per-test naming
# convention (the convention alone is exactly what tests/test_api_cost_optimization_checklist.py
# violated - docs/phase18_9r_test_provider_path_audit.md sec4). No test in this suite may still
# reach production's real index 0 through this fixture.
TEST_REDIS_DB_INDEX = 15


# ---------------------------------------------------------------------------
# Phase 18.9-R Barrier 1 (provider construction poison pill) - OpenAIAdapter.__init__ constructs
# a REAL, functional AsyncOpenAI client whenever client=None (its own default, `integrations/
# llm_gateway/providers/openai_adapter.py`). Patched once, here, for the entire pytest session,
# regardless of which test/fixture/module reaches it - never dependent on an individual test
# injecting a poison-pill registry itself (that discipline already failed once - the original
# Phase 18.9 incident). Tests that inject their own fake/mock client (client=...) are entirely
# unaffected - only the client=None (real construction) branch is intercepted.
# ---------------------------------------------------------------------------


class RealProviderConstructionBlockedError(RuntimeError):
    """Raised instead of constructing a real AsyncOpenAI client during pytest (Phase 18.9-R
    Barrier 1). If you see this, inject a fake/mock client explicitly, or use
    FakeProviderAdapter/FakeLLMGateway (tests/fakes/) instead of the real provider stack."""


_ORIGINAL_OPENAI_ADAPTER_INIT = OpenAIAdapter.__init__

# Pre-existing, already-established SAFE_FAKE convention across this codebase's own tests
# (docs/phase18_9r_test_provider_path_audit.md sec1): several already-audited, already-safe tests
# (tests/test_boot_assembly.py, tests/test_capability_boot_wiring_e2e.py, tests/
# test_phase8/9_cross_cutting_regression.py, tests/test_openai_adapter.py) deliberately construct
# a REAL (but never-called - `.generate()` is never invoked) AsyncOpenAI client with an
# obviously-fake key, specifically to test the boot/construction sequence itself. Blocking those
# unconditionally, on first attempt, broke 6 pre-existing tests - fixed by allowing construction
# through when the key is recognizably one of this codebase's own established fake-key patterns
# (contains "test" or "fake") rather than blocking every client=None construction unconditionally.
# A real OpenAI key (`sk-proj-...`/`sk-...`, real .env value, or Barrier 2's own sentinel string
# swapped in for it) does not match this pattern and is still blocked. This does not weaken the
# barrier's real guarantee - Barrier 2 already ensures the real settings singleton's own key is
# never anything but the sentinel (which itself contains "test" and is therefore also allowed
# through here, safely, since it is not a real key either).
_KNOWN_SAFE_TEST_KEY_MARKERS = ("test", "fake")


def _looks_like_a_known_safe_test_key(credential: object) -> bool:
    """Deliberately excludes an exact match against `TEST_OPENAI_API_KEY_SENTINEL` itself -
    that value means "this credential came from the real `core.config.settings` singleton"
    (Barrier 2), which is exactly the original incident's own shape and must always still be
    blocked here, never treated as a known-safe pattern merely because it happens to contain
    "test" too."""
    api_key = getattr(credential, "api_key", None)
    if api_key is None:
        return False
    value = api_key.get_secret_value()
    if value == TEST_OPENAI_API_KEY_SENTINEL:
        return False
    return any(marker in value.lower() for marker in _KNOWN_SAFE_TEST_KEY_MARKERS)


def _guarded_openai_adapter_init(self: OpenAIAdapter, credential, *, client: object = None) -> None:
    if client is None and not _looks_like_a_known_safe_test_key(credential):
        raise RealProviderConstructionBlockedError(
            f"Blocked: OpenAIAdapter attempted to construct a REAL AsyncOpenAI client "
            f"(base_url={credential.base_url!r}) during pytest, with a credential that does not "
            "match any known-safe test-key pattern. Inject a fake/mock client explicitly, or use "
            "FakeProviderAdapter/FakeLLMGateway instead. "
            "(Phase 18.9-R Barrier 1 - docs/phase18_9r_test_provider_path_audit.md)"
        )
    _ORIGINAL_OPENAI_ADAPTER_INIT(self, credential, client=client)  # type: ignore[arg-type]


OpenAIAdapter.__init__ = _guarded_openai_adapter_init  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Phase 18.9-R Barrier 3 (network egress denial, below the application/provider layer) - even if
# Barriers 1/2 were somehow both bypassed, no httpx-based HTTP request to a real external host can
# leave this process during pytest. Requests already routed through httpx.MockTransport (the
# established pattern tests/test_{arxiv,github,hacker_news,rss}_source.py already use) are always
# allowed through unconditionally - checked by the client's configured transport TYPE, not by
# hostname, so a fake target URL like "https://example.com/feed.rss" (a real-looking host, but a
# fake transport) is never blocked by mistake (docs/phase18_9r_test_provider_path_audit.md sec7).
# Local Postgres/Redis access is unaffected - neither uses httpx (asyncpg/redis-py speak their own
# TCP protocols directly, never routed through httpx.AsyncClient/Client at all).
# ---------------------------------------------------------------------------


class NetworkEgressBlockedTestError(RuntimeError):
    """Raised instead of letting an httpx request leave this process during pytest (Phase 18.9-R
    Barrier 3). Use httpx.MockTransport instead of a real request."""


_ALLOWED_TEST_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

_ORIGINAL_ASYNC_CLIENT_SEND = httpx.AsyncClient.send
_ORIGINAL_CLIENT_SEND = httpx.Client.send


def _is_mock_transport(client: httpx.AsyncClient | httpx.Client) -> bool:
    return isinstance(getattr(client, "_transport", None), httpx.MockTransport)


async def _guarded_async_send(
    self: httpx.AsyncClient, request: httpx.Request, **kwargs: object
) -> httpx.Response:
    if _is_mock_transport(self) or request.url.host in _ALLOWED_TEST_HOSTS:
        return await _ORIGINAL_ASYNC_CLIENT_SEND(self, request, **kwargs)  # type: ignore[arg-type]
    raise NetworkEgressBlockedTestError(
        f"Blocked outbound HTTP request to {request.url.host!r} ({request.method} {request.url}) "
        "during pytest - real network egress is not permitted. Use httpx.MockTransport instead. "
        "(Phase 18.9-R Barrier 3 - docs/phase18_9r_test_provider_path_audit.md)"
    )


def _guarded_sync_send(self: httpx.Client, request: httpx.Request, **kwargs: object) -> httpx.Response:
    if _is_mock_transport(self) or request.url.host in _ALLOWED_TEST_HOSTS:
        return _ORIGINAL_CLIENT_SEND(self, request, **kwargs)  # type: ignore[arg-type]
    raise NetworkEgressBlockedTestError(
        f"Blocked outbound HTTP request to {request.url.host!r} ({request.method} {request.url}) "
        "during pytest - real network egress is not permitted. Use httpx.MockTransport instead. "
        "(Phase 18.9-R Barrier 3 - docs/phase18_9r_test_provider_path_audit.md)"
    )


httpx.AsyncClient.send = _guarded_async_send  # type: ignore[method-assign]
httpx.Client.send = _guarded_sync_send  # type: ignore[method-assign]


# ---------------------------------------------------------------------------
# Phase 23.1L Barrier 4 (test/live database isolation) - a real, confirmed incident (docs/
# phase23_1l_runtime_isolation_final_canary_report.md): integration tests committed real rows
# into `settings.postgres_db` (the same database the live canary and production containers read
# from) via `create_async_engine(settings.database_url, ...)`, and hand-maintained per-table
# teardown DELETEs fell behind a newly-added FK-referencing table, silently orphaning them - one
# of those orphaned rows was later selected as a genuinely "eligible" event and generated two real
# Telegram posts. Cleanup discipline is not a fix (Phase 23.1L's own explicit framing: "cleanup is
# not isolation") - the fix is that no pytest process can open a write-capable connection to
# `settings.postgres_db` at all, structurally, checked BEFORE any engine is even constructed (pure
# string comparison, zero I/O - the earliest possible point, applied at module import time exactly
# like Barriers 1-3 above, not dependent on any individual fixture remembering to call this).
#
# Exact identity comparison, not substring matching (deliberately, per the phase brief's own
# instruction) - `settings.postgres_test_db` (e.g. "ai_newsroom_test") must equal the target
# database's name AND that name must NOT equal `settings.postgres_db` (e.g. "ai_newsroom"),
# checked independently so a misconfigured .env where both settings happen to coincide is still
# caught, not silently allowed through.
# ---------------------------------------------------------------------------


class DatabaseIsolationViolationError(RuntimeError):
    """Raised when a test attempted to connect to the real/dev database instead of the dedicated
    pytest database (Phase 23.1L Barrier 4). If you see this, use settings.test_database_url
    (via independent_session_factory() or the db_session fixture below), never
    settings.database_url, in any test."""


def assert_is_test_database(db_name: str) -> None:
    if db_name == settings.postgres_db:
        raise DatabaseIsolationViolationError(
            f"REFUSING TO CONNECT: {db_name!r} is the real/dev database (settings.postgres_db). "
            f"Tests must use settings.test_database_url ({settings.postgres_test_db!r}), never "
            "settings.database_url. (Phase 23.1L Barrier 4)"
        )
    if db_name != settings.postgres_test_db:
        raise DatabaseIsolationViolationError(
            f"REFUSING TO CONNECT: {db_name!r} does not match the expected pytest database "
            f"{settings.postgres_test_db!r} (settings.postgres_test_db). (Phase 23.1L Barrier 4)"
        )


assert_is_test_database(settings.postgres_test_db)  # fails fast at import time if misconfigured


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    """A real async Redis client, freshly constructed per test (docker-compose already
    provisions Redis) - deliberately NOT core.redis.get_redis_client()'s module-level
    @lru_cache singleton, for the same reason db_session above doesn't reuse
    database.session.engine: pytest-asyncio gives each test function its own event loop by
    default, and a connection pool first opened on one test's loop breaks (RuntimeError:
    Event loop is closed) when reused from a later test's loop. A fresh client per test
    sidesteps this entirely.

    Phase 18.9-R M5: connects to `TEST_REDIS_DB_INDEX` (15), never production's real index 0
    (`settings.redis_db`) - structural isolation, not merely the per-test unique-namespace
    convention every test using this fixture must still additionally follow for keys *within*
    this test database (Phase 7's Redis-backed components - CacheStore, RateLimiter,
    ProviderHealthStore, LatencyTracker, the real CostTracker ledger shape - are exercised
    against this same, now-isolated instance)."""
    test_redis_url = f"redis://{settings.redis_host}:{settings.redis_port}/{TEST_REDIS_DB_INDEX}"
    client = Redis.from_url(test_redis_url, decode_responses=True)
    try:
        yield client
    finally:
        await client.aclose()


@pytest_asyncio.fixture
async def db_session() -> AsyncGenerator[AsyncSession, None]:
    """A real Postgres AsyncSession whose work is always rolled back at teardown."""
    async with _test_engine.connect() as connection:
        await connection.begin()
        async with AsyncSession(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        ) as session:
            yield session
        await connection.rollback()


@pytest_asyncio.fixture
async def real_news_event(db_session: AsyncSession) -> NewsEvent:
    """A real NewsSource + NewsEvent row, rolled back with the rest of the test transaction."""
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url="https://example.com/test-feed.xml", active=True
    )
    db_session.add(source)
    await db_session.flush()

    event = NewsEvent(
        source_id=source.id,
        title="Test event",
        content="Test content",
        category=EventCategory.AI,
        hash=f"test-hash-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    return event
