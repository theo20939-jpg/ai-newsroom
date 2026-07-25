"""Phase 15 M1 end-to-end tests: the invalid-title rejection gate (M1.2) and the
duplicate-task dedup fix (M1.3), exercised through the real run_triage_cycle().

Integration-tier, real Postgres, via independent_session_factory()/real_committed_event()
- the same pattern tests/test_triage_orchestrator_cycle.py already uses, deliberately not
tests/conftest.py's shared db_session fixture (Phase 13 M3's incident: an unscoped
eligibility query run against a populated shared database can claim/mutate unrelated
real backlog rows). Every event this file creates is source-tagged uniquely and deleted
in real_committed_event()'s own teardown, so this module cannot touch any pre-existing
production row.

Phase 15 M1 finalization note: run_triage_cycle() genuinely has no test-scoping (matches
production - the same query real workers use) - even with all live workers stopped, any
NEW-status backlog already sitting in the database before a test runs is claimed and
processed alongside this file's own test-owned event in the same cycle. Every assertion
below is therefore scoped to the one event/task each test itself created (via TriageCycleReport-
independent, direct-query checks) rather than to run_triage_cycle()'s aggregate TriageCycleReport
counters, which reflect the whole cycle - including any concurrent backlog - and are not a safe
thing for a shared-database test to assert exact values of.
"""
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventStatus, NewsEvent
from services.triage_orchestrator import run_triage_cycle
from tests.test_triage_orchestrator_claims import independent_session_factory, real_committed_event

UTC = timezone.utc


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


async def _task_count(factory: async_sessionmaker[AsyncSession], event_id: UUID) -> int:
    async with factory() as session:
        result = await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
        return len(result.scalars().all())


async def _event_status(factory: async_sessionmaker[AsyncSession], event_id: UUID) -> EventStatus:
    async with factory() as session:
        event = await session.get(NewsEvent, event_id)
        assert event is not None
        return event.status


# ---------------------------------------------------------------------------
# M1.2 - early invalid-event gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("malformed_title", ["<a", '<img src="x.png">', '<details open="">', "   "])
async def test_malformed_title_event_is_rejected_before_triage_or_task_creation(
    factory: async_sessionmaker[AsyncSession], malformed_title: str
) -> None:
    """The live-observed failure mode (Phase 15 M0): a malformed title must never reach
    NEWS_ANALYSIS - not even to be scored - since scoring alone already proved unreliable
    (one real Techmeme event with a raw HTML title scored 78 and was delivered). Proves
    the outcome for this test's own event: status=REJECTED and zero EditorialTask rows -
    structural proof no NEWS_ANALYSIS workflow, and therefore no LLM Gateway call, was ever
    possible for it (a WorkflowRunner/CapabilityExecutor call always requires an existing
    EditorialTask row to operate on; none exists here)."""
    async with real_committed_event(factory, title=malformed_title) as event_id:
        await run_triage_cycle(session_factory=factory)

        assert await _task_count(factory, event_id) == 0
        assert await _event_status(factory, event_id) == EventStatus.REJECTED

        async with factory() as session:
            event = await session.get(NewsEvent, event_id)
            assert event is not None
            # Prospective-only (Phase 15 M1 scope): title/content themselves are never
            # rewritten by this gate, only the lifecycle status.
            assert event.title == malformed_title


@pytest.mark.asyncio
async def test_valid_title_event_is_unaffected_by_the_gate(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory, title="A perfectly normal headline") as event_id:
        await run_triage_cycle(session_factory=factory)

        assert await _task_count(factory, event_id) == 1
        assert await _event_status(factory, event_id) == EventStatus.PROCESSING


# ---------------------------------------------------------------------------
# M1.3 - duplicate-task dedup gap, reproduced end-to-end through run_triage_cycle()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stale_event_with_completed_sibling_does_not_get_a_duplicate_task(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Reproduces the exact production mechanism Phase 15 M0 found (108 duplicated
    NewsEvent rows): a NewsEvent stuck at status=PROCESSING (nothing in this codebase
    ever advances it to ANALYZED) whose NEWS_ANALYSIS task already COMPLETED, aged past
    the recovery staleness threshold. Before this fix, run_triage_cycle() would "recover"
    it and create a second, unwanted NEWS_ANALYSIS task every time it went stale again."""
    now = datetime.now(UTC)
    very_old = now - timedelta(days=1)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=very_old) as event_id:
        async with factory() as session:
            session.add(
                EditorialTask(
                    event_id=event_id,
                    priority=TaskPriority.B,
                    status=TaskStatus.COMPLETED,
                    workflow={"workflow_name": "NEWS_ANALYSIS", "workflow_version": 1, "step_results": []},
                )
            )
            await session.commit()

        await run_triage_cycle(session_factory=factory)

        assert await _task_count(factory, event_id) == 1


@pytest.mark.asyncio
async def test_genuinely_abandoned_claim_with_no_task_still_recovers_normally(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    """Legitimate-recovery regression: an event claimed (PROCESSING) but never given any
    task at all (e.g. a worker crash between claim and create_task()) must still be
    recovered and get exactly one task - the M1.3 fix narrows dedup, it must not remove
    recovery for the case it was designed for."""
    now = datetime.now(UTC)
    very_old = now - timedelta(days=1)

    async with real_committed_event(factory, status=EventStatus.PROCESSING, updated_at=very_old) as event_id:
        await run_triage_cycle(session_factory=factory)

        assert await _task_count(factory, event_id) == 1
        assert await _event_status(factory, event_id) == EventStatus.PROCESSING
