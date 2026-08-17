"""TELEGRAPH Checkpoint 6: services.telegraph_article_review_service - persistence + decision
idempotency. Real Postgres (db_session fixture, rolled back per test).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.editorial_task import EditorialTask, TaskPriority
from database.models.telegraph_article_review import TelegraphArticleReviewStatus
from services.telegraph_article_review_service import (
    TelegraphArticleReviewService,
    create_article_review,
    get_review_for_article_task,
)
from tests.test_telegraph_article_processor import _DualGateway, _researched_proposal

_SERVICE_SOURCE = Path("services/telegraph_article_review_service.py").read_text(encoding="utf-8")


async def _make_article_task(db_session: AsyncSession) -> EditorialTask:
    """A minimal, real EditorialTask row to satisfy the FK - the review service itself never
    inspects the task's own workflow content, only its id."""
    from database.models.news_event import EventCategory, NewsEvent
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(name=f"Review test source {uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()
    event = NewsEvent(
        source_id=source.id, title="Review test event", content="x", category=EventCategory.AI,
        hash=f"review-{uuid.uuid4()}",
    )
    db_session.add(event)
    await db_session.flush()
    task = EditorialTask(
        event_id=event.id, priority=TaskPriority.C,
        workflow={"workflow_name": "TELEGRAPH_ARTICLE", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()
    return task


async def _make_proposal_id(db_session: AsyncSession) -> uuid.UUID:
    gateway = _DualGateway()
    proposal, _registry = await _researched_proposal(db_session, gateway)
    return proposal.id


@pytest.mark.asyncio
async def test_create_article_review_persists_pending(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)

    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)
    assert review.status == TelegraphArticleReviewStatus.PENDING
    assert review.decided_at is None
    assert review.article_task_id == task.id


@pytest.mark.asyncio
async def test_create_article_review_is_idempotent_per_task(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)

    first = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)
    second = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)
    assert first.id == second.id


@pytest.mark.asyncio
async def test_get_review_for_article_task(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)
    created = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)

    found = await get_review_for_article_task(db_session, task.id)
    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_approve_sets_status_and_decider(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)
    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)

    service = TelegraphArticleReviewService(db_session)
    updated = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert updated is not None
    assert updated.status == TelegraphArticleReviewStatus.APPROVED
    assert updated.decided_at is not None
    assert updated.decided_by_telegram_user_id == 111


@pytest.mark.asyncio
async def test_request_revision_sets_needs_revision(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)
    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)

    service = TelegraphArticleReviewService(db_session)
    updated = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.NEEDS_REVISION, decided_by_telegram_user_id=111,
    )
    assert updated is not None
    assert updated.status == TelegraphArticleReviewStatus.NEEDS_REVISION


@pytest.mark.asyncio
async def test_decision_is_immutable_once_final(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)
    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)

    service = TelegraphArticleReviewService(db_session)
    approved = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    flipped = await service.set_decision(
        review.id, TelegraphArticleReviewStatus.NEEDS_REVISION, decided_by_telegram_user_id=222,
    )
    assert approved is not None and flipped is not None
    assert flipped.status == TelegraphArticleReviewStatus.APPROVED  # unchanged
    assert flipped.decided_by_telegram_user_id == 111  # original decider preserved


@pytest.mark.asyncio
async def test_set_decision_nonexistent_review_fails_safely(db_session: AsyncSession) -> None:
    service = TelegraphArticleReviewService(db_session)
    result = await service.set_decision(
        uuid.uuid4(), TelegraphArticleReviewStatus.APPROVED, decided_by_telegram_user_id=111,
    )
    assert result is None


@pytest.mark.asyncio
async def test_record_telegram_delivery(db_session: AsyncSession) -> None:
    task = await _make_article_task(db_session)
    proposal_id = await _make_proposal_id(db_session)
    review = await create_article_review(db_session, article_task_id=task.id, proposal_id=proposal_id)

    service = TelegraphArticleReviewService(db_session)
    updated = await service.record_telegram_delivery(
        review.id, chat_id=-100123, message_id=555, thread_id=7,
    )
    assert updated is not None
    assert updated.telegram_chat_id == -100123
    assert updated.telegram_message_id == 555
    assert updated.telegram_thread_id == 7


# ---------------------------------------------------------------------------------------------
# Cost boundary (structural)
# ---------------------------------------------------------------------------------------------


def test_no_llm_gateway_or_telegram_call_in_service_source() -> None:
    for forbidden in (
        "LLMGateway", "call_generate", "CapabilityExecutor", "WorkflowRunner", "aiogram",
        "bot.send", "send_to_editorial_destination", "telegra.ph",
    ):
        assert forbidden not in _SERVICE_SOURCE, f"unexpected reference: {forbidden}"
