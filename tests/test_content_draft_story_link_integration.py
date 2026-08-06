"""Phase 18.10 M3: integration test proving ContentDraftService.create_from_result() creates a
ContentDraftStoryLink when the source NewsEvent has a NewsEventStoryLink and story_memory_mode
is enabled. Real Postgres (db_session, rolled back). Requires the Phase 18.10 M1-M3 migrations
(stories/news_event_story_links/content_draft_story_links tables) to be applied - skipped until
then, same convention as tests/test_story_memory_integration.py.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from services.content_draft_service import ContentDraftService
from services.story_memory import STORY_UPDATE

pytestmark = pytest.mark.skip(
    reason=(
        "Requires Alembic migrations c2bc6affb100/0fac25b59455 (stories/news_event_story_links/"
        "content_draft_story_links tables) to be applied first - Phase 18.10 ships these "
        "unapplied by explicit instruction (design-only). Remove this skip once applied."
    )
)


async def _make_event_with_story_link(session: AsyncSession) -> tuple[NewsEvent, Story]:
    source = NewsSource(name=f"Story Link Source {uuid4()}", type=SourceType.RSS, active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id, title=f"Story link test {uuid4()}", content="Body",
        category=EventCategory.AI, hash=f"story-link-test-{uuid4()}",
    )
    session.add(event)
    await session.flush()
    story = Story(
        id=uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    link = NewsEventStoryLink(
        news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7,
        created_at=datetime.now(timezone.utc),
    )
    session.add(link)
    await session.flush()
    return event, story


@pytest.mark.asyncio
async def test_create_from_result_creates_content_draft_story_link_when_source_event_has_one(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    event, story = await _make_event_with_story_link(db_session)

    from tests.test_content_draft_service import _run_content_generation_to_completed  # reuse fixture-style helper

    task_id, result = await _run_content_generation_to_completed(db_session, event.id)
    draft = await ContentDraftService(db_session).create_from_result(task_id, result, event_id=event.id)

    link = await db_session.get(ContentDraftStoryLink, draft.id)
    assert link is not None
    assert link.story_id == story.id
    assert link.is_story_update is True
    assert link.source_event_id == event.id
