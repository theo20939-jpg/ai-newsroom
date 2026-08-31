"""Phase 18 M8 (revised, MEME PRODUCTION PIPELINE): pure Telegram meme-preview rendering support.
Mirrors `bot/image_preview_formatting.py`'s own "pure functions, no aiogram/Bot type anywhere in
this module" discipline exactly - testable with zero Telegram mocking.

MEME PRODUCTION PIPELINE (overnight phase) product correction: the MEMES topic is an editorial
INBOX, not a diagnostic console - the caption is now the short, minimal "😂 MEME\\n\\n<headline>"
shape the phase brief explicitly specifies, never a dump of the on-image text plus safety/quality
diagnostic lines (those remain visible in structured logs and on the `MemeCandidate` row itself
for anyone who needs to debug a specific meme - the caption is what the EDITOR reads, not what a
developer reads). "Do NOT duplicate the entire NEWS article" - only the headline is shown.
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
    """Never sends anything - pure string construction. Minimal, concise editorial metadata only
    (MEME PRODUCTION PIPELINE's own explicit "do NOT duplicate the entire NEWS article"
    requirement) - the on-image text is already visible IN the delivered photo itself, the source
    link is a separate inline button (bot/keyboards/meme_preview.py), never repeated in text."""
    caption = f"😂 MEME\n\n{card.news_title}"
    if len(caption) > CAPTION_SAFE_LIMIT:
        raise MemePreviewCaptionTooLongError(
            f"Rendered meme preview caption is {len(caption)} chars, exceeds {CAPTION_SAFE_LIMIT}."
        )
    return caption


def render_expired_candidate_alert_text() -> str:
    return "This meme candidate has expired and can no longer be reviewed."


def render_unavailable_candidate_alert_text() -> str:
    return "This meme candidate is no longer available."
