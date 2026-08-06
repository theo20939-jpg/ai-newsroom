"""Tests for bot.formatting (Phase 11 M2, docs/
phase11_telegram_editorial_inbox_architecture_contract.md §12/§13/§14/§24).

Pure unit tests - no DB, no Telegram, no aiogram import anywhere in this file.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from bot.formatting import (
    SAFE_LIMIT,
    CardTooLongError,
    _telegram_utf16_length,
    render_editorial_card,
)
from schemas.editorial_inbox import EditorialInboxCard

_ASTRAL_EMOJI = "\U0001F4F0"  # the card's own static newspaper emoji, U+1F4F0


def _card(**overrides: object) -> EditorialInboxCard:
    defaults: dict[str, object] = dict(
        draft_id=uuid4(),
        draft_title="Draft title",
        draft_body="Draft body text.",
        hashtags=["#example", "#news"],
        draft_created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        news_title="News title",
        news_category="TECH",
        news_url="https://example.com/article",
        news_published_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )
    defaults.update(overrides)
    return EditorialInboxCard(**defaults)  # type: ignore[arg-type]


# --- escaping -----------------------------------------------------------------------------


def test_draft_title_is_escaped() -> None:
    rendered = render_editorial_card(_card(draft_title="<b>evil</b> & co"))
    assert "&lt;b&gt;evil&lt;/b&gt; &amp; co" in rendered
    assert "<b>evil</b>" not in rendered


def test_draft_body_is_escaped() -> None:
    rendered = render_editorial_card(_card(draft_body="<script>alert(1)</script> & more"))
    assert "&lt;script&gt;alert(1)&lt;/script&gt; &amp; more" in rendered


def test_news_title_and_category_are_escaped() -> None:
    rendered = render_editorial_card(_card(news_title="A & B", news_category="TECH<X>"))
    assert "A &amp; B" in rendered
    assert "TECH&lt;X&gt;" in rendered


def test_hashtags_are_never_rendered_even_with_legacy_card_data() -> None:
    """Phase 18.10 M4: the hashtag block is removed unconditionally - a historical
    EditorialInboxCard carrying legacy hashtag data (from a pre-M4 draft) still never renders
    one, not just newly-generated cards with hashtags=None."""
    rendered = render_editorial_card(_card(hashtags=["#a&b", "#<tag>"]))
    assert "#a&b" not in rendered
    assert "#a&amp;b" not in rendered
    assert "#<tag>" not in rendered
    assert "#&lt;tag&gt;" not in rendered


def test_news_url_is_escaped_including_literal_ampersand() -> None:
    rendered = render_editorial_card(_card(news_url="https://example.com/x?a=1&b=2"))
    assert "https://example.com/x?a=1&amp;b=2" in rendered


def test_news_url_is_never_rendered_as_clickable_anchor() -> None:
    rendered = render_editorial_card(_card(news_url="https://example.com/article"))
    assert "<a href" not in rendered
    assert "<a " not in rendered


def test_hashtags_never_add_a_line_regardless_of_legacy_data() -> None:
    """Phase 18.10 M4: rendering is now identical whether or not the card carries legacy
    hashtag data - the block is gone entirely, not merely conditionally shown."""
    with_tags = render_editorial_card(_card(hashtags=["#one", "#two", "#three"]))
    without_tags = render_editorial_card(_card(hashtags=None))
    assert "#one" not in with_tags
    assert with_tags == without_tags


def test_none_hashtags_and_empty_list_both_omit_line() -> None:
    none_rendered = render_editorial_card(_card(hashtags=None))
    empty_rendered = render_editorial_card(_card(hashtags=[]))
    assert none_rendered == empty_rendered


def test_missing_title_renders_placeholder() -> None:
    rendered = render_editorial_card(_card(draft_title=None))
    assert "(no title generated)" in rendered


def test_missing_body_renders_placeholder() -> None:
    rendered = render_editorial_card(_card(draft_body=None))
    assert "(no body generated)" in rendered


def test_missing_news_url_omits_line() -> None:
    with_url = render_editorial_card(_card(news_url="https://example.com/x"))
    without_url = render_editorial_card(_card(news_url=None))
    assert "https://example.com/x" not in without_url
    assert len(without_url.splitlines()) < len(with_url.splitlines())


def test_missing_published_at_omits_date_suffix() -> None:
    rendered = render_editorial_card(_card(news_published_at=None))
    assert "·" not in rendered  # the "·" separator only appears with a date


# --- UTF-16 length semantics ----------------------------------------------------------------


def test_bmp_only_payload_utf16_length_equals_python_len() -> None:
    text = "Plain ASCII and BMP Cyrillic Я text"
    assert _telegram_utf16_length(text) == len(text)


def test_astral_character_counts_as_two_utf16_units() -> None:
    assert _telegram_utf16_length(_ASTRAL_EMOJI) == 2
    assert len(_ASTRAL_EMOJI) == 1


def test_len_le_4096_but_utf16_length_gt_4096_is_correctly_detected_as_oversized() -> None:
    # Each astral emoji is 1 Python code point but 2 UTF-16 code units - 3000 of them make
    # len() report 3000 (comfortably "under" 4096) while the true UTF-16 length is 6000.
    payload = _ASTRAL_EMOJI * 3000
    assert len(payload) <= SAFE_LIMIT
    assert _telegram_utf16_length(payload) > SAFE_LIMIT

    # The renderer must not be fooled by this: a body built from the same trap payload must
    # still come back within SAFE_LIMIT (via truncation), never returned oversized.
    rendered = render_editorial_card(_card(draft_body=payload))
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


def test_static_card_emoji_is_included_in_every_measurement() -> None:
    rendered = render_editorial_card(_card())
    assert _ASTRAL_EMOJI in rendered
    assert _telegram_utf16_length(rendered) == len(rendered.encode("utf-16-le")) // 2


def test_ai_generated_emoji_in_body_counts_correctly() -> None:
    body_with_emoji = "Great news " + _ASTRAL_EMOJI * 5
    rendered = render_editorial_card(_card(draft_body=body_with_emoji))
    # Each astral character contributes +1 to (utf16_length - len()): 5 in the AI-generated body
    # plus 1 from the card's own static header emoji (Contract §12) = 6 total.
    assert _telegram_utf16_length(rendered) - len(rendered) == 6


# --- truncation / worst case -----------------------------------------------------------------


def test_worst_case_escaping_expansion_is_truncated_within_utf16_limit() -> None:
    # Dense in '&' characters: each expands 1 char -> 5 chars ("&amp;") on escape.
    dense_body = "&" * 5000
    rendered = render_editorial_card(_card(draft_body=dense_body))
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


def test_truncation_never_produces_a_dangling_html_entity() -> None:
    dense_body = "x" * 3000 + "&" * 2000
    rendered = render_editorial_card(_card(draft_body=dense_body))
    # Every '&' in the rendered text must start a complete, valid entity - never a dangling
    # fragment (e.g. "&am" cut mid-entity by truncation).
    i = 0
    while True:
        i = rendered.find("&", i)
        if i == -1:
            break
        assert rendered[i : i + 5] == "&amp;" or rendered[i : i + 4] == "&lt;" or rendered[i : i + 4] == "&gt;", (
            f"dangling/malformed entity at position {i}: {rendered[i : i + 10]!r}"
        )
        i += 1


def test_body_that_fits_is_returned_unmodified_no_truncation() -> None:
    card = _card(draft_body="Short body.")
    rendered = render_editorial_card(card)
    assert "Short body." in rendered
    assert "…" not in rendered  # no truncation marker


def test_truncation_shrinks_only_draft_body_other_fields_unchanged() -> None:
    long_body = "word " * 2000
    card = _card(draft_body=long_body, news_title="Stable Title", news_category="STABLE")
    rendered = render_editorial_card(card)
    assert "Stable Title" in rendered
    assert "STABLE" in rendered
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


def test_terminal_fallback_raises_card_too_long_error() -> None:
    # Even fully exhausted (empty body), category+title+hashtags alone exceed SAFE_LIMIT.
    huge_title = "T" * 5000
    card = _card(draft_body=None, news_title=huge_title)
    with pytest.raises(CardTooLongError):
        render_editorial_card(card)


def test_every_successful_render_satisfies_the_utf16_invariant() -> None:
    bodies = [
        "short",
        "word " * 100,
        "&" * 1000,
        _ASTRAL_EMOJI * 500,
        "mixed " + _ASTRAL_EMOJI * 50 + "&<>" * 50,
    ]
    for body in bodies:
        rendered = render_editorial_card(_card(draft_body=body))
        assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


# --- Russian output remediation (Phase 11 regression F: renders a Russian ContentDraft
# unchanged, performs no translation) --------------------------------------------------------


def test_russian_content_renders_verbatim_no_translation() -> None:
    """Phase 11 is presentation-only (Contract §12/§13) - a genuinely Russian ContentDraft must
    pass through the renderer completely unchanged in content (escaped only where HTML
    metacharacters actually occur, never translated, never transliterated, never altered)."""
    card = _card(
        draft_title="Заголовок новости",
        draft_body="Полный текст редакционного поста на русском языке.",
        hashtags=["#новости", "#технологии"],  # legacy field - never rendered (Phase 18.10 M4)
        news_title="Оригинальное событие на русском",
        news_category="AI",
    )

    rendered = render_editorial_card(card)

    assert "Заголовок новости" in rendered
    assert "Полный текст редакционного поста на русском языке." in rendered
    assert "#новости" not in rendered
    assert "Оригинальное событие на русском" in rendered
    assert _telegram_utf16_length(rendered) <= SAFE_LIMIT


def test_russian_content_with_html_metacharacters_still_escaped() -> None:
    """The renderer must not special-case language - a Russian field containing HTML
    metacharacters is escaped exactly like an English one would be."""
    card = _card(draft_title="Заголовок <b>жирный</b> & опасный", draft_body="Текст.")

    rendered = render_editorial_card(card)

    assert "Заголовок &lt;b&gt;жирный&lt;/b&gt; &amp; опасный" in rendered
    assert "<b>жирный</b>" not in rendered


# --- limit / include_url (Phase 16 UX fix, docs/phase16_ux_combined_preview_fix_report.md) ---
# Both parameters default to the frozen Contract §14 behavior (SAFE_LIMIT, True) - every test
# above this point exercises the default and is completely unaffected by these additions.


def test_default_call_is_byte_identical_to_before_the_ux_fix() -> None:
    card = _card(news_url="https://example.com/article")
    assert render_editorial_card(card) == render_editorial_card(card, limit=SAFE_LIMIT, include_url=True)


def test_include_url_false_omits_the_url_line() -> None:
    card = _card(news_url="https://example.com/article")
    with_url = render_editorial_card(card)
    without_url = render_editorial_card(card, include_url=False)
    assert "https://example.com/article" in with_url
    assert "https://example.com/article" not in without_url


def test_include_url_false_is_a_no_op_when_there_is_no_url_anyway() -> None:
    card = _card(news_url=None)
    assert render_editorial_card(card) == render_editorial_card(card, include_url=False)


def test_smaller_limit_truncates_more_aggressively_than_the_default() -> None:
    """The combined image-preview flow passes Telegram's own, much smaller photo-caption limit
    (1024 UTF-16 code units) - the exact same shrink-to-fit algorithm, just a tighter ceiling."""
    long_body = " ".join(f"word{i}" for i in range(2000))
    card = _card(draft_body=long_body)

    full = render_editorial_card(card, include_url=False)
    capped = render_editorial_card(card, limit=1024, include_url=False)

    assert _telegram_utf16_length(full) <= SAFE_LIMIT
    assert _telegram_utf16_length(capped) <= 1024
    assert len(capped) < len(full)


def test_smaller_limit_still_raises_card_too_long_error_when_unavoidable() -> None:
    """Mirrors the existing terminal-fallback test below for SAFE_LIMIT, at a much tighter limit -
    proves the raised-not-silently-truncated invariant holds regardless of which limit is passed."""
    card = _card(
        draft_title="x" * 2000, draft_body=None, news_title="y" * 2000, hashtags=None, news_url=None,
    )
    with pytest.raises(CardTooLongError):
        render_editorial_card(card, limit=50, include_url=False)


# --- Phase 18.10 M5: quote blockquote rendering ----------------------------------------------


def test_quote_renders_as_telegram_blockquote() -> None:
    rendered = render_editorial_card(
        _card(quote_text="We are shipping this next quarter", quote_speaker="Jane Smith, CEO")
    )
    assert "<blockquote>We are shipping this next quarter</blockquote>" in rendered
    assert "Jane Smith, CEO" in rendered


def test_quote_is_escaped() -> None:
    rendered = render_editorial_card(_card(quote_text="We <will> ship & deliver", quote_speaker="CEO"))
    assert "<blockquote>We &lt;will&gt; ship &amp; deliver</blockquote>" in rendered
    assert "<will>" not in rendered


def test_no_quote_omits_blockquote_entirely() -> None:
    rendered = render_editorial_card(_card())
    assert "<blockquote>" not in rendered


def test_quote_without_speaker_still_renders_the_quote_text() -> None:
    rendered = render_editorial_card(_card(quote_text="A verified quote with no speaker given"))
    assert "<blockquote>A verified quote with no speaker given</blockquote>" in rendered


def test_limit_and_include_url_compose_together() -> None:
    long_body = " ".join(f"word{i}" for i in range(2000))
    card = _card(draft_body=long_body, news_url="https://example.com/article")

    rendered = render_editorial_card(card, limit=1024, include_url=False)

    assert "https://example.com/article" not in rendered
    assert _telegram_utf16_length(rendered) <= 1024
