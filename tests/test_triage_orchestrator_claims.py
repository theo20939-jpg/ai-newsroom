"""Tests for services.triage_orchestrator's atomic claim/recovery primitives.

Integration-tier, real Postgres (Contract §16's explicit instruction that this is
integration- not unit-tier). The concurrency tests use two fully independent
AsyncSession/connection pairs from a locally-constructed engine - never the shared
tests/conftest.py::db_session fixture, whose single physical connection (SAVEPOINT
mode) cannot model genuine cross-connection races. This helper is defined locally in
this file (M2's own test module) and reused, via a plain import, by
tests/test_triage_orchestrator_cycle.py (M3) - exactly two Phase 9 test modules need
it, so a local, Phase-9-scoped helper is used rather than a new tests/conftest.py
fixture (kept out of the shared, repo-wide fixture file).
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import Settings, settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, EventStatus, NewsEvent
from database.models.news_source import NewsSource, SourceType
from services.triage_orchestrator import (
    _acquire_recovery_ownership,
    _claim_new_event,
    _select_recovery_candidates,
)

UTC = timezone.utc


def independent_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """A fresh engine + session factory, fully independent of any other test's
    connection - required for genuine cross-connection concurrency proofs."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def real_committed_event(
    factory: async_sessionmaker[AsyncSession],
    *,
    status: EventStatus = EventStatus.NEW,
    updated_at: datetime | None = None,
) -> AsyncIterator[UUID]:
    """Insert a real, committed NewsSource + NewsEvent pair (not wrapped in the
    db_session fixture's rollback-on-teardown SAVEPOINT, since the concurrency tests
    need genuinely separate, independently-committing sessions) and delete both rows
    on exit, regardless of what the test did to them."""
    async with factory() as session:
        source = NewsSource(name=f"claims-test-{uuid4()}", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()

        event = NewsEvent(
            source_id=source.id,
            title="Concurrency test event",
            category=EventCategory.UNKNOWN,
            hash=f"claims-test-{uuid4()}",
            status=status,
        )
        session.add(event)
        await session.flush()
        if updated_at is not None:
            event.updated_at = updated_at
        await session.commit()
        event_id = event.id
        source_id = source.id

    try:
        yield event_id
    finally:
        async with factory() as session:
            existing_event = await session.get(NewsEvent, event_id)
            if existing_event is not None:
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id == event_id))
                await session.delete(existing_event)
            existing_source = await session.get(NewsSource, source_id)
            if existing_source is not None:
                await session.delete(existing_source)
            await session.commit()


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


# ---------------------------------------------------------------------------
# _claim_new_event
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_new_event_succeeds_and_persists_after_commit(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        now = datetime.now(UTC)
        async with factory() as session:
            won = await _claim_new_event(session, event_id, now=now)
            assert won is True
            await session.commit()

        async with factory() as verify_session:
            event = await verify_session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING


@pytest.mark.asyncio
async def test_claim_non_new_event_returns_false_and_leaves_row_unchanged(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory, status=EventStatus.PROCESSING) as event_id:
        async with factory() as session:
            won = await _claim_new_event(session, event_id, now=datetime.now(UTC))
            assert won is False
            await session.rollback()

        async with factory() as verify_session:
            event = await verify_session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING


@pytest.mark.asyncio
async def test_two_normal_claimants_exactly_one_wins(factory: async_sessionmaker[AsyncSession]) -> None:
    async with real_committed_event(factory) as event_id:
        now = datetime.now(UTC)

        async def _attempt() -> bool:
            async with factory() as session:
                won = await _claim_new_event(session, event_id, now=now)
                if won:
                    await session.commit()
                else:
                    await session.rollback()
                return won

        results = await asyncio.gather(_attempt(), _attempt())

        assert sorted(results) == [False, True]

        async with factory() as verify_session:
            event = await verify_session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING


# ---------------------------------------------------------------------------
# _select_recovery_candidates - eligibility invariant
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_processing_event_is_not_a_recovery_candidate(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=now) as event_id:
        async with factory() as session:
            candidates = await _select_recovery_candidates(
                session, now=now, staleness_threshold_seconds=900
            )
        assert event_id not in {c.id for c in candidates}


@pytest.mark.asyncio
async def test_exact_threshold_age_is_not_yet_stale(factory: async_sessionmaker[AsyncSession]) -> None:
    now = datetime.now(UTC)
    threshold_seconds = 300
    claimed_at = now - timedelta(seconds=threshold_seconds)  # age == threshold, exactly

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=claimed_at) as event_id:
        async with factory() as session:
            candidates = await _select_recovery_candidates(
                session, now=now, staleness_threshold_seconds=threshold_seconds
            )
        assert event_id not in {c.id for c in candidates}


@pytest.mark.asyncio
async def test_just_past_threshold_age_is_stale(factory: async_sessionmaker[AsyncSession]) -> None:
    now = datetime.now(UTC)
    threshold_seconds = 300
    claimed_at = now - timedelta(seconds=threshold_seconds + 1)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=claimed_at) as event_id:
        async with factory() as session:
            candidates = await _select_recovery_candidates(
                session, now=now, staleness_threshold_seconds=threshold_seconds
            )
        assert event_id in {c.id for c in candidates}


@pytest.mark.asyncio
async def test_future_updated_at_is_not_stale(factory: async_sessionmaker[AsyncSession]) -> None:
    now = datetime.now(UTC)
    future = now + timedelta(hours=1)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=future) as event_id:
        async with factory() as session:
            candidates = await _select_recovery_candidates(session, now=now, staleness_threshold_seconds=1)
        assert event_id not in {c.id for c in candidates}


@pytest.mark.asyncio
async def test_active_task_blocks_recovery_regardless_of_age(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    very_old = now - timedelta(days=30)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=very_old) as event_id:
        async with factory() as session:
            task = EditorialTask(
                event_id=event_id,
                priority=TaskPriority.B,
                status=TaskStatus.CREATED,
                workflow={"workflow_name": "NEWS_ANALYSIS", "workflow_version": 1, "step_results": []},
            )
            session.add(task)
            await session.commit()

        async with factory() as session:
            candidates = await _select_recovery_candidates(session, now=now, staleness_threshold_seconds=1)
        assert event_id not in {c.id for c in candidates}


@pytest.mark.asyncio
async def test_stale_processing_with_no_active_task_is_a_candidate(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    stale = now - timedelta(hours=1)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=stale) as event_id:
        async with factory() as session:
            candidates = await _select_recovery_candidates(session, now=now, staleness_threshold_seconds=60)
        assert event_id in {c.id for c in candidates}


# ---------------------------------------------------------------------------
# _acquire_recovery_ownership
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_acquire_recovery_ownership_succeeds_with_correct_observed_value(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    stale_updated_at = datetime.now(UTC) - timedelta(hours=1)
    async with real_committed_event(
        factory, status=EventStatus.PROCESSING, updated_at=stale_updated_at
    ) as event_id:
        now = datetime.now(UTC)
        async with factory() as session:
            won = await _acquire_recovery_ownership(session, event_id, stale_updated_at, now=now)
            assert won is True
            await session.commit()

        async with factory() as verify_session:
            event = await verify_session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING
            assert event.updated_at != stale_updated_at


@pytest.mark.asyncio
async def test_two_recovery_claimants_exactly_one_wins(factory: async_sessionmaker[AsyncSession]) -> None:
    stale_updated_at = datetime.now(UTC) - timedelta(hours=1)
    async with real_committed_event(
        factory, status=EventStatus.PROCESSING, updated_at=stale_updated_at
    ) as event_id:
        now = datetime.now(UTC)

        async def _attempt() -> bool:
            async with factory() as session:
                won = await _acquire_recovery_ownership(session, event_id, stale_updated_at, now=now)
                if won:
                    await session.commit()
                else:
                    await session.rollback()
                return won

        results = await asyncio.gather(_attempt(), _attempt())

        assert sorted(results) == [False, True]


@pytest.mark.asyncio
async def test_stale_ownership_toctou_reuse_of_superseded_value_fails(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """After a successful acquisition, a second attempt using the same, now-superseded
    observed_updated_at value must affect zero rows - the structural re-check §7.6
    describes, proven directly."""
    stale_updated_at = datetime.now(UTC) - timedelta(hours=1)
    async with real_committed_event(
        factory, status=EventStatus.PROCESSING, updated_at=stale_updated_at
    ) as event_id:
        now = datetime.now(UTC)
        async with factory() as session:
            first = await _acquire_recovery_ownership(session, event_id, stale_updated_at, now=now)
            assert first is True
            await session.commit()

        async with factory() as session:
            second = await _acquire_recovery_ownership(session, event_id, stale_updated_at, now=now)
            assert second is False
            await session.rollback()


@pytest.mark.asyncio
async def test_losing_claimant_view_shows_no_mutation_it_did_not_cause(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        now = datetime.now(UTC)
        async with factory() as winner_session:
            assert await _claim_new_event(winner_session, event_id, now=now) is True
            await winner_session.commit()

        async with factory() as loser_session:
            won = await _claim_new_event(loser_session, event_id, now=now)
            assert won is False
            await loser_session.rollback()

        async with factory() as verify_session:
            event = await verify_session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING
            assert event.updated_at == now


# ---------------------------------------------------------------------------
# Recovery of a claimed-but-never-progressed event (rerun safety, partial - full
# create_task()-outcome handling is M3's own test responsibility, not duplicated here)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claimed_but_never_progressed_event_becomes_recoverable_once_stale(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        claim_time = datetime.now(UTC)
        async with factory() as session:
            assert await _claim_new_event(session, event_id, now=claim_time) is True
            await session.commit()

        # Not yet stale.
        async with factory() as session:
            candidates = await _select_recovery_candidates(session, now=claim_time, staleness_threshold_seconds=60)
        assert event_id not in {c.id for c in candidates}

        # Aged past the threshold.
        later = claim_time + timedelta(seconds=120)
        async with factory() as session:
            candidates = await _select_recovery_candidates(session, now=later, staleness_threshold_seconds=60)
        assert event_id in {c.id for c in candidates}


# ---------------------------------------------------------------------------
# Staleness-threshold configuration validation
# ---------------------------------------------------------------------------


def test_positive_stale_threshold_is_accepted() -> None:
    assert Settings(stale_processing_threshold_seconds=900).stale_processing_threshold_seconds == 900
    assert Settings(stale_processing_threshold_seconds=1).stale_processing_threshold_seconds == 1


def test_zero_stale_threshold_is_rejected() -> None:
    with pytest.raises(Exception, match="greater than 0"):
        Settings(stale_processing_threshold_seconds=0)


def test_negative_stale_threshold_is_rejected() -> None:
    with pytest.raises(Exception, match="greater than 0"):
        Settings(stale_processing_threshold_seconds=-1)


@pytest.mark.asyncio
async def test_configured_threshold_deterministically_affects_eligibility(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    now = datetime.now(UTC)
    age_seconds = 500
    claimed_at = now - timedelta(seconds=age_seconds)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=claimed_at) as event_id:
        async with factory() as session:
            narrow_threshold_candidates = await _select_recovery_candidates(
                session, now=now, staleness_threshold_seconds=age_seconds - 100
            )
        assert event_id in {c.id for c in narrow_threshold_candidates}

        async with factory() as session:
            wide_threshold_candidates = await _select_recovery_candidates(
                session, now=now, staleness_threshold_seconds=age_seconds + 100
            )
        assert event_id not in {c.id for c in wide_threshold_candidates}
