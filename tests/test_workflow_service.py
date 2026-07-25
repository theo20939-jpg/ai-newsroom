"""Tests for services.workflow_service - real Postgres, transaction rolled back per test."""
from uuid import UUID, uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from workflows.errors import (
    DuplicateActiveTaskError,
    NewsEventNotFoundError,
    TaskNotFoundError,
    UnknownWorkflowTypeError,
)


def _command(
    event_id: UUID, workflow_type: WorkflowType = WorkflowType.NEWS_ANALYSIS, priority: TaskPriority = TaskPriority.B
) -> EditorialTaskCreate:
    return EditorialTaskCreate(event_id=event_id, workflow_type=workflow_type, priority=priority)


@pytest.mark.asyncio
async def test_create_task_succeeds_for_a_real_news_event(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await workflow_service.create_task(db_session, _command(real_news_event.id))

    assert task.event_id == real_news_event.id
    assert task.status == TaskStatus.CREATED
    assert task.priority == TaskPriority.B
    assert task.retry_count == 0
    assert task.current_step == "research"


@pytest.mark.asyncio
async def test_create_task_missing_event_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NewsEventNotFoundError):
        await workflow_service.create_task(db_session, _command(uuid4()))


@pytest.mark.asyncio
async def test_create_task_unknown_workflow_type_raises(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    with pytest.raises(UnknownWorkflowTypeError):
        await workflow_service.create_task(
            db_session, _command(real_news_event.id, workflow_type=WorkflowType.DAILY_DIGEST)
        )


@pytest.mark.asyncio
async def test_duplicate_active_task_raises(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    await workflow_service.create_task(db_session, _command(real_news_event.id))

    with pytest.raises(DuplicateActiveTaskError):
        await workflow_service.create_task(db_session, _command(real_news_event.id, priority=TaskPriority.A))


@pytest.mark.asyncio
@pytest.mark.parametrize("prior_status", [TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.COMPLETED, TaskStatus.FAILED])
async def test_duplicate_task_blocked_regardless_of_prior_status(
    db_session: AsyncSession, real_news_event: NewsEvent, prior_status: TaskStatus
) -> None:
    """Phase 15 M0's own documented gap: 108 NewsEvent rows in production had a second
    NEWS_ANALYSIS task created after the first had already reached a terminal status
    (COMPLETED/FAILED), because the old duplicate check only looked at CREATED/RUNNING.
    A second create_task() call for the same (event, workflow_type) must be blocked no
    matter what status the existing task is in - mirrors the already-established,
    already-tested CONTENT_GENERATION-side contract in
    tests/test_content_worker_cycle.py::test_duplicate_content_generation_sibling_excludes_regardless_of_status."""
    first = await workflow_service.create_task(db_session, _command(real_news_event.id))
    persisted = await db_session.get(EditorialTask, first.id)
    assert persisted is not None
    persisted.status = prior_status
    await db_session.commit()

    with pytest.raises(DuplicateActiveTaskError):
        await workflow_service.create_task(db_session, _command(real_news_event.id, priority=TaskPriority.A))


@pytest.mark.asyncio
async def test_different_workflow_type_for_same_event_is_allowed(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    await workflow_service.create_task(db_session, _command(real_news_event.id))
    task2 = await workflow_service.create_task(
        db_session, _command(real_news_event.id, workflow_type=WorkflowType.CONTENT_GENERATION)
    )

    assert task2.event_id == real_news_event.id


@pytest.mark.asyncio
async def test_get_task_returns_created_task(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    created = await workflow_service.create_task(db_session, _command(real_news_event.id))

    fetched = await workflow_service.get_task(db_session, created.id)

    assert fetched == created


@pytest.mark.asyncio
async def test_get_task_missing_raises(db_session: AsyncSession) -> None:
    with pytest.raises(TaskNotFoundError):
        await workflow_service.get_task(db_session, uuid4())
