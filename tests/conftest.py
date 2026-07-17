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
"""
import uuid
from collections.abc import AsyncGenerator

import pytest_asyncio
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType

_test_engine = create_async_engine(settings.database_url, poolclass=NullPool)


@pytest_asyncio.fixture
async def redis_client() -> AsyncGenerator[Redis, None]:
    """A real async Redis client, freshly constructed per test (docker-compose already
    provisions Redis) - deliberately NOT core.redis.get_redis_client()'s module-level
    @lru_cache singleton, for the same reason db_session above doesn't reuse
    database.session.engine: pytest-asyncio gives each test function its own event loop by
    default, and a connection pool first opened on one test's loop breaks (RuntimeError:
    Event loop is closed) when reused from a later test's loop. A fresh client per test
    sidesteps this entirely.

    Phase 7's Redis-backed components (CacheStore, RateLimiter, ProviderHealthStore,
    LatencyTracker, the real CostTracker ledger) are tested against this directly - every
    test using it MUST write only uniquely namespaced keys and delete them in its own
    teardown, since this fixture does not wrap Redis in a transaction the way `db_session`
    wraps Postgres (Redis has no equivalent rollback-on-teardown mechanism here).
    """
    client = Redis.from_url(settings.redis_url, decode_responses=True)
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
