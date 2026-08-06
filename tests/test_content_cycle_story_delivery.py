"""Phase 18.10 M3: worker.content_cycle's story-linked Telegram reply/delivery wiring.

Reuses tests/test_content_worker_cycle.py's own established fixtures (factory/test_source/
_isolated_freshness_window/_make_event/_make_completed_news_analysis_task) via import - a
Phase-18.10-scoped extension, kept in its own file to avoid growing that already-large module.

No real Telegram send anywhere in this file - `bot` is always a plain AsyncMock, exactly like
every other content_cycle test in this codebase. Every test explicitly pins
image_editorial_preview_enabled/content_generation_dry_run via monkeypatch rather than relying on
this environment's ambient .env values (which are non-default in this dev environment - see
docs/phase18_10_editorial_intelligence_report.md's own disclosed test-environment notes) - the
same explicit-override discipline tests/test_content_worker_cycle.py's own
_isolated_freshness_window fixture already established.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from core.config import settings
from database.models.news_event import EventCategory, NewsEvent
from database.models.story import Story
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType, StoryTelegramDelivery
from services.telegram_notifier import NotificationOutcome
from tests.test_content_worker_cycle import (  # noqa: F401,F811 - fixtures reused via import
    _make_completed_news_analysis_task,
    _make_event,
    _real_capability_registry,
    _isolated_freshness_window,
    factory,
    test_source,
)
from worker.content_cycle import run_content_cycle

_MIGRATION_SKIP_REASON = (
    "Requires Alembic migrations c2bc6affb100/0fac25b59455 (stories/news_event_story_links/"
    "content_draft_story_links/story_telegram_deliveries tables) to be applied first - Phase "
    "18.10 ships these unapplied by explicit instruction (design-only). Remove this skip once "
    "applied."
)


async def _make_story_linked_draft(
    factory: async_sessionmaker[AsyncSession], test_source, *, is_story_update: bool,  # noqa: F811
) -> tuple[Story, NewsEvent]:
    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)
        story = Story(
            id=uuid4(), title=event.title, category=EventCategory.AI, entities=[], keywords=[],
            topic_bucket="product", first_event_id=event.id, event_count=1,
        )
        session.add(story)
        await session.flush()
        await session.commit()
    return story, event


@pytest.fixture
def _deterministic_delivery_settings(monkeypatch: pytest.MonkeyPatch):
    """Forces the plain send_editorial_card path and live (non-dry-run) sends, regardless of
    this environment's own ambient .env values - so this file's assertions are never at the
    mercy of local configuration drift."""
    monkeypatch.setattr(settings, "image_editorial_preview_enabled", False)
    monkeypatch.setattr(settings, "content_generation_dry_run", False)
    monkeypatch.setattr(settings, "editorial_chat_id", 123456789)


@pytest.mark.asyncio
async def test_off_mode_never_queries_story_link_or_records_delivery(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None,
) -> None:
    """The default, byte-identical-to-pre-18.10 path - story_memory_mode == "off" must never
    attempt a ContentDraftStoryLink lookup or a delivery record, and must behave exactly as
    before (send happens, notified counts as usual). Does not need the Phase 18.10 migration at
    all, since the new code path is never entered."""
    assert settings.story_memory_mode == "off"  # this test's own precondition, not just an assumption

    async with factory() as session:
        event = await _make_event(session, test_source, published_at=datetime.now(timezone.utc))
        await _make_completed_news_analysis_task(session, event, score=settings.content_generation_min_score)

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()

    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=42)),
    ) as mock_notify, patch("worker.content_cycle.record_delivery") as mock_record_delivery:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()
    # reply_to_message_id must be explicitly None (a normal, non-story-linked send), never
    # simply omitted - proves the new parameter is wired through even in the inert/off case.
    assert mock_notify.call_args.kwargs["reply_to_message_id"] is None
    mock_record_delivery.assert_not_called()
    assert result.completed == 1
    assert result.notified == 1
    assert result.story_fail_closed_review == 0
    assert result.story_delivery_persistence_failed == 0


@pytest.mark.skip(reason=_MIGRATION_SKIP_REASON)
@pytest.mark.asyncio
async def test_story_update_with_existing_root_replies_to_it(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An update whose story already has a SENT root delivery must be sent as a reply to that
    root message's telegram_message_id - end to end, through the real create_from_result() ->
    ContentDraftStoryLink creation -> determine_reply_target() -> send_editorial_card() chain."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        session.add(
            StoryTelegramDelivery(
                id=uuid4(), story_id=story.id, content_draft_id=uuid4(), telegram_chat_id=123456789,
                telegram_message_id=999, reply_to_message_id=None, delivery_type=DeliveryType.ROOT,
                delivery_status=DeliveryStatus.SENT, idempotency_key=f"root-{uuid4()}",
                sent_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch(
        "worker.content_cycle.send_editorial_card",
        new=AsyncMock(return_value=NotificationOutcome(chat_id=1, rendered_html="<html>", sent=True, message_id=1001)),
    ) as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_called_once()
    assert mock_notify.call_args.kwargs["reply_to_message_id"] == 999
    assert result.story_fail_closed_review == 0


@pytest.mark.skip(reason=_MIGRATION_SKIP_REASON)
@pytest.mark.asyncio
async def test_story_update_with_no_root_fails_closed_never_sends(
    factory: async_sessionmaker[AsyncSession], test_source, _isolated_freshness_window: None,  # noqa: F811
    _deterministic_delivery_settings: None, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An update whose story has NO root delivery must never be sent as a standalone post - the
    explicit, non-negotiable fail-closed requirement."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")
    from database.models.story_link import NewsEventStoryLink
    from services.story_memory import STORY_UPDATE

    story, event = await _make_story_linked_draft(factory, test_source, is_story_update=True)
    async with factory() as session:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=STORY_UPDATE, match_score=0.7)
        )
        await session.commit()

    _gateway, registry = _real_capability_registry()
    fake_bot = AsyncMock()
    with patch("worker.content_cycle.send_editorial_card") as mock_notify:
        result = await run_content_cycle(registry, fake_bot, session_factory=factory)

    mock_notify.assert_not_called()
    assert result.story_fail_closed_review == 1
    assert result.notified == 0
