"""Tests for bot/keyboards/image_preview.py's NINJA PULSE Visual System v1 additions -
build_source_and_cta_keyboard(). Pure keyboard construction, no Bot/Telegram API involved.

Pre-commit correction (source button fail-closed contract): the real production call site
(worker/content_cycle.py) calls `build_source_and_cta_keyboard(event.url)` with NO `label=`
override - so this function's own default value is the one and only text real deliveries ever
see. The tests below exercise that default directly, never an explicit override, so a future
regression to the wrong (pre-existing legacy "🔗 Источник") label would be caught here."""
from bot.keyboards.image_preview import (
    NINJA_PULSE_CTA_LABEL,
    NINJA_PULSE_CTA_URL,
    NINJA_PULSE_SOURCE_LABEL,
    build_source_and_cta_keyboard,
)


def test_cta_url_is_exact():
    assert NINJA_PULSE_CTA_URL == "https://t.me/nnjvpn"


def test_cta_label_is_exact():
    assert NINJA_PULSE_CTA_LABEL == "NINJA PULSE. Подписаться 🥷"


def test_source_label_is_exact():
    assert NINJA_PULSE_SOURCE_LABEL == "Источник ↗"


def test_source_and_cta_together_single_row_using_the_real_default_label():
    """The exact call shape worker/content_cycle.py actually uses - no `label=` override."""
    keyboard = build_source_and_cta_keyboard("https://example.com/article")
    assert len(keyboard.inline_keyboard) == 1
    row = keyboard.inline_keyboard[0]
    assert len(row) == 2
    assert row[0].text == "Источник ↗"
    assert row[0].url == "https://example.com/article"
    assert row[1].text == "NINJA PULSE. Подписаться 🥷"
    assert row[1].url == "https://t.me/nnjvpn"


def test_cta_present_even_without_a_source_url():
    """No valid source URL -> one row containing ONLY the CTA - never an empty, placeholder, or
    non-clickable "Источник" button."""
    keyboard = build_source_and_cta_keyboard(None)
    assert len(keyboard.inline_keyboard) == 1
    row = keyboard.inline_keyboard[0]
    assert len(row) == 1
    assert row[0].text == "NINJA PULSE. Подписаться 🥷"
    assert row[0].url == "https://t.me/nnjvpn"


def test_cta_present_even_with_empty_string_source_url():
    keyboard = build_source_and_cta_keyboard("")
    row = keyboard.inline_keyboard[0]
    assert len(row) == 1
    assert row[0].url == NINJA_PULSE_CTA_URL


def test_no_source_row_never_contains_a_second_placeholder_button():
    """Explicit negative check for the fail-closed contract: with no source URL, the row must
    have exactly one button (the CTA) - never a disabled/placeholder second entry."""
    keyboard = build_source_and_cta_keyboard(None)
    texts = [button.text for row in keyboard.inline_keyboard for button in row]
    assert texts == ["NINJA PULSE. Подписаться 🥷"]
    assert "Источник" not in " ".join(texts)


def test_source_button_url_is_never_empty_or_placeholder_when_present():
    keyboard = build_source_and_cta_keyboard("https://example.com/real-article")
    source_button = keyboard.inline_keyboard[0][0]
    assert source_button.url
    assert source_button.url.startswith("http")
