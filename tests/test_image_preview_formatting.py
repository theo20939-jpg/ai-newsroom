"""Tests for bot.image_preview_formatting's remaining pure helpers (docs/
phase16_m6_telegram_editorial_preview_report.md §5, docs/phase16_ux_combined_preview_fix_report.md).
No aiogram/Bot type anywhere in this file.

The UX fix removed this module's own candidate-metadata caption renderer (`render_image_preview_
caption`), the "no candidates" text, and the "decision confirmation" text - every message the
combined preview flow sends is now the *actual* news card (`bot/formatting.py::
render_editorial_card()`, tested in tests/test_editorial_card_formatting.py) rather than a
candidate-specific technical readout. What remains here is the shared `CAPTION_SAFE_LIMIT`
constant and the two callback-alert strings (shown only as Telegram alert popups, never as message
content).
"""
from bot.image_preview_formatting import (
    CAPTION_SAFE_LIMIT,
    render_expired_candidate_alert_text,
    render_unavailable_candidate_alert_text,
)


def test_caption_safe_limit_is_telegrams_own_photo_caption_limit() -> None:
    """Distinct from (and much smaller than) bot/formatting.py::SAFE_LIMIT (4096), which applies
    to plain text messages only."""
    assert CAPTION_SAFE_LIMIT == 1024


def test_alert_texts_are_distinct_and_non_empty() -> None:
    expired = render_expired_candidate_alert_text()
    unavailable = render_unavailable_candidate_alert_text()
    assert expired and unavailable
    assert expired != unavailable
