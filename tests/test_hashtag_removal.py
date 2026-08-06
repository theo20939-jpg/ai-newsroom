"""Phase 18.10 M4/M10: dedicated test for the hashtag-removal quality check. Modern Telegram
media channels don't use hashtag blocks - this proves the two enforcement points directly:
(1) `services.content_draft_service.check_no_hashtags()` rejects any title/body containing a
hashtag, (2) `bot.formatting.render_editorial_card()` never emits a hashtag block, even given
legacy card data from a historical pre-M4 draft."""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from bot.formatting import render_editorial_card
from schemas.editorial_inbox import EditorialInboxCard
from services.content_draft_service import check_no_hashtags


# --- check_no_hashtags() (pure) --------------------------------------------------------------


@pytest.mark.parametrize(
    "title,body",
    [
        ("Clean title", "Clean body with no tags at all."),
        ("Title with a # not followed by a word", "Body text."),  # bare '#' is not a hashtag
        (None, "Body only, no title."),
        ("Title only.", None),
        (None, None),
    ],
)
def test_check_no_hashtags_passes_for_clean_content(title: str | None, body: str | None) -> None:
    assert check_no_hashtags(title, body) is True


@pytest.mark.parametrize(
    "title,body",
    [
        ("Company launches #NewProduct", "Body text."),
        ("Clean title", "Body text with a stray #hashtag in it."),
        ("#AI #Apple #Technology", "Body."),
        ("Title.", "Многострочный текст с #хэштегом внутри."),  # non-ASCII word chars too
    ],
)
def test_check_no_hashtags_fails_when_a_hashtag_is_present(title: str | None, body: str | None) -> None:
    assert check_no_hashtags(title, body) is False


# --- render_editorial_card() never emits a hashtag block -------------------------------------


def _card(**overrides: object) -> EditorialInboxCard:
    defaults: dict[str, object] = dict(
        draft_id=uuid4(),
        draft_title="Draft title",
        draft_body="Draft body text.",
        hashtags=["#legacy", "#tags"],
        draft_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        news_title="News title",
        news_category="TECH",
        news_url="https://example.com/article",
        news_published_at=None,
    )
    defaults.update(overrides)
    return EditorialInboxCard(**defaults)  # type: ignore[arg-type]


def test_render_never_emits_a_hashtag_block_even_with_legacy_data() -> None:
    """A historical ContentDraft row that still has hashtags populated (pre-Phase-18.10) must
    render identically to one with hashtags=None - the QUALITY CHECK FAILED requirement is about
    what actually reaches Telegram, not just what new drafts contain."""
    rendered = render_editorial_card(_card(hashtags=["#legacy", "#tags"]))
    assert "#legacy" not in rendered
    assert "#tags" not in rendered

    without = render_editorial_card(_card(hashtags=None))
    assert rendered == without
