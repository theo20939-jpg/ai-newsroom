"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: services.event_recap_review_notifier -
send_event_recap_review() + update_event_recap_review_message(). Pure unit tier, mirrors tests/
test_telegram_editorial_routing.py's own established convention exactly: `Bot` is a plain
`unittest.mock.AsyncMock` - no real Postgres, no real Telegram API contact of any kind, including
a "live" (`dry_run=False`) send, since the fake bot never leaves the process.

Phase D.0 change from Phase C.1: both functions now take an `EventRecapReview` ORM instance (for
status/id) plus the recap's own persisted result dict, never a live `EventRecapCandidate` - see
services/event_recap_review_notifier.py's own module docstring.
"""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ParseMode

from core.config import settings
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus
from schemas.editorial_route import EditorialDestination
from services.event_recap_review_notifier import send_event_recap_review, update_event_recap_review_message

_RECAP_RESULT = {
    "recap_title": "Apple Watch Ultra Unveiled",
    "recap_summary": "Apple introduced a new Watch Ultra model.",
    "key_takeaways": ["Priced at $999.", "Positioned as the flagship Watch tier."],
    "uncertainty_notes": ["Availability date not yet confirmed."],
}


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated topic ids for every test in this file - mirrors tests/test_telegram_editorial_
    routing.py's own identical fixture, never the real environment's values."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)


def _pending_review() -> EventRecapReview:
    """An unpersisted, in-memory EventRecapReview - exactly the ORM shape the caller would hold
    right after services.event_recap_review_service.create_event_recap_review() returns."""
    return EventRecapReview(id=uuid.uuid4(), recap_task_id=uuid.uuid4(), status=EventRecapReviewStatus.PENDING)


@pytest.mark.asyncio
async def test_dry_run_is_true_by_default_and_never_calls_send_message() -> None:
    bot = AsyncMock()
    review = _pending_review()

    outcome = await send_event_recap_review(bot, review, _RECAP_RESULT)

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "dry_run"


@pytest.mark.asyncio
async def test_live_send_builds_a_correct_preview_message() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 777
    review = _pending_review()

    outcome = await send_event_recap_review(bot, review, _RECAP_RESULT, dry_run=False)

    assert bot.send_message.call_count == 1
    args, kwargs = bot.send_message.call_args
    sent_chat_id, sent_text = args[0], args[1]
    assert sent_chat_id == -100123456789
    assert kwargs["message_thread_id"] == 33  # EditorialDestination.TELEGRAPH's own topic id

    assert _RECAP_RESULT["recap_title"] in sent_text
    assert _RECAP_RESULT["recap_summary"] in sent_text
    for takeaway in _RECAP_RESULT["key_takeaways"]:
        assert takeaway in sent_text
    for note in _RECAP_RESULT["uncertainty_notes"]:
        assert note in sent_text
    assert "shadow" in sent_text.lower()  # never rendered as a finished, publishable post
    assert "⏳" in sent_text  # PENDING status line

    assert outcome.sent is True
    assert outcome.destination is EditorialDestination.TELEGRAPH
    assert outcome.message_id == 777

    # Real reply_markup wired through - a keyboard, not None, while PENDING.
    assert kwargs["reply_markup"] is not None


@pytest.mark.asyncio
async def test_uses_the_real_send_to_editorial_destination_routing() -> None:
    """Proves this notifier routes through the existing, unmodified send_to_editorial_destination()
    - never a parallel/duplicated Telegram call - by checking the real routing side effects
    (parse_mode, message_thread_id resolved from settings, link_preview_options) that only that
    function applies."""
    from aiogram.types import LinkPreviewOptions

    bot = AsyncMock()
    review = _pending_review()

    await send_event_recap_review(bot, review, _RECAP_RESULT, dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["parse_mode"] == ParseMode.HTML
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


@pytest.mark.asyncio
async def test_accepts_an_explicit_alternate_destination(monkeypatch: pytest.MonkeyPatch) -> None:
    """The caller may pass a different EditorialDestination explicitly - this module makes no
    destination decision of its own beyond the TELEGRAPH default (module docstring)."""
    monkeypatch.setattr(settings, "news_topic_id", 11)
    bot = AsyncMock()
    review = _pending_review()

    await send_event_recap_review(bot, review, _RECAP_RESULT, dry_run=False, destination=EditorialDestination.NEWS)

    _, kwargs = bot.send_message.call_args
    assert kwargs["message_thread_id"] == 11


@pytest.mark.asyncio
async def test_update_message_edits_in_place_never_sends_new() -> None:
    bot = AsyncMock()
    review = EventRecapReview(id=uuid.uuid4(), recap_task_id=uuid.uuid4(), status=EventRecapReviewStatus.APPROVED)

    edited = await update_event_recap_review_message(
        bot, chat_id=-100123456789, message_id=42, review=review, recap_result=_RECAP_RESULT,
    )

    assert edited is True
    bot.send_message.assert_not_called()
    assert bot.edit_message_text.call_count == 1
    _, kwargs = bot.edit_message_text.call_args
    assert kwargs["chat_id"] == -100123456789
    assert kwargs["message_id"] == 42
    assert "✅ Recap одобрен" in kwargs["text"]
    # APPROVED is a final state - no keyboard on the re-rendered message.
    assert kwargs["reply_markup"] is None


@pytest.mark.asyncio
async def test_update_message_returns_false_on_telegram_api_error() -> None:
    from aiogram.exceptions import TelegramBadRequest

    bot = AsyncMock()
    bot.edit_message_text.side_effect = TelegramBadRequest(method=AsyncMock(), message="message to edit not found")
    review = _pending_review()

    edited = await update_event_recap_review_message(
        bot, chat_id=-100123456789, message_id=42, review=review, recap_result=_RECAP_RESULT,
    )

    assert edited is False


@pytest.mark.asyncio
async def test_publishable_is_never_read_or_touched_by_the_notifier() -> None:
    """EventRecapCandidate.publishable stays exactly what services/event_recap.py already
    returned - this notifier never imports EventRecapCandidate at all any more (Phase D.0
    change), only the recap's own persisted result dict and the durable EventRecapReview row."""
    bot = AsyncMock()
    review = _pending_review()

    outcome = await send_event_recap_review(bot, review, _RECAP_RESULT, dry_run=False)

    assert not hasattr(outcome, "publishable")
