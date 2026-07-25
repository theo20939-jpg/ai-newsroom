"""Tests for workflows.runner.WorkflowRunner - real Postgres, transaction rolled back per test.

Injects fake StepExecutor implementations to exercise retry/failure/timeout
paths - none of them call any AI provider or network endpoint. Timeout tests
use a throwaway WorkflowRegistry with a 1-second step/workflow timeout (the
schema's minimum, since WorkflowStepDefinition.timeout_seconds is an
integer >= 1) rather than the real registered definitions' 30s/120s budgets,
so they add only a few real seconds to the suite instead of minutes.
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_task import EditorialTaskCreate, EditorialTaskRead
from schemas.workflow import (
    WorkflowDefinition,
    WorkflowRetryPolicy,
    WorkflowStepDefinition,
    WorkflowType,
)
from services import workflow_service
from workflows.errors import (
    PermanentStepFailureError,
    StepExecutionError,
    TaskAlreadyCompletedError,
    TaskAlreadyRunningError,
)
from workflows.registry import WorkflowRegistry
from workflows.runner import WorkflowRunner


class _AlwaysSucceeds:
    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        return {"ok": True}


class _FailsThenSucceeds:
    def __init__(self, failures_before_success: int) -> None:
        self._remaining_failures = failures_before_success

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        if self._remaining_failures > 0:
            self._remaining_failures -= 1
            raise StepExecutionError(f"transient failure ({self._remaining_failures} left)")
        return {"ok": True}


class _AlwaysFailsPermanently:
    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        raise PermanentStepFailureError("cannot be retried")


class _AlwaysFailsRetryably:
    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        raise StepExecutionError("always fails")


class _SlowThenFast:
    """Sleeps past the step timeout on its first N calls, then returns instantly."""

    def __init__(self, slow_seconds: float, slow_calls: int = 1) -> None:
        self._slow_seconds = slow_seconds
        self._remaining_slow_calls = slow_calls

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        if self._remaining_slow_calls > 0:
            self._remaining_slow_calls -= 1
            await asyncio.sleep(self._slow_seconds)
        return {}


class _AlwaysSlow:
    def __init__(self, slow_seconds: float) -> None:
        self._slow_seconds = slow_seconds

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        await asyncio.sleep(self._slow_seconds)
        return {}


def _command(event_id, workflow_type: WorkflowType = WorkflowType.NEWS_ANALYSIS) -> EditorialTaskCreate:
    return EditorialTaskCreate(event_id=event_id, workflow_type=workflow_type, priority=TaskPriority.B)


def _single_step_registry(
    step_timeout: int, workflow_timeout: int, max_attempts: int = 3
) -> WorkflowRegistry:
    """A throwaway registry with one CONTENT_GENERATION definition, tuned for fast timeout tests."""
    registry = WorkflowRegistry()
    registry.register(
        WorkflowDefinition(
            name=WorkflowType.CONTENT_GENERATION,
            version=1,
            steps=[
                WorkflowStepDefinition(
                    name="slow_step", capability="research", max_attempts=max_attempts, timeout_seconds=step_timeout
                )
            ],
            max_iterations=3,
            retry_policy=WorkflowRetryPolicy(
                max_attempts=max_attempts, retryable_error_types=["StepExecutionError", "StepTimeoutError"]
            ),
            timeout_seconds=workflow_timeout,
            required_input=["event_id"],
            expected_output=["result"],
        )
    )
    registry.seal()
    return registry


async def _created_task(session: AsyncSession, event: NewsEvent) -> EditorialTaskRead:
    return await workflow_service.create_task(session, _command(event.id))


@pytest.mark.asyncio
async def test_successful_run_completes(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_AlwaysSucceeds())

    result = await runner.run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.iterations_used == 1
    assert len(result.step_results) == 4  # NEWS_ANALYSIS has 4 steps
    assert all(r.status == "SUCCESS" for r in result.step_results)

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_step_failure_without_successful_retry_fails_task(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_AlwaysFailsRetryably())

    result = await runner.run(db_session, task.id)

    assert result.status == "FAILED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED


@pytest.mark.asyncio
async def test_retry_succeeds_on_second_attempt(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_FailsThenSucceeds(failures_before_success=1))

    result = await runner.run(db_session, task.id)

    assert result.status == "COMPLETED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.retry_count >= 1


@pytest.mark.asyncio
async def test_permanent_failure_stops_immediately_without_retry(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_AlwaysFailsPermanently())

    result = await runner.run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 1  # failed on the first step, no further steps attempted
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.retry_count == 0  # no retries for a permanent failure


@pytest.mark.asyncio
async def test_max_attempts_exhausted_fails_after_retrying(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_AlwaysFailsRetryably())

    result = await runner.run(db_session, task.id)

    assert result.status == "FAILED"
    first_step_attempts = [r for r in result.step_results if r.step_name == "research"]
    assert len(first_step_attempts) == 3  # NEWS_ANALYSIS's steps default to max_attempts=3


@pytest.mark.asyncio
async def test_max_iterations_exceeded_fails_without_running_any_step(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await _created_task(db_session, real_news_event)
    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    raw_task.workflow = {**raw_task.workflow, "iteration_count": 3}  # NEWS_ANALYSIS's max_iterations
    await db_session.commit()

    runner = WorkflowRunner(executor=_AlwaysSucceeds())
    result = await runner.run(db_session, task.id)

    assert result.status == "FAILED"
    assert result.step_results == []


@pytest.mark.asyncio
async def test_rerun_on_completed_task_raises(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _created_task(db_session, real_news_event)
    runner = WorkflowRunner(executor=_AlwaysSucceeds())
    await runner.run(db_session, task.id)

    with pytest.raises(TaskAlreadyCompletedError):
        await runner.run(db_session, task.id)


@pytest.mark.asyncio
async def test_rerun_on_running_task_raises(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await _created_task(db_session, real_news_event)
    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    raw_task.status = TaskStatus.RUNNING
    await db_session.commit()

    runner = WorkflowRunner(executor=_AlwaysSucceeds())
    with pytest.raises(TaskAlreadyRunningError):
        await runner.run(db_session, task.id)


# --- Timeout enforcement ---------------------------------------------------


@pytest.mark.asyncio
async def test_fast_step_completes_within_a_tight_timeout(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    registry = _single_step_registry(step_timeout=1, workflow_timeout=10)
    task = await workflow_service.create_task(
        db_session, _command(real_news_event.id, WorkflowType.CONTENT_GENERATION), registry=registry
    )

    result = await WorkflowRunner(executor=_AlwaysSucceeds(), registry=registry).run(db_session, task.id)

    assert result.status == "COMPLETED"
    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_step_timeout_then_successful_retry(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    registry = _single_step_registry(step_timeout=1, workflow_timeout=10)
    task = await workflow_service.create_task(
        db_session, _command(real_news_event.id, WorkflowType.CONTENT_GENERATION), registry=registry
    )

    result = await WorkflowRunner(
        executor=_SlowThenFast(slow_seconds=1.3, slow_calls=1), registry=registry
    ).run(db_session, task.id)

    assert result.status == "COMPLETED"
    assert result.step_results[0].status == "FAILED"  # the first (timed-out) attempt
    assert result.step_results[1].status == "SUCCESS"  # the retry
    assert "timeout" in (result.step_results[0].error or "").lower()

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.COMPLETED
    assert persisted.retry_count == 1  # one retry, recorded

    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    assert raw_task.workflow["iteration_count"] == 1  # unaffected by the retry


@pytest.mark.asyncio
async def test_step_timeout_exhausting_max_attempts_fails_task(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    registry = _single_step_registry(step_timeout=1, workflow_timeout=10, max_attempts=2)
    task = await workflow_service.create_task(
        db_session, _command(real_news_event.id, WorkflowType.CONTENT_GENERATION), registry=registry
    )

    result = await WorkflowRunner(executor=_AlwaysSlow(slow_seconds=1.3), registry=registry).run(db_session, task.id)

    assert result.status == "FAILED"
    assert len(result.step_results) == 2  # both attempts, both timed out
    assert all(r.status == "FAILED" for r in result.step_results)

    persisted = await workflow_service.get_task(db_session, task.id)
    assert persisted.status == TaskStatus.FAILED  # never left RUNNING


@pytest.mark.asyncio
async def test_whole_workflow_timeout_fails_task_distinctly_from_step_timeout(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    # Step budget (10s) is far larger than the workflow budget (1s), so only
    # the outer, whole-workflow timeout can fire here - proves the two are
    # not confused with each other.
    registry = _single_step_registry(step_timeout=10, workflow_timeout=1)
    task = await workflow_service.create_task(
        db_session, _command(real_news_event.id, WorkflowType.CONTENT_GENERATION), registry=registry
    )

    result = await WorkflowRunner(executor=_AlwaysSlow(slow_seconds=1.5), registry=registry).run(db_session, task.id)

    assert result.status == "FAILED"

    raw_task = await db_session.get(EditorialTask, task.id)
    assert raw_task is not None
    assert raw_task.status == TaskStatus.FAILED  # never left RUNNING
    failure = raw_task.workflow["failure"]
    assert failure is not None
    assert failure["error_type"] == "WorkflowTimeoutError"
    assert "timeout" in failure["message"].lower()


# ---------------------------------------------------------------------------
# Phase 13 M2: atomic CREATED->RUNNING claim, proven under genuine concurrency (docs/
# phase13_automatic_news_analysis_implementation_plan.md §8.1/§8.2/§19). Two fully independent
# AsyncSession/connection pairs, real Postgres row-locking - never the shared
# tests/conftest.py::db_session fixture (single physical SAVEPOINT connection, cannot model a
# genuine cross-connection race) - mirrors tests/test_triage_orchestrator_claims.py's own
# already-proven concurrency-test shape for _claim_new_event() exactly, not invented fresh.
# ---------------------------------------------------------------------------

def _independent_session_factory() -> tuple[AsyncEngine, async_sessionmaker[AsyncSession]]:
    """A fresh engine + session factory, fully independent of any other test's connection -
    required for genuine cross-connection concurrency proofs. Mirrors
    tests/test_triage_orchestrator_claims.py's own module-local helper of the same name."""
    engine = create_async_engine(settings.database_url, poolclass=NullPool)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _real_committed_created_task(
    factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[UUID]:
    """Insert a real, committed NewsSource + NewsEvent + EditorialTask(CREATED, a throwaway
    single-step CONTENT_GENERATION registry) - not wrapped in db_session's rollback SAVEPOINT,
    since the concurrency test needs genuinely separate, independently-committing sessions -
    and delete all three on exit, FK-safe order, regardless of what the test did to them."""
    registry = _single_step_registry(step_timeout=10, workflow_timeout=30)
    async with factory() as session:
        source = NewsSource(name=f"claim-test-{uuid4()}", type=SourceType.RSS, active=True)
        session.add(source)
        await session.flush()

        event = NewsEvent(
            source_id=source.id,
            title="Atomic claim concurrency test event",
            category=EventCategory.UNKNOWN,
            hash=f"claim-test-{uuid4()}",
        )
        session.add(event)
        await session.flush()
        await session.commit()
        event_id = event.id
        source_id = source.id

        task = await workflow_service.create_task(
            session, _command(event_id, WorkflowType.CONTENT_GENERATION), registry=registry
        )
        task_id = task.id

    try:
        yield task_id
    finally:
        async with factory() as session:
            existing_task = await session.get(EditorialTask, task_id)
            if existing_task is not None:
                await session.delete(existing_task)
            existing_event = await session.get(NewsEvent, event_id)
            if existing_event is not None:
                await session.delete(existing_event)
            existing_source = await session.get(NewsSource, source_id)
            if existing_source is not None:
                await session.delete(existing_source)
            await session.commit()


class _CountingAlwaysSucceeds:
    """Spy StepExecutor - proves the claim loser never enters CapabilityExecutor/executor path
    at all (its own execute() call count must remain 0)."""

    def __init__(self) -> None:
        self.call_count = 0

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        self.call_count += 1
        return {"ok": True}


@pytest_asyncio.fixture
async def _claim_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = _independent_session_factory()
    yield session_factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_atomic_claim_exactly_one_winner_under_real_concurrency(
    _claim_factory: async_sessionmaker[AsyncSession],
) -> None:
    registry = _single_step_registry(step_timeout=10, workflow_timeout=30)

    async with _real_committed_created_task(_claim_factory) as task_id:
        winner_executor = _CountingAlwaysSucceeds()
        loser_executor = _CountingAlwaysSucceeds()

        async def _attempt(executor: _CountingAlwaysSucceeds) -> str:
            async with _claim_factory() as session:
                runner = WorkflowRunner(executor=executor, registry=registry)
                try:
                    result = await runner.run(session, task_id)
                    return result.status
                except (TaskAlreadyRunningError, TaskAlreadyCompletedError):
                    return "LOST_RACE"

        results = await asyncio.gather(_attempt(winner_executor), _attempt(loser_executor))

        # Exactly one of the two attempts actually ran the workflow (reached COMPLETED); the
        # other lost the race and made zero capability/executor calls.
        outcomes = sorted(results)
        assert outcomes == ["COMPLETED", "LOST_RACE"]

        winner_calls = winner_executor.call_count
        loser_calls = loser_executor.call_count
        # Exactly one executor was ever invoked (the winner, exactly once - one step, no
        # retry needed); the other made zero calls, regardless of which local variable
        # ("winner_executor"/"loser_executor") actually won the real race.
        assert sorted([winner_calls, loser_calls]) == [0, 1]

        async with _claim_factory() as verify_session:
            final_task = await verify_session.get(EditorialTask, task_id)
            assert final_task is not None
            assert final_task.status == TaskStatus.COMPLETED  # never left RUNNING, no ambiguity


@pytest.mark.asyncio
async def test_atomic_claim_loser_never_marked_failed(
    _claim_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The claim loser raises TaskAlreadyRunningError/TaskAlreadyCompletedError - it must never
    cause the task to be (re-)marked FAILED merely because it lost the race."""
    registry = _single_step_registry(step_timeout=10, workflow_timeout=30)

    async with _real_committed_created_task(_claim_factory) as task_id:

        async def _attempt() -> str:
            async with _claim_factory() as session:
                runner = WorkflowRunner(executor=_CountingAlwaysSucceeds(), registry=registry)
                try:
                    result = await runner.run(session, task_id)
                    return result.status
                except (TaskAlreadyRunningError, TaskAlreadyCompletedError):
                    return "LOST_RACE"

        results = await asyncio.gather(_attempt(), _attempt())

        assert sorted(results) == ["COMPLETED", "LOST_RACE"]

        async with _claim_factory() as verify_session:
            final_task = await verify_session.get(EditorialTask, task_id)
            assert final_task is not None
            assert final_task.status != TaskStatus.FAILED
            assert final_task.status == TaskStatus.COMPLETED
