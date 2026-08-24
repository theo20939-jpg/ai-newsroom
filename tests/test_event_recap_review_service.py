"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: services.event_recap_review_service -
persistence + decision idempotency. Real Postgres (db_session fixture, rolled back per test).
Mirrors tests/test_telegraph_article_review_service.py's own established shape exactly.
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.event_recap_review import EventRecapReviewStatus
from services.event_recap_review_service import (
    create_event_recap_review,
    get_event_recap_review,
    get_event_recap_review_for_task,
    record_telegram_delivery,
    set_decision,
)

_SERVICE_SOURCE = Path("services/event_recap_review_service.py").read_text(encoding="utf-8")


async def _make_recap_task(db_session: AsyncSession) -> EditorialTask:
    """A minimal, real EditorialTask row to satisfy the FK - the review service itself never
    inspects the task's own workflow content, only its id."""
    from database.models.news_event import EventCategory, NewsEvent
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name=f"Recap review test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Recap review test event", content="x", category=EventCategory.AI,
        hash=f"recap-review-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    task = EditorialTask(
        event_id=event.id, priority=TaskPriority.C,
        workflow={"workflow_name": "EVENT_RECAP", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()
    return task


@pytest.mark.asyncio
async def test_create_event_recap_review_persists_pending(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)

    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    assert review.status == EventRecapReviewStatus.PENDING
    assert review.decided_at is None
    assert review.recap_task_id == task.id


@pytest.mark.asyncio
async def test_create_event_recap_review_is_idempotent_per_task(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)

    first = await create_event_recap_review(db_session, recap_task_id=task.id)
    second = await create_event_recap_review(db_session, recap_task_id=task.id)

    assert first.id == second.id


@pytest.mark.asyncio
async def test_get_event_recap_review_for_task(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    created = await create_event_recap_review(db_session, recap_task_id=task.id)

    found = await get_event_recap_review_for_task(db_session, task.id)

    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_get_event_recap_review_by_id(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    created = await create_event_recap_review(db_session, recap_task_id=task.id)

    found = await get_event_recap_review(db_session, created.id)

    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_get_event_recap_review_missing_returns_none(db_session: AsyncSession) -> None:
    found = await get_event_recap_review(db_session, uuid.uuid4())
    assert found is None


@pytest.mark.asyncio
async def test_approve_sets_status_and_decider(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    updated = await set_decision(
        db_session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=111,
    )

    assert updated is not None
    assert updated.status == EventRecapReviewStatus.APPROVED
    assert updated.decided_at is not None
    assert updated.decided_by_telegram_user_id == 111


@pytest.mark.asyncio
async def test_needs_revision_sets_status(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    updated = await set_decision(
        db_session, review.id, EventRecapReviewStatus.NEEDS_REVISION, decided_by_user_id=111,
    )

    assert updated is not None
    assert updated.status == EventRecapReviewStatus.NEEDS_REVISION


@pytest.mark.asyncio
async def test_decision_is_immutable_once_final(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    approved = await set_decision(
        db_session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=111,
    )
    flipped = await set_decision(
        db_session, review.id, EventRecapReviewStatus.NEEDS_REVISION, decided_by_user_id=222,
    )

    assert approved is not None and flipped is not None
    assert flipped.status == EventRecapReviewStatus.APPROVED  # unchanged - repeat callback no-op
    assert flipped.decided_by_telegram_user_id == 111  # original decider preserved


@pytest.mark.asyncio
async def test_set_decision_nonexistent_review_fails_safely(db_session: AsyncSession) -> None:
    result = await set_decision(
        db_session, uuid.uuid4(), EventRecapReviewStatus.APPROVED, decided_by_user_id=111,
    )
    assert result is None


@pytest.mark.asyncio
async def test_record_telegram_delivery(db_session: AsyncSession) -> None:
    task = await _make_recap_task(db_session)
    review = await create_event_recap_review(db_session, recap_task_id=task.id)

    updated = await record_telegram_delivery(
        db_session, review.id, chat_id=-100123, message_id=555, thread_id=7,
    )

    assert updated is not None
    assert updated.telegram_chat_id == -100123
    assert updated.telegram_message_id == 555
    assert updated.telegram_thread_id == 7


@pytest.mark.asyncio
async def test_record_telegram_delivery_nonexistent_review_returns_none(db_session: AsyncSession) -> None:
    result = await record_telegram_delivery(
        db_session, uuid.uuid4(), chat_id=-100123, message_id=555, thread_id=None,
    )
    assert result is None


# ---------------------------------------------------------------------------------------------
# Cost/publish boundary (structural)
# ---------------------------------------------------------------------------------------------


def test_no_llm_gateway_or_telegram_call_in_service_source() -> None:
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "WorkflowRunner", "aiogram",
        "bot.send", "send_to_editorial_destination", "publishable", "ContentDraft",
    ):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected reference: {forbidden}"
