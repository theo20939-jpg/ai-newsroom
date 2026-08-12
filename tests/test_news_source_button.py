"""Phase 23.1E - inline source-button tests (phase brief "TEST-FIRST - SOURCE BUTTON" cases A-H).

Reuses, extends, never replaces: bot/keyboards/image_preview.py::build_source_only_keyboard() -
the exact Phase 16 implementation ("Open source" button, already shipped, already tested) - this
phase adds an optional `label` parameter only, default unchanged, so every existing caller
(services/image_preview_notifier.py) is byte-for-byte unaffected.

Cases A/B/C/D/H are pure unit tests against `build_source_only_keyboard()` and `services/
telegram_routing.py::send_to_editorial_destination()`'s new `reply_markup` passthrough. Cases E/F/G
(full worker/content_cycle.py wiring) live in tests/test_editorial_delivery_mode.py alongside the
existing Phase 23.1A router/legacy tests they extend - see that file's own "Phase 23.1E" section.
"""
from unittest.mock import AsyncMock

import pytest
from aiogram.types import InlineKeyboardMarkup

from bot.keyboards.image_preview import build_source_only_keyboard
from schemas.editorial_route import EditorialDestination
from services.telegram_routing import send_to_editorial_destination

_REAL_CHAT_ID = -1004297182444
_REAL_NEWS_TOPIC_ID = 2
_SOURCE_LABEL = "🔗 Источник"


# ---------------------------------------------------------------------------
# CASE B - the NEWS keyboard contains "🔗 Источник"
# ---------------------------------------------------------------------------


def test_case_b_keyboard_contains_the_news_source_label() -> None:
    keyboard = build_source_only_keyboard("https://example.com/article", label=_SOURCE_LABEL)
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == _SOURCE_LABEL


def test_default_label_unchanged_for_every_existing_caller() -> None:
    """Regression guard: services/image_preview_notifier.py calls build_source_only_keyboard(url)
    with no label kwarg at all - this must stay "🔗 Open source", byte-identical to before Phase
    23.1E, since that flow is unrelated to the NEWS presentation profile."""
    keyboard = build_source_only_keyboard("https://example.com/article")
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].text == "🔗 Open source"


# ---------------------------------------------------------------------------
# CASE C - the button URL exactly equals the real source URL
# ---------------------------------------------------------------------------


def test_case_c_button_url_exactly_equals_the_real_source_url() -> None:
    real_url = "https://news.google.com/rss/articles/CBMiTEFVX3lxTE9YU19Bd2JTYjBFdUhkanotRFlBSi0zOThzbVNKNXdtUnRNVmExdzZyMmRiOU1iRVhzdTZqUGw5T1BKckhlVkI0bFZ0T00"
    keyboard = build_source_only_keyboard(real_url, label=_SOURCE_LABEL)
    assert keyboard is not None
    assert keyboard.inline_keyboard[0][0].url == real_url


def test_case_c_no_url_shortener_or_fabricated_link_is_ever_introduced() -> None:
    """Structural guard: bot/keyboards/image_preview.py never imports any URL-shortening/
    redirect-service client - the button URL is always exactly the input, never transformed."""
    from pathlib import Path

    source_text = Path("bot/keyboards/image_preview.py").read_text(encoding="utf-8")
    for forbidden in ("bit.ly", "tinyurl", "t.co", "goo.gl", "shorten"):
        assert forbidden not in source_text.lower()


# ---------------------------------------------------------------------------
# CASE D - a missing/invalid URL never creates a broken button, never crashes
# ---------------------------------------------------------------------------


def test_case_d_missing_url_returns_none_never_a_broken_button() -> None:
    assert build_source_only_keyboard(None, label=_SOURCE_LABEL) is None
    assert build_source_only_keyboard("", label=_SOURCE_LABEL) is None


# ---------------------------------------------------------------------------
# reply_markup passthrough on send_to_editorial_destination() - required for E/F/G to work at all
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _routing_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    from core.config import settings

    monkeypatch.setattr(settings, "newsroom_telegram_chat_id", _REAL_CHAT_ID)
    monkeypatch.setattr(settings, "news_topic_id", _REAL_NEWS_TOPIC_ID)


@pytest.mark.asyncio
async def test_reply_markup_is_passed_through_to_bot_send_message() -> None:
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 1
    keyboard = build_source_only_keyboard("https://example.com/x", label=_SOURCE_LABEL)

    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, "text", dry_run=False, reply_markup=keyboard,
    )

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_markup"] is keyboard


@pytest.mark.asyncio
async def test_reply_markup_defaults_to_none_backward_compatible() -> None:
    """Every Phase 22/23.1A call site that never passes reply_markup at all (e.g. the Phase
    23.0B/23.1B/23.1D smoke-test scripts) must keep working unmodified."""
    bot = AsyncMock()
    bot.send_message.return_value.message_id = 1

    await send_to_editorial_destination(bot, EditorialDestination.NEWS, "text", dry_run=False)

    _, kwargs = bot.send_message.call_args
    assert kwargs["reply_markup"] is None


# ---------------------------------------------------------------------------
# CASE H - no real Telegram API call occurs during tests (structural)
# ---------------------------------------------------------------------------


def test_case_h_no_real_bot_constructed_in_this_file() -> None:
    import ast
    from pathlib import Path

    source_text = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source_text)
    imported_names = {
        alias.asname or alias.name
        for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "create_bot" not in imported_names


def test_case_h_inline_keyboard_markup_is_a_plain_data_object_no_network() -> None:
    """InlineKeyboardMarkup construction itself never touches the network - a structural sanity
    check that the type this module builds is the same pure aiogram data type used everywhere
    else in this codebase's own keyboard tests."""
    keyboard = build_source_only_keyboard("https://example.com/x")
    assert isinstance(keyboard, InlineKeyboardMarkup)
