"""Tests for worker.analysis_cycle (Phase 13 M3).

Real Postgres, no separate test database - every test uses independent_session_factory()
(imported from tests.test_triage_orchestrator_claims, the already-established, already-proven
helper this repository's own Phase 12/9 integration tests reuse) with explicit, FK-safe,
test-owned cleanup - never rollback-only isolation, never a table-wide delete.
"""
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from capabilities.errors import PermanentCapabilityError
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.capability import CapabilityContext, CapabilityResult
from schemas.capability_definition import CapabilityConfig, CapabilityDefinition
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from tests.fakes.fake_capability import AlwaysSucceedsCapability
from tests.test_triage_orchestrator_claims import independent_session_factory
from worker.analysis_cycle import _select_eligible_task_ids, run_analysis_cycle


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest_asyncio.fixture
async def test_source(factory: async_sessionmaker[AsyncSession]) -> AsyncIterator[NewsSource]:
    unique_name = f"phase13-analysis-cycle-test-{uuid4()}"
    async with factory() as session:
        source = NewsSource(name=unique_name, type=SourceType.RSS, active=True)
        session.add(source)
        await session.commit()

    try:
        yield source
    finally:
        async with factory() as session:
            event_ids = (
                await session.execute(select(NewsEvent.id).where(NewsEvent.source_id == source.id))
            ).scalars().all()
            if event_ids:
                await session.execute(delete(EditorialTask).where(EditorialTask.event_id.in_(event_ids)))
                await session.execute(delete(NewsEvent).where(NewsEvent.id.in_(event_ids)))
            await session.execute(delete(NewsSource).where(NewsSource.id == source.id))
            await session.commit()


async def _make_event(
    session: AsyncSession,
    source: NewsSource,
    *,
    published_at: datetime | None,
) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id,
        title=f"Analysis cycle test event {uuid4()}",
        category=EventCategory.AI,
        hash=f"analysis-cycle-test-{uuid4()}",
        published_at=published_at,
    )
    session.add(event)
    await session.flush()
    await session.commit()
    return event


async def _make_created_task(
    session: AsyncSession, event: NewsEvent, workflow_type: WorkflowType
) -> EditorialTask:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=workflow_type, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None
    return task


# ---------------------------------------------------------------------------
# _select_eligible_task_ids() - SQL-side filtering
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fresh_news_analysis_created_task_is_eligible(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)

        eligible = await _select_eligible_task_ids(session)

        assert task.id in eligible


@pytest.mark.asyncio
async def test_stale_task_beyond_48h_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        stale_published_at = datetime.now(timezone.utc) - timedelta(hours=72)
        event = await _make_event(session, test_source, published_at=stale_published_at)
        task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)

        eligible = await _select_eligible_task_ids(session)

        assert task.id not in eligible


@pytest.mark.asyncio
async def test_content_generation_workflow_task_is_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """The GREEN proof (docs/phase13_automatic_news_analysis_implementation_plan.md §9.1): a
    test-owned CONTENT_GENERATION task must NOT be matched by the .as_string() workflow-name
    predicate, proving the extraction is workflow-specific, not a substring/any-match."""
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task = await _make_created_task(session, event, WorkflowType.CONTENT_GENERATION)

        eligible = await _select_eligible_task_ids(session)

        assert task.id not in eligible


@pytest.mark.asyncio
async def test_running_completed_failed_tasks_are_excluded(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        for status in (TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            task.status = status
            await session.commit()

        eligible = await _select_eligible_task_ids(session)

        # None of the three non-CREATED tasks just inserted appear.
        async with factory() as verify_session:
            all_task_ids = (
                await verify_session.execute(
                    select(EditorialTask.id).where(EditorialTask.event_id.in_(
                        select(NewsEvent.id).where(NewsEvent.source_id == test_source.id)
                    ))
                )
            ).scalars().all()
        for task_id in all_task_ids:
            assert task_id not in eligible


@pytest.mark.asyncio
async def test_batch_cap_selects_exactly_five_of_six_plus_eligible(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        created_ids = []
        for _ in range(6):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            created_ids.append(task.id)

        eligible = await _select_eligible_task_ids(session)

        matched = [task_id for task_id in eligible if task_id in created_ids]
        assert len(matched) == 5  # LIMIT settings.news_analysis_batch_size (default 5), hard cap


@pytest.mark.asyncio
async def test_ordering_is_deterministic_oldest_created_first(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    async with factory() as session:
        ordered_ids = []
        for _ in range(3):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            ordered_ids.append(task.id)

        eligible = await _select_eligible_task_ids(session)

        matched = [task_id for task_id in eligible if task_id in ordered_ids]
        assert matched == ordered_ids  # created_at ASC, id ASC - insertion order preserved


# ---------------------------------------------------------------------------
# run_analysis_cycle() - orchestration: sequential execution, lost-race handling,
# mid-batch per-task failure.
#
# Uses the REAL, unmodified, default workflows.registry.registry singleton (NEWS_ANALYSIS's
# real 4-step definition: research -> intelligence -> engagement_analysis -> scoring, exactly
# as WorkflowRunner(executor) constructs it inside worker/analysis_cycle.py with no registry
# override) - no synthetic WorkflowRegistry, no monkeypatching of the shared singleton. Only the
# CapabilityRegistry is test-local: four fake Capabilities registered under the four real
# capability names the real definition expects, so no LLM/network call is ever made.
#
# CRITICAL isolation note: run_analysis_cycle() calls the real, deliberately-unscoped
# _select_eligible_task_ids() against the shared dev database - by design, it has no
# test-scoping hook (exactly the same eligibility query production use, per the Plan's own M7
# isolation discussion). This repository's real backlog currently contains 1000+ genuinely
# fresh-eligible NEWS_ANALYSIS/CREATED tasks (confirmed by direct read-only query this session,
# newest ~4.9 hours old). Without isolation, run_analysis_cycle() would claim and mutate REAL
# production EditorialTask rows with this test's own fake capability output - unacceptable.
# Every test below that actually calls run_analysis_cycle() (not merely
# _select_eligible_task_ids() directly, which is read-only and therefore safe as-is) must use
# the _isolated_freshness_window fixture, which temporarily narrows
# settings.news_analysis_freshness_cutoff_hours to a few minutes - far below the real backlog's
# multi-hour minimum age, comfortably above this test's own execution time - so only this test's
# own just-created rows are ever eligible.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def _isolated_freshness_window() -> AsyncIterator[None]:
    from core.config import settings as real_settings

    original = real_settings.news_analysis_freshness_cutoff_hours
    real_settings.news_analysis_freshness_cutoff_hours = 0.05  # 3 minutes - far below the real
    # backlog's confirmed multi-hour minimum age, comfortably above this test's own runtime.
    try:
        yield
    finally:
        real_settings.news_analysis_freshness_cutoff_hours = original


def _definition(name: str) -> CapabilityDefinition:
    return CapabilityDefinition(
        name=name,
        version=1,
        config=CapabilityConfig(timeout_seconds=10),
        required_context=["news_event"],
        expected_output_keys=["ok"],
    )


class _FirstStepSpyCapability:
    """Registered under "research" (NEWS_ANALYSIS's first, required step) - every other real
    capability name ("intelligence", "engagement", "scoring") is registered as an unconditional
    AlwaysSucceedsCapability, so this one capability's own behavior fully determines whether a
    given task proceeds to COMPLETED or fails immediately. Records call order; supports an
    optional side-effect hook invoked once per call, used by the lost-race test to externally
    claim another task mid-cycle."""

    def __init__(
        self,
        *,
        failing_task_ids: set | None = None,
        on_call=None,
    ) -> None:
        self._failing_task_ids = failing_task_ids or set()
        self._on_call = on_call
        self.call_order: list = []

    async def execute(self, context: CapabilityContext) -> CapabilityResult:
        self.call_order.append(context.runtime.task_id)
        if self._on_call is not None:
            await self._on_call(context.runtime.task_id)
        if context.runtime.task_id in self._failing_task_ids:
            raise PermanentCapabilityError("intentional mid-batch test failure")
        return await AlwaysSucceedsCapability().execute(context)


def _real_news_analysis_capability_registry(research_capability) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(_definition("research"), research_capability)
    registry.register(_definition("intelligence"), AlwaysSucceedsCapability())
    registry.register(_definition("engagement"), AlwaysSucceedsCapability())
    registry.register(_definition("scoring"), AlwaysSucceedsCapability())
    registry.seal()
    return registry


@pytest.mark.asyncio
async def test_run_analysis_cycle_sequential_execution_no_gather(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """No asyncio.gather anywhere in run_analysis_cycle() - proven both by static grep (no
    'gather' token in worker/analysis_cycle.py) and behaviorally (a spy capability records call
    order; three claimed tasks are attempted one-at-a-time, in selection order)."""
    from pathlib import Path

    source_text = Path("worker/analysis_cycle.py").read_text(encoding="utf-8")
    assert "gather" not in source_text

    ordered_ids = []
    async with factory() as session:
        for _ in range(3):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            ordered_ids.append(task.id)

    spy = _FirstStepSpyCapability()
    registry = _real_news_analysis_capability_registry(spy)

    result = await run_analysis_cycle(registry, session_factory=factory)

    matched_order = [task_id for task_id in spy.call_order if task_id in ordered_ids]
    assert matched_order == ordered_ids  # attempted in selection order, one at a time
    assert result.completed == 3
    assert result.failed == 0


@pytest.mark.asyncio
async def test_run_analysis_cycle_lost_race_is_not_fatal_and_not_refilled(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """task1 is processed normally; while task1's own "research" step is executing, an
    external claimant (a separate session, simulating another worker/cycle) atomically claims
    task2 to RUNNING. When the cycle's own loop then reaches task2, its atomic claim must lose
    (rowcount 0), be caught as TaskAlreadyRunningError, counted as a lost race - not fatal to
    the cycle, no replacement candidate fetched."""
    from sqlalchemy import update as sa_update

    async with factory() as session:
        event1 = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task1 = await _make_created_task(session, event1, WorkflowType.NEWS_ANALYSIS)
        event2 = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        task2 = await _make_created_task(session, event2, WorkflowType.NEWS_ANALYSIS)

    async def _externally_claim_task2(called_for_task_id) -> None:
        if called_for_task_id != task1.id:
            return
        async with factory() as claimer_session:
            await claimer_session.execute(
                sa_update(EditorialTask)
                .where(EditorialTask.id == task2.id, EditorialTask.status == TaskStatus.CREATED)
                .values(status=TaskStatus.RUNNING)
            )
            await claimer_session.commit()

    spy = _FirstStepSpyCapability(on_call=_externally_claim_task2)
    registry = _real_news_analysis_capability_registry(spy)

    result = await run_analysis_cycle(registry, session_factory=factory)

    assert task1.id in result.task_ids
    assert task2.id in result.task_ids
    assert result.eligible_found == 2
    assert result.claimed == 1  # only task1
    assert result.lost_races == 1  # task2
    assert result.completed == 1
    assert result.failed == 0

    async with factory() as verify_session:
        final_task1 = await verify_session.get(EditorialTask, task1.id)
        final_task2 = await verify_session.get(EditorialTask, task2.id)
        assert final_task1 is not None and final_task1.status == TaskStatus.COMPLETED
        # task2 was claimed externally (by the "competitor"), left RUNNING - the cycle never
        # touched it again, never refilled with a replacement candidate.
        assert final_task2 is not None and final_task2.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_run_analysis_cycle_mid_batch_per_task_failure_does_not_abort_remaining(
    factory: async_sessionmaker[AsyncSession], test_source: NewsSource, _isolated_freshness_window: None
) -> None:
    """task1 completes, task2 fails during its own workflow execution, task3 (already selected)
    still executes and completes - no replacement candidate fetched, cycle does not abort."""
    task_ids = []
    async with factory() as session:
        for _ in range(3):
            event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
            task = await _make_created_task(session, event, WorkflowType.NEWS_ANALYSIS)
            task_ids.append(task.id)
    task1_id, task2_id, task3_id = task_ids

    spy = _FirstStepSpyCapability(failing_task_ids={task2_id})
    registry = _real_news_analysis_capability_registry(spy)

    result = await run_analysis_cycle(registry, session_factory=factory)

    assert result.eligible_found == 3
    assert result.claimed == 3  # all three were successfully claimed (no race lost)
    assert result.completed == 2  # task1, task3
    assert result.failed == 1  # task2
    assert task1_id in spy.call_order
    assert task2_id in spy.call_order
    assert task3_id in spy.call_order  # task3 was still attempted - no abort, no refill needed

    async with factory() as verify_session:
        final1 = await verify_session.get(EditorialTask, task1_id)
        final2 = await verify_session.get(EditorialTask, task2_id)
        final3 = await verify_session.get(EditorialTask, task3_id)
        assert final1 is not None and final1.status == TaskStatus.COMPLETED
        assert final2 is not None and final2.status == TaskStatus.FAILED
        assert final3 is not None and final3.status == TaskStatus.COMPLETED
