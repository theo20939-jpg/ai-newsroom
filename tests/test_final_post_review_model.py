"""Phase I.2, Part Z: FinalPostReview model/migration tests. Mirrors the shape a corresponding
EventRecapReview model test would take (no dedicated tests/test_event_recap_review_model.py exists
in this codebase - EventRecapReview's own model behavior is exercised implicitly through
tests/test_event_recap_review_service.py - this file follows the same convention but is named
explicitly per Phase I.2's own Part Z requirement)."""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.editorial_task import TaskPriority
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service


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
async def test_create_final_post_review_defaults_to_pending(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    review = FinalPostReview(content_draft_id=draft.id)
    db_session.add(review)
    await db_session.commit()
    await db_session.refresh(review)

    assert review.status == FinalPostReviewStatus.PENDING
    assert review.decided_at is None
    assert review.decided_by_telegram_user_id is None
    assert review.telegram_chat_id is None
    assert review.telegram_message_id is None
    assert review.telegram_thread_id is None
    assert review.created_at is not None
    assert review.updated_at is not None


@pytest.mark.asyncio
async def test_content_draft_id_is_unique(db_session: AsyncSession) -> None:
    draft = await _seed_content_draft(db_session)
    db_session.add(FinalPostReview(content_draft_id=draft.id))
    await db_session.commit()

    db_session.add(FinalPostReview(content_draft_id=draft.id))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
