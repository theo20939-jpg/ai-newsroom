"""Tests for workflows.runner.WorkflowRunner - real Postgres, transaction rolled back per test.

Injects fake StepExecutor implementations to exercise retry/failure paths -
none of them call any AI provider or network endpoint.
"""
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskRead
from schemas.workflow import WorkflowStepDefinition, WorkflowType
from services import workflow_service
from workflows.errors import PermanentStepFailureError, StepExecutionError, TaskAlreadyCompletedError, TaskAlreadyRunningError
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


async def _created_task(session: AsyncSession, event: NewsEvent) -> EditorialTaskRead:
    return await workflow_service.create_task(session, event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.B)


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
