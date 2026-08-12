"""Phase 22 - Telegram Editorial Routing Foundation tests.

Pure unit tier, mirroring tests/test_telegram_notifier.py's own established convention exactly:
`Bot` is a plain `unittest.mock.AsyncMock` - no real Postgres, no real Telegram API contact of any
kind, in any case, including "live" (`dry_run=False`) sends, since the fake bot never leaves the
process. `bot.send_message` is asserted called/not-called and, when called, asserted with the
exact kwargs (`message_thread_id` present vs. absent) - this is the direct regression guard for
"do not repeat the previous Telegram topic bug" (the phase brief's own §6 instruction): unlike the
Phase 11 bug (inbound topic-context propagation, a proven upstream Telegram limitation - see docs/
phase22_telegram_editorial_routing_report.md §2), this routing layer only ever sets
`message_thread_id` from *pre-configured settings*, never from an incoming Update, so that
limitation cannot recur here by construction - these tests prove the outgoing call shape directly.
"""
from unittest.mock import AsyncMock

import pytest
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramAPIError

from aiogram.types import LinkPreviewOptions

from core.config import settings
from schemas.editorial_route import EditorialDestination, parse_editorial_destination
from services.telegram_routing import RouteTarget, resolve_route, send_to_editorial_destination


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolated topic ids for every test in this file - never the real environment's values
    (which are `None` by default anyway - see core/config.py's own Phase 22 comment)."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", -100123456789)
    monkeypatch.setattr(settings, "news_topic_id", 11)
    monkeypatch.setattr(settings, "meme_topic_id", 22)
    monkeypatch.setattr(settings, "telegraph_topic_id", 33)
    monkeypatch.setattr(settings, "instagram_topic_id", 44)
    monkeypatch.setattr(settings, "reels_topic_id", 55)


# ---------------------------------------------------------------------------
# parse_editorial_destination() / resolve_route() - pure unit tests
# ---------------------------------------------------------------------------


def test_parse_editorial_destination_recognizes_all_five() -> None:
    assert parse_editorial_destination("NEWS") is EditorialDestination.NEWS
    assert parse_editorial_destination("MEME") is EditorialDestination.MEME
    assert parse_editorial_destination("TELEGRAPH") is EditorialDestination.TELEGRAPH
    assert parse_editorial_destination("INSTAGRAM") is EditorialDestination.INSTAGRAM
    assert parse_editorial_destination("REELS") is EditorialDestination.REELS


def test_parse_editorial_destination_returns_none_for_unknown_value() -> None:
    assert parse_editorial_destination("PODCAST") is None
    assert parse_editorial_destination("") is None
    assert parse_editorial_destination("news") is None  # case-sensitive, exact enum value only


def test_resolve_route_returns_none_when_chat_id_unconfigured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", None)
    assert resolve_route(EditorialDestination.NEWS) is None


def test_resolve_route_topic_id_none_is_a_valid_target_not_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """A configured chat id but an unconfigured per-destination topic id must still resolve -
    routing to the chat's own root, never treated as a configuration error."""
    monkeypatch.setattr(settings, "news_topic_id", None)
    route = resolve_route(EditorialDestination.NEWS)
    assert route == RouteTarget(chat_id=-100123456789, topic_id=None)


def test_resolve_route_maps_each_destination_to_its_own_configured_topic() -> None:
    assert resolve_route(EditorialDestination.NEWS).topic_id == 11
    assert resolve_route(EditorialDestination.MEME).topic_id == 22
    assert resolve_route(EditorialDestination.TELEGRAPH).topic_id == 33
    assert resolve_route(EditorialDestination.INSTAGRAM).topic_id == 44
    assert resolve_route(EditorialDestination.REELS).topic_id == 55


# ---------------------------------------------------------------------------
# CASE 1 - NEWS draft -> sent to NEWS topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_1_news_draft_sent_to_news_topic() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 555

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "A news post", dry_run=False)

    bot.send_message.assert_called_once_with(
        -100123456789, "A news post", parse_mode=ParseMode.HTML, message_thread_id=11, reply_markup=None,
        reply_to_message_id=None, link_preview_options=LinkPreviewOptions(is_disabled=True),
    )
    assert outcome.sent is True
    assert outcome.destination is EditorialDestination.NEWS
    assert outcome.chat_id == -100123456789
    assert outcome.topic_id == 11
    assert outcome.message_id == 555


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case G, docs/news_output_stability_forensic_report.md §8): text-only
# NEWS sends must disable the Telegram link-preview card (real, observed problem: the NINJA PULSE
# footer's own link was the only link in the message body and Telegram expanded it into a large
# preview card) - the link itself must remain fully clickable, only the preview card is disabled.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_text_only_send_disables_link_preview() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 900

    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS,
        'Post text with <a href="https://t.me/nnjvpn">NINJA PULSE. Подписаться 🥷</a>', dry_run=False,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


@pytest.mark.asyncio
async def test_link_preview_disabled_for_every_destination_not_only_news() -> None:
    """Applied unconditionally inside send_to_editorial_destination() - never gated by which
    destination is being sent to (every real text NEWS send goes through this one function)."""
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 901

    await send_to_editorial_destination(bot, EditorialDestination.MEME, "A meme idea", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


@pytest.mark.asyncio
async def test_link_preview_never_sent_when_dry_run() -> None:
    """dry_run=True never calls bot.send_message() at all - nothing to assert about kwargs, but
    explicitly confirms this fix does not accidentally introduce a live call in dry-run mode."""
    bot = AsyncMock()

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "A news post")

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "dry_run"


@pytest.mark.asyncio
async def test_photo_send_never_receives_a_link_preview_kwarg() -> None:
    """Telegram never generates a link preview for a photo caption at all - send_photo_to_
    editorial_destination() must never be touched by this fix; confirmed structurally, not just by
    absence of a visible symptom."""
    from services.telegram_routing import send_photo_to_editorial_destination

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 902

    await send_photo_to_editorial_destination(bot, EditorialDestination.NEWS, "file_id_123", "Caption text", dry_run=False)

    _, kwargs = bot.send_photo.call_args
    assert "link_preview_options" not in kwargs


@pytest.mark.asyncio
async def test_media_group_send_never_receives_a_link_preview_kwarg() -> None:
    """Same reasoning as the photo case - Telegram never generates a link preview for a
    media-group caption either; send_media_group_to_editorial_destination() must be unaffected."""
    from unittest.mock import MagicMock

    from services.telegram_routing import send_media_group_to_editorial_destination

    bot = AsyncMock()
    bot.send_media_group.return_value = [MagicMock(message_id=903), MagicMock(message_id=904)]

    await send_media_group_to_editorial_destination(
        bot, EditorialDestination.NEWS, ["fake-media-item-1", "fake-media-item-2"], dry_run=False,  # type: ignore[list-item]
    )

    _, kwargs = bot.send_media_group.call_args
    assert "link_preview_options" not in kwargs


@pytest.mark.asyncio
async def test_update_reply_send_still_disables_link_preview() -> None:
    """UPDATE reply-threading is unaffected by this fix - reply_to_message_id and link-preview
    suppression are independent parameters on the same call."""
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 905

    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "An update reply post", dry_run=False, reply_to_message_id=999,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_to_message_id"] == 999
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


@pytest.mark.asyncio
async def test_source_button_reply_markup_unaffected_by_link_preview_fix() -> None:
    from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    bot = AsyncMock()
    bot.send_message.return_value.message_id = 906
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔗 Источник", url="https://example.com/article")]]
    )

    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "A news post", dry_run=False, reply_markup=keyboard,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_markup"] is keyboard
    assert kwargs["link_preview_options"] == LinkPreviewOptions(is_disabled=True)


# ---------------------------------------------------------------------------
# CASE 2 - MEME draft -> sent to MEME topic
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_2_meme_draft_sent_to_meme_topic() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 556

    outcome = await send_to_editorial_destination(bot, EditorialDestination.MEME, "A meme idea", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["message_thread_id"] == 22
    assert outcome.sent is True
    assert outcome.destination is EditorialDestination.MEME
    assert outcome.topic_id == 22


# ---------------------------------------------------------------------------
# CASE 3 - unknown destination -> safe failure, no Telegram call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_3_unknown_destination_string_never_calls_telegram() -> None:
    bot = AsyncMock()

    outcome = await send_to_editorial_destination(bot, "PODCAST", "Some text", dry_run=False)

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "unknown_destination"
    assert outcome.destination is None


@pytest.mark.asyncio
async def test_case_3_unconfigured_destination_never_calls_telegram(monkeypatch: pytest.MonkeyPatch) -> None:
    """A recognized destination is still a safe failure, never a Telegram call, when the chat id
    itself is not configured."""
    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", None)
    bot = AsyncMock()

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "Some text", dry_run=False)

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "unconfigured_destination"


# ---------------------------------------------------------------------------
# CASE 4 - forum topic delivery -> message_thread_id included
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_4_forum_topic_delivery_includes_message_thread_id() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 1

    await send_to_editorial_destination(bot, EditorialDestination.TELEGRAPH, "Long-form draft", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["message_thread_id"] == 33


# ---------------------------------------------------------------------------
# CASE 5 - normal chat delivery -> message_thread_id absent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_5_normal_chat_delivery_omits_message_thread_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """A destination whose own topic id is not configured sends to the chat's root - the outgoing
    call's `message_thread_id` must be `None` (functionally identical to omitting it - aiogram's
    own `Bot.send_message()` already defaults this parameter to `None`), never a real topic id,
    matching the phase brief's own §6 "if destination is normal chat: send without thread ID"
    requirement exactly."""
    monkeypatch.setattr(settings, "news_topic_id", None)
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 1

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "A news post", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["message_thread_id"] is None
    assert outcome.topic_id is None
    assert outcome.sent is True


# ---------------------------------------------------------------------------
# CASE 6 - production safety: no real Telegram API call, in any mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_case_6_dry_run_default_never_calls_telegram() -> None:
    """dry_run defaults to True (mirrors send_editorial_card's own safe default) - a caller that
    forgets to pass dry_run=False explicitly can never accidentally send a real message."""
    bot = AsyncMock()

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "A news post")

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "dry_run"
    assert outcome.chat_id == -100123456789  # target still inspectable even though nothing sent
    assert outcome.topic_id == 11


@pytest.mark.asyncio
async def test_case_6_fake_bot_is_never_a_real_aiogram_network_client() -> None:
    """Explicit proof this test file never constructs a real aiogram Bot (which would require
    TELEGRAM_BOT_TOKEN and could, in principle, reach the network) - every test uses AsyncMock."""
    bot = AsyncMock()
    assert not hasattr(bot, "session") or isinstance(bot, AsyncMock)
    await send_to_editorial_destination(bot, EditorialDestination.NEWS, "text", dry_run=False)
    bot.send_message.assert_called_once()
    # The mock recorded the call but performed no real I/O - AsyncMock has no network transport.


# ---------------------------------------------------------------------------
# Live-send failure handling (mirrors send_editorial_card's own error-swallowing convention)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_telegram_api_error_is_caught_and_returned_never_raised() -> None:
    bot = AsyncMock()
    bot.send_message.side_effect = TelegramAPIError(method=None, message="boom")  # type: ignore[arg-type]

    outcome = await send_to_editorial_destination(bot, EditorialDestination.NEWS, "text", dry_run=False)

    assert outcome.sent is False
    assert outcome.reason == "telegram_api_error"


# ---------------------------------------------------------------------------
# Phase 23.1Q - reply_to_message_id passthrough (docs/phase23_1p_story_memory_quotes_gate_
# report.md §"newly-discovered items": worker/content_cycle.py already resolved a real reply
# target for router-mode NEWS deliveries, but this module had no parameter to carry it, so it was
# silently dropped - closing that gap). This module makes no reply-routing decision of its own -
# these tests only prove the already-decided int reaches the real Telegram API call, exactly like
# reply_markup already does.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reply_to_message_id_reaches_the_real_send_message_call() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 777

    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "An update post", dry_run=False, reply_to_message_id=555,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_to_message_id"] == 555


@pytest.mark.asyncio
async def test_reply_to_message_id_defaults_to_none_every_existing_caller_unaffected() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 778

    await send_to_editorial_destination(bot, EditorialDestination.NEWS, "A normal post", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_to_message_id"] is None


@pytest.mark.asyncio
async def test_reply_to_message_id_reaches_the_real_send_photo_call() -> None:
    from aiogram.types import BufferedInputFile

    from services.telegram_routing import send_photo_to_editorial_destination

    bot = AsyncMock()
    bot.send_photo.return_value.message_id = 779
    photo = BufferedInputFile(b"fake-bytes", filename="x.jpg")

    await send_photo_to_editorial_destination(
        bot, EditorialDestination.NEWS, photo, "caption", dry_run=False, reply_to_message_id=555,
    )

    _, kwargs = bot.send_photo.call_args
    assert kwargs["reply_to_message_id"] == 555


@pytest.mark.asyncio
async def test_reply_to_message_id_never_sent_when_dry_run() -> None:
    """A resolved reply target must never leak into a real API call while dry_run - mirrors every
    other field's own established dry-run safety guarantee."""
    bot = AsyncMock()

    outcome = await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "text", dry_run=True, reply_to_message_id=555,
    )

    bot.send_message.assert_not_called()
    assert outcome.sent is False
    assert outcome.reason == "dry_run"
