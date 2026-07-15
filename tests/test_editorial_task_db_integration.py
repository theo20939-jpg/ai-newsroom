"""Real-Postgres integration tests for EditorialTask persistence.

Verifies status transitions via direct SQL (not just the returned schema),
retry_count persistence, workflow JSON round-tripping, and that a rejected
rerun makes zero changes to the row.
"""
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowStepDefinition, WorkflowType
from services import workflow_service
from workflows.errors import StepExecutionError, TaskAlreadyCompletedError
from workflows.runner import WorkflowRunner


class _AlwaysSucceeds:
    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        return {}


class _FailsOnceThenSucceeds:
    def __init__(self) -> None:
        self._failed_once = False

    async def execute(self, step: WorkflowStepDefinition) -> dict[str, Any]:
        if not self._failed_once:
            self._failed_once = True
            raise StepExecutionError("transient")
        return {}


def _command(event_id) -> EditorialTaskCreate:
    return EditorialTaskCreate(event_id=event_id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)


@pytest.mark.asyncio
async def test_status_transition_is_visible_via_raw_sql(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await workflow_service.create_task(db_session, _command(real_news_event.id))

    before = await db_session.execute(
        text("SELECT status FROM editorial_tasks WHERE id = :id"), {"id": task.id}
    )
    assert before.scalar_one() == "CREATED"

    await WorkflowRunner(executor=_AlwaysSucceeds()).run(db_session, task.id)

    after = await db_session.execute(
        text("SELECT status FROM editorial_tasks WHERE id = :id"), {"id": task.id}
    )
    assert after.scalar_one() == "COMPLETED"


@pytest.mark.asyncio
async def test_workflow_json_round_trips_with_started_and_finished_timestamps(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await workflow_service.create_task(db_session, _command(real_news_event.id))
    await WorkflowRunner(executor=_AlwaysSucceeds()).run(db_session, task.id)

    persisted = await db_session.get(EditorialTask, task.id)
    assert persisted is not None
    assert persisted.workflow["workflow_name"] == "NEWS_ANALYSIS"
    assert persisted.workflow["workflow_version"] == 1
    assert persisted.workflow["iteration_count"] == 1
    assert all(
        "started_at" in step and "finished_at" in step for step in persisted.workflow["step_results"]
    )


@pytest.mark.asyncio
async def test_retry_count_persists_in_database(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    task = await workflow_service.create_task(db_session, _command(real_news_event.id))
    await WorkflowRunner(executor=_FailsOnceThenSucceeds()).run(db_session, task.id)

    result = await db_session.execute(
        text("SELECT retry_count FROM editorial_tasks WHERE id = :id"), {"id": task.id}
    )
    assert result.scalar_one() >= 1


@pytest.mark.asyncio
async def test_rerun_on_completed_task_makes_zero_changes(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await workflow_service.create_task(db_session, _command(real_news_event.id))
    await WorkflowRunner(executor=_AlwaysSucceeds()).run(db_session, task.id)

    before = await db_session.execute(
        text("SELECT status, retry_count, updated_at FROM editorial_tasks WHERE id = :id"), {"id": task.id}
    )
    before_row = before.one()

    with pytest.raises(TaskAlreadyCompletedError):
        await WorkflowRunner(executor=_AlwaysSucceeds()).run(db_session, task.id)

    after = await db_session.execute(
        text("SELECT status, retry_count, updated_at FROM editorial_tasks WHERE id = :id"), {"id": task.id}
    )
    after_row = after.one()

    assert before_row == after_row
