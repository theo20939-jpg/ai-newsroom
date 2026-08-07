"""Phase 19 M7: services.story_context.build_story_timeline() - a real, migrated-database
integration test (like tests/test_editorial_planning_persistence_integration.py, this skips at
runtime rather than via a static marker when the Phase 18.10/19 tables it needs are not present -
see that file's own docstring for why: this branch's real dev DB does not yet have the Phase
18.10 story-memory tables applied either, since it predates migration c2bc6affb100 in the chain).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.story_context import build_story_timeline


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


async def _require_story_tables(session: AsyncSession) -> None:
    if not await _table_exists(session, "stories") or not await _table_exists(session, "news_event_story_links"):
        pytest.skip(
            "stories/news_event_story_links tables not present on this DB - migration "
            "c2bc6affb100 (Phase 18.10) ships unapplied to the real DB; run this test against a "
            "disposable DB that has had 'alembic upgrade head' applied."
        )


@pytest.mark.asyncio
async def test_timeline_orders_by_published_at_with_collected_at_fallback(db_session: AsyncSession) -> None:
    await _require_story_tables(db_session)

    source = NewsSource(id=uuid.uuid4(), name="Source A", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()

    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    # Deliberately inserted out of chronological order - the timeline must still sort correctly.
    event_late = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="Second real development", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=base + timedelta(hours=5), collected_at=base + timedelta(hours=5),
    )
    event_early = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="Company launches new product", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=base, collected_at=base,
    )
    # No published_at - must fall back to collected_at for ordering.
    event_no_published = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="Third real development", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=None, collected_at=base + timedelta(hours=10),
    )
    db_session.add_all([event_late, event_early, event_no_published])
    await db_session.flush()

    story = Story(
        id=uuid.uuid4(), title=event_early.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=event_early.id, event_count=3,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add_all(
        [
            NewsEventStoryLink(news_event_id=event_early.id, story_id=story.id, match_type="new_story", match_score=1.0),
            NewsEventStoryLink(news_event_id=event_late.id, story_id=story.id, match_type="story_update", match_score=0.7),
            NewsEventStoryLink(
                news_event_id=event_no_published.id, story_id=story.id, match_type="supporting_source", match_score=0.6,
            ),
        ]
    )
    await db_session.flush()

    timeline = await build_story_timeline(db_session, story.id)

    assert [e.event_id for e in timeline] == [event_early.id, event_late.id, event_no_published.id]
    assert timeline[0].delta == "new_story"
    assert timeline[1].delta == "new_information"
    assert timeline[2].delta == "corroboration"


@pytest.mark.asyncio
async def test_introduced_and_confirmed_facts_are_relative_to_running_history(db_session: AsyncSession) -> None:
    await _require_story_tables(db_session)

    source = NewsSource(id=uuid.uuid4(), name="Source B", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()

    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    event_1 = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="Acme launches new product line", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=base, collected_at=base,
    )
    event_2 = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="Acme new product line adds enterprise features",
        category=EventCategory.AI, hash=f"h-{uuid.uuid4()}",
        published_at=base + timedelta(hours=3), collected_at=base + timedelta(hours=3),
    )
    db_session.add_all([event_1, event_2])
    await db_session.flush()

    story = Story(
        id=uuid.uuid4(), title=event_1.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=event_1.id, event_count=2,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add_all(
        [
            NewsEventStoryLink(news_event_id=event_1.id, story_id=story.id, match_type="new_story", match_score=1.0),
            NewsEventStoryLink(news_event_id=event_2.id, story_id=story.id, match_type="story_update", match_score=0.7),
        ]
    )
    await db_session.flush()

    timeline = await build_story_timeline(db_session, story.id)

    assert timeline[0].confirmed_existing_facts == []  # nothing preceded the first event
    assert "new" in timeline[0].introduced_new_facts
    # the second event shares "acme"/"new"/"product"/"line" with the first, and introduces
    # "enterprise"/"features" that were not seen before.
    assert "enterprise" in timeline[1].introduced_new_facts
    assert "acme" in timeline[1].confirmed_existing_facts


@pytest.mark.asyncio
async def test_already_published_and_telegram_message_id_reflect_sent_deliveries_only(
    db_session: AsyncSession,
) -> None:
    await _require_story_tables(db_session)
    if not await _table_exists(db_session, "content_draft_story_links") or not await _table_exists(
        db_session, "story_telegram_deliveries"
    ):
        pytest.skip("content_draft_story_links/story_telegram_deliveries tables not present on this DB.")

    source = NewsSource(id=uuid.uuid4(), name="Source C", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()

    base = datetime(2026, 8, 1, tzinfo=timezone.utc)
    event = NewsEvent(
        id=uuid.uuid4(), source_id=source.id, title="A real launch", category=EventCategory.AI,
        hash=f"h-{uuid.uuid4()}", published_at=base, collected_at=base,
    )
    db_session.add(event)
    await db_session.flush()

    story = Story(
        id=uuid.uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=event.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()

    db_session.add(
        NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type="new_story", match_score=1.0)
    )

    task = EditorialTask(
        id=uuid.uuid4(), event_id=event.id, status=TaskStatus.COMPLETED, priority=TaskPriority.B,
        workflow={"workflow_name": "CONTENT_GENERATION", "step_results": []},
    )
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(
        id=uuid.uuid4(), task_id=task.id, type=ContentType.POST, title="t", body="b", version=1, status="draft",
    )
    db_session.add(draft)
    await db_session.flush()
    content_draft_id = draft.id
    db_session.add(
        ContentDraftStoryLink(
            content_draft_id=content_draft_id, story_id=story.id, is_story_update=False, source_event_id=event.id,
        )
    )
    db_session.add(
        StoryTelegramDelivery(
            id=uuid.uuid4(), story_id=story.id, content_draft_id=content_draft_id, telegram_chat_id=1,
            telegram_message_id=555, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
            delivery_status=DeliveryStatus.SENT, idempotency_key=f"k-{uuid.uuid4()}", sent_at=base,
        )
    )
    await db_session.flush()

    timeline = await build_story_timeline(db_session, story.id)

    assert timeline[0].content_draft_id == content_draft_id
    assert timeline[0].already_published is True
    assert timeline[0].telegram_message_id == 555
    assert timeline[0].source_role is None  # M8 not implemented yet - must stay unknown
