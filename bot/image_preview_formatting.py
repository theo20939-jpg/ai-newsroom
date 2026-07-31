"""Phase 16 M6/UX fix: pure Telegram Editorial Preview support (docs/
phase16_m6_telegram_editorial_preview_report.md §5, docs/phase16_ux_combined_preview_fix_report.md).
Mirrors bot/formatting.py's own "pure functions, no aiogram/Bot type anywhere in this module"
discipline exactly - testable with zero Telegram mocking.

The UX fix folded the image preview into a single combined message that shows the *actual* news
card content (via `bot.formatting.render_editorial_card()`, reused directly - never duplicated or
reinvented here) as the photo caption/text, so this module no longer renders any candidate-specific
technical display (quality/relevance score, discovery reason, "Image N/Total") - "one message = one
news item," never a separate technical readout. What remains here is purely the two callback-alert
strings (shown as Telegram alert popups, never as message content) and the shared
`CAPTION_SAFE_LIMIT` constant `bot/handlers/image_preview.py`/`services/image_preview_notifier.py`
both need to size a photo caption correctly.
"""

# Telegram's own hard limit for a photo caption, in UTF-16 code units - distinct from (and much
# smaller than) bot/formatting.py's SAFE_LIMIT (4096), which applies to plain text messages only.
CAPTION_SAFE_LIMIT = 1024


def render_expired_candidate_alert_text() -> str:
    """Shown as a Telegram callback-query alert (`show_alert=True`), not a message edit - the
    candidate being acted on has already expired per M5's own retention policy (§8/§9)."""
    return "This image candidate has expired and can no longer be selected."


def render_unavailable_candidate_alert_text() -> str:
    """Shown when the referenced candidate row no longer exists at all (deleted, or a tampered/
    stale callback from an old message) - distinct from the expired case above."""
    return "This image candidate is no longer available."
