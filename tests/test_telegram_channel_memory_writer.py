"""SOCIAL-INTELLIGENCE-OPS-1, spec §61: TelegramChannelMemoryWriter tests - only writes from a
real recorded publication, resolves real canonical data through the ContentDraft/EditorialTask/
NewsEvent/ContentDraftStoryLink/Story chain, idempotent on repeated calls, and never fabricates a
field with no resolvable source."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft import ContentDraft, ContentType
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from database.models.news_event import NewsEvent
from database.models.story import Story
from database.models.telegram_channel_memory import StoryRole
from services.telegram_channel_memory_writer import write_channel_memory_from_final_post_review


async def _make_draft(db_session: AsyncSession, event: NewsEvent, *, title: str = "Test headline") -> ContentDraft:
    task = EditorialTask(event_id=event.id, priority=TaskPriority.A, status=TaskStatus.COMPLETED)
    db_session.add(task)
    await db_session.flush()
    draft = ContentDraft(task_id=task.id, type=ContentType.POST, title=title, body="body text")
    db_session.add(draft)
    await db_session.flush()
    return draft


async def _make_review(
    db_session: AsyncSession, draft: ContentDraft, *, published: bool, message_id: int | None = 111,
) -> FinalPostReview:
    now = datetime.now(timezone.utc)
    review = FinalPostReview(
        content_draft_id=draft.id, status=FinalPostReviewStatus.APPROVED_FOR_PUBLICATION,
        decided_at=now, published_at=now if published else None,
        published_telegram_message_id=message_id if published else None,
        published_telegram_chat_id=-100123 if published else None,
    )
    db_session.add(review)
    await db_session.flush()
    return review


@pytest.mark.asyncio
async def test_no_memory_written_when_not_yet_published(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    draft = await _make_draft(db_session, real_news_event)
    review = await _make_review(db_session, draft, published=False)
    memory = await write_channel_memory_from_final_post_review(db_session, review)
    assert memory is None


@pytest.mark.asyncio
async def test_writes_real_memory_from_published_review(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    draft = await _make_draft(db_session, real_news_event, title="Real headline")
    review = await _make_review(db_session, draft, published=True, message_id=555)
    memory = await write_channel_memory_from_final_post_review(db_session, review)
    assert memory is not None
    assert memory.content_draft_id == draft.id
    assert memory.headline == "Real headline"
    assert memory.post_id == "555"
    assert memory.event_id == real_news_event.id
    assert memory.category == real_news_event.category.value
    assert memory.published_at == review.published_at
    # No resolvable source for these in the current ContentDraft/EditorialTask chain - never
    # fabricated.
    assert memory.campaign_id is None
    assert memory.presentation_type is None
    assert memory.visual_family is None


@pytest.mark.asyncio
async def test_writer_is_idempotent_on_repeated_calls(db_session: AsyncSession, real_news_event: NewsEvent) -> None:
    draft = await _make_draft(db_session, real_news_event)
    review = await _make_review(db_session, draft, published=True)
    first = await write_channel_memory_from_final_post_review(db_session, review)
    second = await write_channel_memory_from_final_post_review(db_session, review)
    assert first is not None and second is not None
    assert first.id == second.id


@pytest.mark.asyncio
async def test_story_link_resolves_story_role_and_topics_entities(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    story = Story(
        title="Story title", category=real_news_event.category, entities=["OpenAI"], keywords=["ai", "gaming"],
        topic_bucket="ai-launch", first_event_id=real_news_event.id,
    )
    db_session.add(story)
    await db_session.flush()

    draft = await _make_draft(db_session, real_news_event)
    db_session.add(ContentDraftStoryLink(
        content_draft_id=draft.id, story_id=story.id, is_story_update=True, source_event_id=real_news_event.id,
    ))
    await db_session.flush()

    review = await _make_review(db_session, draft, published=True)
    memory = await write_channel_memory_from_final_post_review(db_session, review)
    assert memory is not None
    assert memory.story_id == story.id
    assert memory.story_role == StoryRole.UPDATE
    assert memory.topics == ["ai", "gaming"]
    assert memory.entities == ["OpenAI"]


@pytest.mark.asyncio
async def test_no_story_link_leaves_story_role_and_story_id_unset(
    db_session: AsyncSession, real_news_event: NewsEvent,
) -> None:
    draft = await _make_draft(db_session, real_news_event)
    review = await _make_review(db_session, draft, published=True)
    memory = await write_channel_memory_from_final_post_review(db_session, review)
    assert memory is not None
    assert memory.story_id is None
    assert memory.story_role is None  # never guessed FIRST/UPDATE without a real link
