"""Phase 18 M8: pure Telegram meme-preview rendering support (docs/
phase18_m8_telegram_editorial_preview_report.md). Mirrors `bot/image_preview_formatting.py`'s
own "pure functions, no aiogram/Bot type anywhere in this module" discipline exactly - testable
with zero Telegram mocking.
"""
from schemas.meme_preview import MemePreviewCard

# Telegram's own hard limit for a photo caption, in UTF-16 code units - same constant
# bot/image_preview_formatting.py already established for the news-image preview.
CAPTION_SAFE_LIMIT = 1024


class MemePreviewCaptionTooLongError(Exception):
    """Raised when a rendered caption exceeds `CAPTION_SAFE_LIMIT` - never silently truncated
    (mirrors `bot/formatting.py::CardTooLongError`'s identical "fail loud, let the caller decide"
    discipline)."""


def render_meme_preview_caption(card: MemePreviewCard) -> str:
    """Never sends anything - pure string construction. The on-image text (top/bottom) is shown
    again here as plain text so an editor reviewing on a small screen doesn't have to zoom into
    the image to read it, alongside a link back to the source story and the safety/quality
    summary lines."""
    lines = [
        f"🖼 {card.top_text}" + (f" / {card.bottom_text}" if card.bottom_text else ""),
        "",
        f"📰 {card.news_title}",
        f"({card.news_category})",
        "",
        card.safety_summary,
        card.quality_summary,
    ]
    if card.editor_explanation:
        lines.extend(["", f"💡 {card.editor_explanation}"])
    caption = "\n".join(lines)
    if len(caption) > CAPTION_SAFE_LIMIT:
        raise MemePreviewCaptionTooLongError(
            f"Rendered meme preview caption is {len(caption)} chars, exceeds {CAPTION_SAFE_LIMIT}."
        )
    return caption


def render_expired_candidate_alert_text() -> str:
    return "This meme candidate has expired and can no longer be reviewed."


def render_unavailable_candidate_alert_text() -> str:
    return "This meme candidate is no longer available."
