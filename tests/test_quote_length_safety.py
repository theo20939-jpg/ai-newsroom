"""Phase 19 M5: proves a verified quote is either rendered whole or omitted entirely - never
partially truncated - for both the text-message limit (SAFE_LIMIT, 4096 UTF-16 units) and the
media-caption limit (CAPTION_SAFE_LIMIT, 1024 UTF-16 units), per the explicit correction
requirement to test both paths. Pure unit tests - no DB, no Telegram, no aiogram.
"""
from datetime import datetime, timezone
from uuid import uuid4

from bot.formatting import SAFE_LIMIT, _telegram_utf16_length, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from schemas.editorial_inbox import EditorialInboxCard


def _card(**overrides: object) -> EditorialInboxCard:
    defaults: dict[str, object] = dict(
        draft_id=uuid4(),
        draft_title="Draft title",
        draft_body="Draft body text.",
        hashtags=None,
        draft_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        news_title="News title",
        news_category="TECH",
        news_url="https://example.com/article",
        news_published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return EditorialInboxCard(**defaults)  # type: ignore[arg-type]


def test_short_quote_renders_whole_at_safe_limit() -> None:
    card = _card(quote_text="A short verbatim quote.", quote_speaker="Jane Doe")
    rendered = render_editorial_card(card, limit=SAFE_LIMIT)
    assert "A short verbatim quote." in rendered
    assert "Jane Doe" in rendered
    assert "<blockquote>" in rendered and "</blockquote>" in rendered


def test_quote_too_long_for_safe_limit_is_omitted_not_truncated() -> None:
    """A quote that alone (plus the fixed header/title) exceeds SAFE_LIMIT even with an empty
    body must be omitted entirely - never appear as a partial substring."""
    huge_quote = "Verbatim quote word. " * 400  # ~8800 chars, exceeds SAFE_LIMIT alone
    card = _card(draft_body="Short body.", quote_text=huge_quote, quote_speaker="Jane Doe")

    rendered = render_editorial_card(card, limit=SAFE_LIMIT)

    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT
    assert "<blockquote>" not in rendered
    assert "Jane Doe" not in rendered
    # Never a partial fragment of the quote either.
    assert huge_quote[:100] not in rendered
    # The body itself is unaffected - proves omission, not a side effect of body truncation.
    assert "Short body." in rendered


def test_short_quote_renders_whole_at_caption_limit() -> None:
    card = _card(quote_text="A brief quote.", quote_speaker="Jane Doe")
    rendered = render_editorial_card(card, limit=CAPTION_SAFE_LIMIT, include_url=False)
    assert "A brief quote." in rendered
    assert _telegram_utf16_length(rendered) <= CAPTION_SAFE_LIMIT


def test_quote_too_long_for_caption_limit_is_omitted_not_truncated() -> None:
    """The much tighter 1024-unit caption limit is the case the correction specifically calls
    out to test - a moderate-length quote that would fit in a text message can still legitimately
    need to be omitted here."""
    moderate_quote = "A verbatim quote sentence that is realistically long. " * 25  # ~1400 chars, exceeds the 1024-unit caption limit once header/title overhead is included
    card = _card(draft_body="Caption body text.", quote_text=moderate_quote, quote_speaker="Jane Doe")

    rendered = render_editorial_card(card, limit=CAPTION_SAFE_LIMIT, include_url=False)

    assert _telegram_utf16_length(rendered) <= CAPTION_SAFE_LIMIT
    assert "<blockquote>" not in rendered
    assert moderate_quote[:50] not in rendered


def test_quote_omission_never_raises_card_too_long_error() -> None:
    """Omitting an oversized quote must let the card render successfully via the ordinary body-
    shrink path - never itself the cause of a CardTooLongError."""
    huge_quote = "Quote text. " * 500
    card = _card(draft_body="A body long enough to need shrinking. " * 50, quote_text=huge_quote, quote_speaker="S")
    rendered = render_editorial_card(card, limit=SAFE_LIMIT)
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


def test_no_quote_is_unaffected_by_budget_logic() -> None:
    card = _card(quote_text=None, quote_speaker=None)
    rendered = render_editorial_card(card, limit=SAFE_LIMIT)
    assert "<blockquote>" not in rendered


def test_quote_with_no_speaker_still_respects_budget() -> None:
    huge_quote = "Word " * 3000
    card = _card(quote_text=huge_quote, quote_speaker=None)
    rendered = render_editorial_card(card, limit=SAFE_LIMIT)
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT
    assert "<blockquote>" not in rendered
