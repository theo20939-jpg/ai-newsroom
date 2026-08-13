"""Phase 19 M1: pure, tier-1 unit tests for services.article_acquisition - no DB, no network."""
from services.article_acquisition import (
    _strip_google_news_title_suffix,
    _titles_confidently_match,
    classify_acquisition_status,
    compute_text_hash,
    estimate_substantive_char_count,
    extract_raw_text,
    resolve_canonical_url,
)
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_HEADLINE_ONLY,
    ACQUISITION_STATUS_PARTIAL_TEXT,
    ACQUISITION_STATUS_SUBSTANTIAL_TEXT,
)


def test_extract_raw_text_strips_tags_keeps_paragraphs() -> None:
    html = "<html><body><p>First paragraph.</p><p>Second paragraph.</p></body></html>"
    text = extract_raw_text(html)
    assert "First paragraph." in text
    assert "Second paragraph." in text


def test_extract_raw_text_excludes_script_and_style() -> None:
    html = "<html><body><script>var x = 'not article text';</script><style>.a{color:red}</style><p>Real text.</p></body></html>"
    text = extract_raw_text(html)
    assert "Real text." in text
    assert "not article text" not in text
    assert "color:red" not in text


def test_extract_raw_text_empty_html_returns_empty_string() -> None:
    assert extract_raw_text("") == ""


def test_extract_raw_text_malformed_html_never_raises() -> None:
    text = extract_raw_text("<p>unclosed <div>nested <span>tags")
    assert isinstance(text, str)


def test_resolve_canonical_url_prefers_link_tag() -> None:
    html = '<html><head><link rel="canonical" href="https://example.com/real-article"></head></html>'
    assert resolve_canonical_url(html, base_url="https://example.com/amp/real-article") == "https://example.com/real-article"


def test_resolve_canonical_url_resolves_relative_href() -> None:
    html = '<html><head><link rel="canonical" href="/real-article"></head></html>'
    assert resolve_canonical_url(html, base_url="https://example.com/amp/x") == "https://example.com/real-article"


def test_resolve_canonical_url_falls_back_to_base_url_when_absent() -> None:
    html = "<html><head></head></html>"
    assert resolve_canonical_url(html, base_url="https://example.com/article") == "https://example.com/article"


def test_resolve_canonical_url_rejects_malformed_scheme() -> None:
    """A canonical tag pointing at a non-http(s) scheme must never be trusted as a reuse key -
    falls back to base_url instead."""
    html = '<html><head><link rel="canonical" href="javascript:alert(1)"></head></html>'
    assert resolve_canonical_url(html, base_url="https://example.com/article") == "https://example.com/article"


def test_resolve_canonical_url_empty_html_falls_back() -> None:
    assert resolve_canonical_url("", base_url="https://example.com/x") == "https://example.com/x"


def test_classify_acquisition_status_thresholds() -> None:
    assert classify_acquisition_status(3000) == ACQUISITION_STATUS_FULL_TEXT
    assert classify_acquisition_status(2000) == ACQUISITION_STATUS_FULL_TEXT
    assert classify_acquisition_status(1999) == ACQUISITION_STATUS_SUBSTANTIAL_TEXT
    assert classify_acquisition_status(800) == ACQUISITION_STATUS_SUBSTANTIAL_TEXT
    assert classify_acquisition_status(799) == ACQUISITION_STATUS_PARTIAL_TEXT
    assert classify_acquisition_status(200) == ACQUISITION_STATUS_PARTIAL_TEXT
    assert classify_acquisition_status(199) == ACQUISITION_STATUS_HEADLINE_ONLY
    assert classify_acquisition_status(0) == ACQUISITION_STATUS_HEADLINE_ONLY


def test_compute_text_hash_is_deterministic_and_sensitive_to_content() -> None:
    a = compute_text_hash("Hello world")
    b = compute_text_hash("Hello world")
    c = compute_text_hash("Hello world!")
    assert a == b
    assert a != c
    assert len(a) == 64  # sha256 hex digest


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case H, docs/news_output_stability_forensic_report.md §9):
# estimate_substantive_char_count() - real, hand-curated interstitial-line markers, calibrated
# directly against the real BAD_GARBAGE.c LinkedIn acquisition row (empirically confirmed during
# implementation: 11 of its 401 extracted lines matched, ~400 of its 20000 characters - the vast
# majority of that specific real page WAS genuine substantive article prose, not boilerplate; this
# fix's own invariant only fires when a page is SUBSTANTIALLY a shell, which that specific real
# page was not - see the checkpoint's own honest before/after note for that exact event).
# ---------------------------------------------------------------------------

_REAL_LINKEDIN_SHELL_LINES = (
    "LinkedIn respects your privacy",
    "LinkedIn and 3rd parties use essential and non-essential cookies to provide, secure, analyze and improve our Services.",
    "Cookie Policy",
    "Accept",
    "Reject",
    "Agree & Join LinkedIn",
    "Sign in to view more content",
    "Create your free account or sign in to continue your search",
    "Sign in with Email",
    "New to LinkedIn?",
    "Skip to main content",
)

_REAL_ARTICLE_PARAGRAPH = (
    "It doesn't happen often that you get to exploit the same bug three times in ten years. It "
    "went from a truly universal escape to a less and less universal one, and it's now getting "
    "slowly patched, the upstream fix landed in early May, some three months ago."
)


def test_estimate_substantive_char_count_of_a_pure_interstitial_page_is_near_zero() -> None:
    """The required invariant: a page that is SUBSTANTIALLY just a cookie-consent/sign-in-wall
    shell (no real article paragraph at all - the genuine hard-paywall shape, unlike the real
    LinkedIn/BAD_GARBAGE.c case, which did contain the real article) must be measured as thin."""
    raw_text = "\n".join(_REAL_LINKEDIN_SHELL_LINES)
    substantive = estimate_substantive_char_count(raw_text)
    assert substantive < len(raw_text) * 0.1


def test_estimate_substantive_char_count_of_a_real_article_with_a_cookie_banner_is_unaffected() -> None:
    """Do not make every fetch with incidental cookie-banner chrome into a rejection - a genuine,
    substantial article with only a small amount of interstitial chrome mixed in must classify
    essentially unchanged (mirrors the real, confirmed BAD_GARBAGE.c shape almost exactly: 11
    short banner lines alongside a very long real article)."""
    raw_text = "\n".join(
        [*_REAL_LINKEDIN_SHELL_LINES] + [_REAL_ARTICLE_PARAGRAPH] * 20
    )
    substantive = estimate_substantive_char_count(raw_text)
    assert substantive > len(raw_text) * 0.9


def test_estimate_substantive_char_count_empty_text_is_zero() -> None:
    assert estimate_substantive_char_count("") == 0


def test_estimate_substantive_char_count_changes_classification_for_a_true_shell_page() -> None:
    """End-to-end of the actual invariant this fix exists for: a page whose entire extracted text
    is interstitial chrome must not classify as FULL_TEXT/SUBSTANTIAL_TEXT/PARTIAL_TEXT."""
    raw_text = "\n".join(_REAL_LINKEDIN_SHELL_LINES)
    raw_status = classify_acquisition_status(len(raw_text))
    substantive_status = classify_acquisition_status(estimate_substantive_char_count(raw_text))
    assert raw_status != ACQUISITION_STATUS_HEADLINE_ONLY  # the raw length alone would NOT catch this
    assert substantive_status == ACQUISITION_STATUS_HEADLINE_ONLY  # the substantive count does


# ---------------------------------------------------------------------------------------------
# Google News sibling-evidence-reuse fix (docs/google_news_sibling_reuse_fix_checkpoint.md) -
# pure title-matching safety logic. Real titles from docs/
# story_cluster_fragmentation_focused_forensic_report.md.
# ---------------------------------------------------------------------------------------------

_REAL_A1_TITLE = "Российский ИИ отправят на экзамен по духовности — модели проверят на традиционные ценности - 3DNews"
_REAL_A2_TITLE = "Российский ИИ отправят на экзамен по духовности — модели проверят на традиционные ценности"
_REAL_B1_TITLE = "«Будь это добровольно, никто бы не согласился»: Twitch начал тренировать ИИ на контенте пользователей, никого не"
_REAL_B2_TITLE = "«Будь это добровольно, никто бы не согласился»: Twitch начал тренировать ИИ на контенте пользователей, никого не спросив"


def test_strip_google_news_title_suffix_removes_real_publisher_suffix() -> None:
    assert _strip_google_news_title_suffix(_REAL_A1_TITLE) == _REAL_A2_TITLE


def test_strip_google_news_title_suffix_is_a_noop_without_a_suffix() -> None:
    assert _strip_google_news_title_suffix(_REAL_A2_TITLE) == _REAL_A2_TITLE


def test_titles_confidently_match_real_a_pair_via_suffix_stripping() -> None:
    assert _titles_confidently_match(_REAL_A1_TITLE, _REAL_A2_TITLE) is True


def test_titles_confidently_match_real_b_pair_via_prefix_containment() -> None:
    """The real RSS-truncation case: B1's own title is cut short mid-sentence relative to B2's -
    a genuine prefix, not a suffix-stripped exact match."""
    assert _titles_confidently_match(_REAL_B1_TITLE, _REAL_B2_TITLE) is True


def test_titles_confidently_match_is_order_independent() -> None:
    assert _titles_confidently_match(_REAL_B2_TITLE, _REAL_B1_TITLE) is True


def test_titles_confidently_match_rejects_same_publisher_similar_but_distinct_titles() -> None:
    """Case 4 of the required test matrix: same publisher/topic, materially different article -
    must NOT match even though both share substantial common wording."""
    a = "Российские ИИ-модели проверят на соответствие традиционным ценностям - 3DNews"
    b = "Российские ИИ-модели проверят на соответствие корпоративным стандартам безопасности"
    assert _titles_confidently_match(a, b) is False


def test_titles_confidently_match_rejects_loosely_related_short_titles() -> None:
    """Case 3 of the required test matrix: a short, generic fragment must never be trusted alone,
    even if technically a prefix (the _SIBLING_REUSE_MIN_TITLE_LEN floor)."""
    assert _titles_confidently_match("Twitch", "Twitch launches new AI training feature today") is False


def test_titles_confidently_match_rejects_same_category_different_event() -> None:
    a = "Apple announces new iPhone features - 3DNews"
    b = "Apple reports quarterly earnings decline amid investor concerns"
    assert _titles_confidently_match(a, b) is False
