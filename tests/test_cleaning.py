"""Tests for services.cleaning - Phase 15 M1 title normalization + validation.

Pure unit tests, no database - clean_item()/is_valid_title() are deterministic
functions of a RawNewsItem/str only.
"""
from services.cleaning import clean_item, is_valid_title
from schemas.raw_news_item import RawNewsItem


def _raw(title: str | None, text: str = "fallback body text") -> RawNewsItem:
    return RawNewsItem(external_id="ext-1", title=title, text=text, url="https://example.com/x")


# ---------------------------------------------------------------------------
# A. Title normalization
# ---------------------------------------------------------------------------


def test_valid_title_preferred_over_html_heavy_summary() -> None:
    raw = _raw(
        title="Real Headline",
        text='<a href="https://example.com">Real Headline</a>&nbsp;<font color="#6f6f6f">Source</font>',
    )
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "Real Headline"
    # text/content is untouched - Phase 15 M1 is scoped to title normalization only.
    assert cleaned.text.startswith('<a href="https://example.com">')


def test_html_tags_and_entities_are_stripped_and_unescaped() -> None:
    raw = _raw(title='<a href="https://x.test/y">Big Announcement &amp; More</a>')
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "Big Announcement & More"


def test_whitespace_and_newline_pollution_is_normalized() -> None:
    raw = _raw(title="  Some\n   Title  \n  with   extra   spaces  ")
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "Some Title with extra spaces"


def test_ordinary_valid_title_is_unchanged() -> None:
    raw = _raw(title="OpenAI announces GPT-5")
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "OpenAI announces GPT-5"


def test_title_falls_back_to_first_line_of_text_when_no_explicit_title() -> None:
    raw = _raw(title=None, text="Headline From Body\nRest of the body text")
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "Headline From Body"


def test_long_title_is_truncated_on_a_word_boundary() -> None:
    raw = _raw(title="word " * 40)
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert len(cleaned.title) <= 120


# ---------------------------------------------------------------------------
# B. Deterministic rejection of malformed/garbage items - no LLM involved,
# clean_item() returning None means services.collector never creates a
# NewsEvent row for it at all (services/collector.py::_process_item), so no
# downstream NEWS_ANALYSIS/LLM call is even reachable for these inputs.
# ---------------------------------------------------------------------------


def test_unclosed_anchor_fragment_is_rejected() -> None:
    """The exact live-observed Google News malformation (Phase 15 M0/M0 observation
    evidence): a truncated, unclosed '<a' tag with no real headline text."""
    raw = _raw(title="<a", text="<a")
    assert clean_item(raw) is None


def test_image_tag_only_title_is_rejected() -> None:
    garbage = '<img src="https://x.test/badge.png" alt="badge">'
    raw = _raw(title=garbage, text=garbage)
    assert clean_item(raw) is None


def test_details_tag_only_title_is_rejected() -> None:
    """The exact live-observed llama.cpp Releases malformation."""
    garbage = '<details open="">'
    raw = _raw(title=garbage, text=garbage)
    assert clean_item(raw) is None


def test_blank_title_falls_back_and_then_rejects_if_text_is_also_blank() -> None:
    raw = _raw(title="   ", text="   ")
    assert clean_item(raw) is None


def test_bare_url_title_is_rejected() -> None:
    url = "https://example.com/some/article/path"
    raw = _raw(title=url, text=url)
    assert clean_item(raw) is None


def test_no_text_at_all_is_dropped() -> None:
    raw = RawNewsItem(external_id="ext-1", title="Something", text=None)
    assert clean_item(raw) is None


def test_invalid_explicit_title_falls_back_to_valid_text_derived_title() -> None:
    """An adapter-provided title candidate that is itself unusable must not sink an
    item whose body text still yields a valid title - never invents one, but also
    doesn't give up early when a working fallback exists."""
    raw = _raw(title="<a", text="A Perfectly Good Headline\nBody text follows")
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.title == "A Perfectly Good Headline"


# ---------------------------------------------------------------------------
# is_valid_title() directly
# ---------------------------------------------------------------------------


def test_is_valid_title_accepts_normal_text() -> None:
    assert is_valid_title("A normal, readable headline") is True


def test_is_valid_title_rejects_empty_and_whitespace_only() -> None:
    assert is_valid_title("") is False
    assert is_valid_title("   ") is False


def test_is_valid_title_rejects_bare_url() -> None:
    assert is_valid_title("http://example.com/a/b/c") is False
    assert is_valid_title("https://example.com/a/b/c") is False


def test_is_valid_title_rejects_html_only() -> None:
    assert is_valid_title('<details open="">') is False
    assert is_valid_title("<a") is False
    assert is_valid_title('<img src="x.png">') is False


def test_is_valid_title_accepts_title_with_incidental_punctuation() -> None:
    assert is_valid_title("Q&A: What's next for AI?") is True


# ---------------------------------------------------------------------------
# Phase 15 M3 - engagement metrics pass through clean_item() verbatim
# ---------------------------------------------------------------------------


def test_clean_item_passes_engagement_metrics_through_unchanged() -> None:
    raw = RawNewsItem(
        external_id="ext-1",
        title="A post",
        text="body",
        views_count=10000,
        forwards_count=120,
        replies_count=35,
        reactions_count=62,
    )
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.views_count == 10000
    assert cleaned.forwards_count == 120
    assert cleaned.replies_count == 35
    assert cleaned.reactions_count == 62


def test_clean_item_preserves_none_engagement_metrics() -> None:
    raw = _raw(title="An RSS-sourced post")  # engagement fields default to None

    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.views_count is None
    assert cleaned.forwards_count is None
    assert cleaned.replies_count is None
    assert cleaned.reactions_count is None


def test_clean_item_preserves_real_zero_engagement_metrics() -> None:
    raw = RawNewsItem(
        external_id="ext-1",
        title="A quiet post",
        text="body",
        views_count=0,
        forwards_count=0,
        replies_count=0,
        reactions_count=0,
    )
    cleaned = clean_item(raw)

    assert cleaned is not None
    assert cleaned.views_count == 0
    assert cleaned.forwards_count == 0
    assert cleaned.replies_count == 0
    assert cleaned.reactions_count == 0
