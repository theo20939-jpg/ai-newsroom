"""Phase 19 M11: services.media_ranking's cross-event story-aware reuse queries - a real,
migrated-database integration test (runtime table-existence skip, mirrors tests/
test_editorial_planning_persistence_integration.py's own established pattern).
"""
from __future__ import annotations

import uuid

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_media_item import ContentDraftMediaItem
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from schemas.image_candidate import ImageDiscoveryMethod
from services.media_ranking import find_story_reused_image_signatures, find_story_reused_video_urls


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


async def _require_tables(session: AsyncSession) -> None:
    required = ("stories", "news_event_story_links", "image_candidates", "content_draft_media_items")
    for table in required:
        if not await _table_exists(session, table):
            pytest.skip(
                f"{table} table not present on this DB - run this test against a disposable DB "
                "that has had 'alembic upgrade head' applied."
            )


async def _make_story_with_events(db_session: AsyncSession, *, event_count: int) -> tuple[Story, list[NewsEvent]]:
    source = NewsSource(id=uuid.uuid4(), name=f"reuse-test-{uuid.uuid4()}", type=SourceType.RSS, active=True)
    db_session.add(source)
    await db_session.flush()

    events = []
    for i in range(event_count):
        event = NewsEvent(
            id=uuid.uuid4(), source_id=source.id, title=f"Event {i}", category=EventCategory.AI,
            hash=f"h-{uuid.uuid4()}",
        )
        db_session.add(event)
        events.append(event)
    await db_session.flush()

    story = Story(
        id=uuid.uuid4(), title=events[0].title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=events[0].id, event_count=event_count,
    )
    db_session.add(story)
    await db_session.flush()

    for event in events:
        db_session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type="new_story", match_score=1.0)
        )
    await db_session.flush()
    return story, events


@pytest.mark.asyncio
async def test_finds_image_signatures_from_other_events_in_the_same_story(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    story, events = await _make_story_with_events(db_session, event_count=2)

    db_session.add(
        ImageCandidateRecord(
            id=uuid.uuid4(), news_event_id=events[0].id, candidate_id="c-1", source_type=SourceType.RSS,
            discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE.value,
            sha256="a" * 64, perceptual_hash="0000000000000000",
        )
    )
    await db_session.flush()

    exact, perceptual = await find_story_reused_image_signatures(
        db_session, story_id=story.id, exclude_event_id=events[1].id
    )
    assert "a" * 64 in exact
    assert "0000000000000000" in perceptual


@pytest.mark.asyncio
async def test_excludes_signatures_from_the_event_itself(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    story, events = await _make_story_with_events(db_session, event_count=1)

    db_session.add(
        ImageCandidateRecord(
            id=uuid.uuid4(), news_event_id=events[0].id, candidate_id="c-1", source_type=SourceType.RSS,
            discovery_method=ImageDiscoveryMethod.OPEN_GRAPH_IMAGE.value, sha256="b" * 64,
        )
    )
    await db_session.flush()

    exact, _ = await find_story_reused_image_signatures(
        db_session, story_id=story.id, exclude_event_id=events[0].id
    )
    assert exact == set()  # the only image belongs to the excluded (current) event itself


@pytest.mark.asyncio
async def test_finds_video_urls_from_other_events_in_the_same_story(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    story, events = await _make_story_with_events(db_session, event_count=2)

    db_session.add(
        ContentDraftMediaItem(
            id=uuid.uuid4(), event_id=events[0].id, media_type="video", discovery_method="html_video_tag",
            remote_url="https://cdn.example.com/clip.mp4", platform="direct_hosted", validation_status="valid",
        )
    )
    await db_session.flush()

    urls = await find_story_reused_video_urls(db_session, story_id=story.id, exclude_event_id=events[1].id)
    assert "https://cdn.example.com/clip.mp4" in urls


@pytest.mark.asyncio
async def test_story_with_only_the_excluded_event_returns_empty(db_session: AsyncSession) -> None:
    await _require_tables(db_session)
    story, events = await _make_story_with_events(db_session, event_count=1)

    exact, perceptual = await find_story_reused_image_signatures(
        db_session, story_id=story.id, exclude_event_id=events[0].id
    )
    assert exact == set()
    assert perceptual == []
