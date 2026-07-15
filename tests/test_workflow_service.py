"""Tests for services.workflow_service - real Postgres, transaction rolled back per test."""
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from schemas.workflow import WorkflowType
from services import workflow_service
from workflows.errors import (
    DuplicateActiveTaskError,
    NewsEventNotFoundError,
    TaskNotFoundError,
    UnknownWorkflowTypeError,
)


@pytest.mark.asyncio
async def test_create_task_succeeds_for_a_real_news_event(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    task = await workflow_service.create_task(
        db_session, real_news_event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.B
    )

    assert task.event_id == real_news_event.id
    assert task.status == TaskStatus.CREATED
    assert task.priority == TaskPriority.B
    assert task.retry_count == 0
    assert task.current_step == "research"


@pytest.mark.asyncio
async def test_create_task_missing_event_raises(db_session: AsyncSession) -> None:
    with pytest.raises(NewsEventNotFoundError):
        await workflow_service.create_task(db_session, uuid4(), WorkflowType.NEWS_ANALYSIS, TaskPriority.B)


@pytest.mark.asyncio
async def test_create_task_unknown_workflow_type_raises(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    with pytest.raises(UnknownWorkflowTypeError):
        await workflow_service.create_task(db_session, real_news_event.id, WorkflowType.DAILY_DIGEST, TaskPriority.B)


@pytest.mark.asyncio
async def test_duplicate_active_task_raises(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    await workflow_service.create_task(db_session, real_news_event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.B)

    with pytest.raises(DuplicateActiveTaskError):
        await workflow_service.create_task(db_session, real_news_event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.A)


@pytest.mark.asyncio
async def test_different_workflow_type_for_same_event_is_allowed(
    db_session: AsyncSession, real_news_event: NewsEvent
) -> None:
    await workflow_service.create_task(db_session, real_news_event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.B)
    task2 = await workflow_service.create_task(
        db_session, real_news_event.id, WorkflowType.CONTENT_GENERATION, TaskPriority.B
    )

    assert task2.event_id == real_news_event.id


@pytest.mark.asyncio
async def test_get_task_returns_created_task(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    created = await workflow_service.create_task(
        db_session, real_news_event.id, WorkflowType.NEWS_ANALYSIS, TaskPriority.B
    )

    fetched = await workflow_service.get_task(db_session, created.id)

    assert fetched == created


@pytest.mark.asyncio
async def test_get_task_missing_raises(db_session: AsyncSession) -> None:
    with pytest.raises(TaskNotFoundError):
        await workflow_service.get_task(db_session, uuid4())
