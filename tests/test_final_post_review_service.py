"""Phase I.2: services.final_post_review_service tests. Mirrors tests/test_event_recap_review_
service.py's own established shape exactly, adapted for FinalPostReview."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import TaskPriority
from database.models.final_post_review import FinalPostReviewStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.final_post_review_service import (
    create_final_post_review,
    get_final_post_review,
    get_final_post_review_for_draft,
    record_telegram_delivery,
    set_decision,
)


async def _seed_content_draft(session: AsyncSession) -> ContentDraft:
    source = NewsSource(name="Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid.uuid4()}.xml", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(source_id=source.id, title="T", content="B", category=EventCategory.AI, hash=f"h-{uuid.uuid4()}")
    session.add(event)
    await session.flush()
    task_read = await workflow_service.create_task(
        session, EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.FINAL_POST_AUTHORING, priority=TaskPriority.C),
    )
    draft = ContentDraft(id=uuid.uuid4(), task_id=task_read.id, type=ContentType.POST, title="T", body="B", version=1, status="draft")
    session.add(draft)
    await session.commit()
    await session.refresh(draft)
    return draft


@pytest.mark.asyncio
async def test_create_final_post_review_is_idempotent(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)

    first = await create_final_post_review(db_session, content_draft_id=draft.id)
    second = await create_final_post_review(db_session, content_draft_id=draft.id)

    assert first.id == second.id
    assert first.status == FinalPostReviewStatus.PENDING


@pytest.mark.asyncio
async def test_get_final_post_review_for_draft_finds_the_row(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    created = await create_final_post_review(db_session, content_draft_id=draft.id)

    found = await get_final_post_review_for_draft(db_session, draft.id)

    assert found is not None
    assert found.id == created.id


@pytest.mark.asyncio
async def test_get_final_post_review_for_draft_returns_none_when_absent(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    assert await get_final_post_review_for_draft(db_session, draft.id) is None


@pytest.mark.asyncio
async def test_get_final_post_review_by_id(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    created = await create_final_post_review(db_session, content_draft_id=draft.id)

    found = await get_final_post_review(db_session, created.id)

    assert found is not None and found.id == created.id


@pytest.mark.asyncio
async def test_get_final_post_review_returns_none_for_unknown_id(db_session: AsyncSession) -> None:
    """PRESENTATION RECOVERY (2026-09-02) bugfix: this test previously used `database.session.
    async_session_factory` directly - the real dev/production database (`settings.database_url`),
    bypassing the `db_session` fixture every sibling test in this file correctly uses (`tests/
    conftest.py`'s isolated, rolled-back-at-teardown `ai_newsroom_test` connection). Surfaced by
    this phase's own additive migration: the real dev DB is (correctly) several revisions behind
    `ai_newsroom_test`, so a SELECT including this phase's new columns failed against it with
    `UndefinedColumnError` - a pre-existing test-isolation defect, not a Presentation Recovery
    regression, fixed here to match this file's own already-correct established convention."""
    found = await get_final_post_review(db_session, uuid.uuid4())
    assert found is None


@pytest.mark.asyncio
async def test_record_telegram_delivery_sets_message_2_metadata(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    review = await create_final_post_review(db_session, content_draft_id=draft.id)

    updated = await record_telegram_delivery(db_session, review.id, chat_id=-100123, message_id=502, thread_id=33)

    assert updated is not None
    assert updated.telegram_chat_id == -100123
    assert updated.telegram_message_id == 502
    assert updated.telegram_thread_id == 33


@pytest.mark.asyncio
async def test_record_telegram_delivery_returns_none_for_unknown_review(db_session: AsyncSession) -> None:
    assert await record_telegram_delivery(db_session, uuid.uuid4(), chat_id=1, message_id=1, thread_id=None) is None


@pytest.mark.asyncio
async def test_set_decision_approve_for_publication(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    review = await create_final_post_review(db_session, content_draft_id=draft.id)

    updated = await set_decision(
        db_session, review.id, FinalPostReviewStatus.APPROVED_FOR_PUBLICATION, decided_by_user_id=42,
    )

    assert updated is not None
    assert updated.status == FinalPostReviewStatus.APPROVED_FOR_PUBLICATION
    assert updated.decided_at is not None
    assert updated.decided_by_telegram_user_id == 42


@pytest.mark.asyncio
async def test_set_decision_needs_revision(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    review = await create_final_post_review(db_session, content_draft_id=draft.id)

    updated = await set_decision(db_session, review.id, FinalPostReviewStatus.NEEDS_REVISION, decided_by_user_id=42)

    assert updated is not None
    assert updated.status == FinalPostReviewStatus.NEEDS_REVISION


@pytest.mark.asyncio
async def test_set_decision_is_immutable_once_final(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    review = await create_final_post_review(db_session, content_draft_id=draft.id)

    await set_decision(db_session, review.id, FinalPostReviewStatus.APPROVED_FOR_PUBLICATION, decided_by_user_id=1)
    second = await set_decision(db_session, review.id, FinalPostReviewStatus.NEEDS_REVISION, decided_by_user_id=2)

    assert second is not None
    assert second.status == FinalPostReviewStatus.APPROVED_FOR_PUBLICATION  # never flips
    assert second.decided_by_telegram_user_id == 1  # first decider preserved


@pytest.mark.asyncio
async def test_set_decision_returns_none_for_unknown_review(db_session: AsyncSession) -> None:
    result = await set_decision(
        db_session, uuid.uuid4(), FinalPostReviewStatus.APPROVED_FOR_PUBLICATION, decided_by_user_id=1,
    )
    assert result is None


@pytest.mark.asyncio
async def test_one_content_draft_maps_to_at_most_one_review_row(db_session: AsyncSession) -> None:
    """Part N: one ContentDraft -> max one FinalPostReview - repeated creation calls never
    produce a second row (service-level duplicate lookup, on top of the DB's own unique
    constraint)."""
    draft = await _seed_content_draft(db_session)

    for _ in range(3):
        await create_final_post_review(db_session, content_draft_id=draft.id)

    from sqlalchemy import func, select

    from database.models.final_post_review import FinalPostReview

    count = (
        await db_session.execute(
            select(func.count()).select_from(FinalPostReview).where(FinalPostReview.content_draft_id == draft.id)
        )
    ).scalar_one()
    assert count == 1
