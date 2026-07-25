"""Tests for services.telegram_notifier.send_editorial_card (Phase 14 M3).

Pure unit tier - no real Postgres, no real Telegram call in either dry-run or live mode. `Bot`
is a plain AsyncMock; `bot.send_message` is asserted called/not-called directly.
"""
from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from bot.formatting import render_editorial_card
from database.models.news_event import EventCategory, NewsEvent
from schemas.content_draft import ContentDraftRead
from schemas.content_draft import ContentType as SchemaContentType
from schemas.editorial_inbox import EditorialInboxCard
from services.telegram_notifier import send_editorial_card


def _draft(
    *, title: str | None = "Example title", body: str | None = "Example body", hashtags: list[str] | None = None
) -> ContentDraftRead:
    now = datetime.now(timezone.utc)
    return ContentDraftRead(
        id=uuid4(),
        task_id=uuid4(),
        type=SchemaContentType.POST,
        title=title,
        body=body,
        hashtags=hashtags if hashtags is not None else ["#example", "#news"],
        version=1,
        status="draft",
        created_at=now,
        updated_at=now,
    )


def _event(*, url: str | None = "https://example.com/story") -> NewsEvent:
    return NewsEvent(
        id=uuid4(),
        source_id=uuid4(),
        title="Example news title",
        summary=None,
        content="Example content",
        url=url,
        category=EventCategory.AI,
        published_at=datetime.now(timezone.utc),
        hash=f"notifier-test-{uuid4()}",
    )


@pytest.mark.asyncio
async def test_dry_run_never_calls_send_message_and_returns_not_sent() -> None:
    bot = AsyncMock()
    draft = _draft()
    event = _event()

    outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=True)

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.chat_id == 123456789


@pytest.mark.asyncio
async def test_dry_run_rendered_html_matches_render_editorial_card_directly() -> None:
    """Non-tautological: computed independently via the same, real, unmodified
    render_editorial_card() + EditorialInboxCard construction, not merely re-invoking
    send_editorial_card's own internals."""
    bot = AsyncMock()
    draft = _draft()
    event = _event()

    outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=True)

    expected_card = EditorialInboxCard(
        draft_id=draft.id, draft_title=draft.title, draft_body=draft.body,
        hashtags=draft.hashtags, draft_created_at=draft.created_at,
        news_title=event.title, news_category=event.category.value,
        news_url=event.url, news_published_at=event.published_at,
    )
    assert outcome.rendered_html == render_editorial_card(expected_card)


@pytest.mark.asyncio
async def test_dry_run_tolerates_missing_chat_id() -> None:
    """dry_run mode must not require editorial_chat_id to already be configured - inspecting a
    dry-run payload before chat_id is set is part of what dry-run exists for."""
    bot = AsyncMock()
    draft = _draft()
    event = _event()

    outcome = await send_editorial_card(bot, None, draft, event, dry_run=True)

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.chat_id is None


@pytest.mark.asyncio
async def test_live_mode_calls_send_message_with_correct_arguments() -> None:
    bot = AsyncMock()
    draft = _draft()
    event = _event()

    outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=False)

    bot.send_message.assert_called_once()
    call_args = bot.send_message.call_args
    assert call_args.args[0] == 123456789
    assert call_args.args[1] == outcome.rendered_html
    assert call_args.kwargs["parse_mode"] == ParseMode.HTML
    assert outcome.sent is True


@pytest.mark.asyncio
async def test_live_mode_requires_chat_id_configured() -> None:
    bot = AsyncMock()
    draft = _draft()
    event = _event()

    with pytest.raises(AssertionError):
        await send_editorial_card(bot, None, draft, event, dry_run=False)

    bot.send_message.assert_not_called()


@pytest.mark.asyncio
async def test_live_mode_telegram_api_error_caught_logged_not_raised() -> None:
    bot = AsyncMock()
    bot.send_message = AsyncMock(side_effect=TelegramAPIError(method="sendMessage", message="boom"))
    draft = _draft()
    event = _event()

    outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=False)

    assert outcome.sent is False
    assert outcome.rendered_html  # still populated - rendering succeeded, only the send failed


@pytest.mark.asyncio
async def test_card_too_long_error_caught_in_both_modes_never_raised() -> None:
    """A pathologically long draft_body triggers bot/formatting.py's own CardTooLongError even
    after its internal shrink loop - proven here with a real, unmodified render path, not a
    mocked one."""
    bot = AsyncMock()
    # No word boundary anywhere in the body, forcing render_editorial_card's own terminal
    # fallback path to still exceed SAFE_LIMIT - mirrors bot/formatting.py's own established
    # test technique for reaching CardTooLongError deterministically.
    draft = _draft(title="x" * 5000, body="y" * 5000)
    event = _event()

    dry_run_outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=True)
    assert dry_run_outcome.sent is False
    assert dry_run_outcome.rendered_html == ""
    bot.send_message.assert_not_called()

    live_outcome = await send_editorial_card(bot, 123456789, draft, event, dry_run=False)
    assert live_outcome.sent is False
    bot.send_message.assert_not_called()
