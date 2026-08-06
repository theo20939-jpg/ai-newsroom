"""Phase 19 M1: pure, tier-1 unit tests for services.article_acquisition - no DB, no network."""
from services.article_acquisition import (
    classify_acquisition_status,
    compute_text_hash,
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
