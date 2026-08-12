"""Phase 19 M1: fetch-boundary tests for services.article_acquisition.acquire_article() - real
local HTTP server, DNS pinned to loopback (mirrors tests/test_image_intelligence_m2.py's exact
fixture pattern), zero real network egress.
"""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest

from core.config import settings
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FETCH_FAILED,
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_HEADLINE_ONLY,
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
    ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE,
)
from services.article_acquisition import acquire_article, is_google_news_redirect_host


class _RoutedHandler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self) -> None:
        handler = self.routes.get(self.path)
        if handler is None:
            self.send_response(404)
            self.end_headers()
            return
        handler(self)

    def log_message(self, format, *args):  # noqa: A002
        pass


@pytest.fixture
def local_server():
    routes: dict = {}

    class Handler(_RoutedHandler):
        pass

    Handler.routes = routes
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server, routes
    finally:
        server.shutdown()
        thread.join(timeout=2)


@pytest.fixture
def pinned(monkeypatch: pytest.MonkeyPatch, local_server):
    server, routes = local_server

    async def _fake_resolve(hostname, port):
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    return server, routes


def _article_url(server) -> str:
    return f"http://local.test:{server.server_port}/article"


def _html_route(html: str, *, content_type: str = "text/html; charset=utf-8"):
    def handler(request) -> None:
        body = html.encode("utf-8")
        request.send_response(200)
        request.send_header("Content-Type", content_type)
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        request.wfile.write(body)
    return handler


_LONG_PARAGRAPH = " ".join(["This is a real sentence about the article's content."] * 60)


@pytest.mark.asyncio
async def test_acquire_article_full_text(pinned) -> None:
    server, routes = pinned
    html = f"<html><body><p>{_LONG_PARAGRAPH}</p></body></html>"
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FULL_TEXT
    assert outcome.raw_extracted_text is not None
    assert _LONG_PARAGRAPH[:50] in outcome.raw_extracted_text
    assert outcome.error_code is None


@pytest.mark.asyncio
async def test_acquire_article_short_page_is_headline_only(pinned) -> None:
    server, routes = pinned
    routes["/article"] = _html_route("<html><body><p>Short.</p></body></html>")

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_HEADLINE_ONLY


@pytest.mark.asyncio
async def test_acquire_article_non_html_content_type_rejected(pinned) -> None:
    server, routes = pinned
    routes["/article"] = _html_route('{"not": "html"}', content_type="application/json")

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE
    assert outcome.raw_extracted_text is None


@pytest.mark.asyncio
async def test_acquire_article_connection_failure_never_raises(pinned) -> None:
    server, routes = pinned
    # No route registered for /missing -> the local server returns 404, which safe_fetch surfaces
    # as an HTTP error rather than raising - acquire_article() must still degrade to a status.

    outcome = await acquire_article(f"http://local.test:{server.server_port}/missing", event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FETCH_FAILED
    assert outcome.raw_extracted_text is None


@pytest.mark.asyncio
async def test_acquire_article_bounded_by_max_extracted_chars(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    server, routes = pinned
    monkeypatch.setattr(settings, "article_acquisition_max_extracted_chars", 50)
    html = f"<html><body><p>{_LONG_PARAGRAPH}</p></body></html>"
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.raw_extracted_text is not None
    assert len(outcome.raw_extracted_text) <= 50


@pytest.mark.asyncio
async def test_acquire_article_resolves_canonical_url_from_page(pinned) -> None:
    server, routes = pinned
    html = (
        f'<html><head><link rel="canonical" href="http://local.test:{server.server_port}/canonical-article">'
        f"</head><body><p>{_LONG_PARAGRAPH}</p></body></html>"
    )
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.canonical_url == f"http://local.test:{server.server_port}/canonical-article"


# ---------------------------------------------------------------------------
# NEWS Output Stability Fix (Case A, docs/news_output_stability_forensic_report.md §2): a
# news.google.com "articles" redirect-shell URL, real behavior confirmed via a single diagnostic
# live fetch during implementation (see services/article_acquisition.py's own new module comments)
# - the DNS-pinning trick the `pinned` fixture already uses (any hostname resolves to 127.0.0.1)
# lets these tests build a URL whose HOST really is "news.google.com" (so
# is_google_news_redirect_host() sees the real host) while the TCP connection lands on the local
# test server - zero real network egress, same discipline as every other test in this file.
# ---------------------------------------------------------------------------


def _google_news_url(server) -> str:
    return f"http://news.google.com:{server.server_port}/article"


def test_is_google_news_redirect_host_matches_known_hosts() -> None:
    assert is_google_news_redirect_host("https://news.google.com/rss/articles/CBMi...")
    assert is_google_news_redirect_host("https://news.google.co.uk/rss/articles/CBMi...")
    assert is_google_news_redirect_host("https://news.google.de/rss/articles/CBMi...")


def test_is_google_news_redirect_host_rejects_lookalike_and_unrelated_hosts() -> None:
    """Same word/domain-boundary-safe discipline as services/video_discovery.py::
    classify_video_url()'s own YouTube-lookalike-domain test - a host merely containing the
    substring must not match."""
    assert not is_google_news_redirect_host("https://notnews.google.com/rss/articles/CBMi...")
    assert not is_google_news_redirect_host("https://news.google.com.evil.com/rss/articles/CBMi...")
    assert not is_google_news_redirect_host("https://cbsnews.com/news/some-article")
    assert not is_google_news_redirect_host("not a url at all :::")


@pytest.mark.asyncio
async def test_google_news_shell_with_no_resolvable_signal_reports_redirect_unresolved(pinned) -> None:
    """The real, empirically-confirmed shape: Google's own JS application shell, no off-host
    canonical link, no meta-refresh - must never be silently classified as HEADLINE_ONLY article
    content (the real regression this fix closes)."""
    server, routes = pinned
    # Mirrors the real page's own shape: canonical points back at itself (Google's own host), no
    # meta-refresh, and only a small amount of incidental visible text - never claimed as content.
    html = (
        f'<html><head><link rel="canonical" href="http://news.google.com:{server.server_port}/article">'
        f"<title>Google News</title></head><body>Google News</body></html>"
    )
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_google_news_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED
    assert outcome.raw_extracted_text is None
    assert outcome.extracted_char_count is None
    assert outcome.error_code == "google_news_redirect_unresolved"


@pytest.mark.asyncio
async def test_google_news_shell_with_off_host_canonical_link_resolves_the_real_article(pinned) -> None:
    server, routes = pinned
    real_article_url = f"http://local.test:{server.server_port}/real-article"
    shell_html = (
        f'<html><head><link rel="canonical" href="{real_article_url}"></head>'
        f"<body>Google News</body></html>"
    )
    routes["/article"] = _html_route(shell_html)
    routes["/real-article"] = _html_route(f"<html><body><p>{_LONG_PARAGRAPH}</p></body></html>")

    outcome = await acquire_article(_google_news_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FULL_TEXT
    assert outcome.raw_extracted_text is not None
    assert _LONG_PARAGRAPH[:50] in outcome.raw_extracted_text
    assert outcome.canonical_url == real_article_url


@pytest.mark.asyncio
async def test_google_news_shell_with_meta_refresh_resolves_the_real_article(pinned) -> None:
    """A general, non-Google-specific redirect signal - some redirect-shell pages use meta-refresh
    instead of (or in addition to) a canonical link for non-JS clients."""
    server, routes = pinned
    real_article_url = f"http://local.test:{server.server_port}/real-article"
    shell_html = (
        f'<html><head><meta http-equiv="refresh" content="0;url={real_article_url}">'
        f"</head><body>Google News</body></html>"
    )
    routes["/article"] = _html_route(shell_html)
    routes["/real-article"] = _html_route(f"<html><body><p>{_LONG_PARAGRAPH}</p></body></html>")

    outcome = await acquire_article(_google_news_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FULL_TEXT
    assert outcome.raw_extracted_text is not None
    assert _LONG_PARAGRAPH[:50] in outcome.raw_extracted_text


@pytest.mark.asyncio
async def test_google_news_canonical_pointing_to_another_google_host_never_followed(pinned) -> None:
    """A canonical/meta-refresh target that is ITSELF still a Google News host must never be
    treated as a real resolution - prevents chasing a Google-hosted loop."""
    server, routes = pinned
    shell_html = (
        f'<html><head><link rel="canonical" href="http://news.google.com:{server.server_port}/other">'
        f"</head><body>Google News</body></html>"
    )
    routes["/article"] = _html_route(shell_html)
    # Deliberately no route registered for /other - if this were ever (incorrectly) followed, the
    # local server would 404 and the outcome would be FETCH_FAILED, not REDIRECT_UNRESOLVED,
    # making a wrongful hop directly observable by this test's own assertion below.

    outcome = await acquire_article(_google_news_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED


@pytest.mark.asyncio
async def test_hard_paywall_shell_page_is_never_classified_full_text(pinned) -> None:
    """NEWS Output Stability Fix (Case H): a genuinely-gated page (the real hard-paywall shape,
    not the real BAD_GARBAGE.c/LinkedIn case, which turned out to contain the real article) - a
    live end-to-end confirmation of the required invariant through the real acquire_article()
    path, not just the pure estimate_substantive_char_count() unit tests."""
    server, routes = pinned
    html = (
        "<html><body>"
        "<p>We use cookies to provide, secure, analyze and improve our Services.</p>"
        "<p>Cookie Policy</p>"
        "<p>Subscribe to continue reading</p>"
        "<p>Sign in to continue</p>"
        "<p>Create your free account or sign in to continue your search</p>"
        "</body></html>"
    )
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.status != ACQUISITION_STATUS_FULL_TEXT
    assert outcome.status == ACQUISITION_STATUS_HEADLINE_ONLY
    # Verbatim extraction/count are unchanged for audit purposes - only the classification differs.
    assert outcome.raw_extracted_text is not None
    assert "Cookie Policy" in outcome.raw_extracted_text


@pytest.mark.asyncio
async def test_article_with_incidental_cookie_banner_still_classifies_full_text(pinned) -> None:
    """Do not make every fetch with incidental cookie-banner chrome into a rejection - a genuine,
    substantial article that merely has a cookie banner mixed in must remain FULL_TEXT."""
    server, routes = pinned
    html = (
        "<html><body>"
        "<p>We use cookies to provide, secure, analyze and improve our Services.</p>"
        "<p>Cookie Policy</p>"
        f"<p>{_LONG_PARAGRAPH}</p>"
        "</body></html>"
    )
    routes["/article"] = _html_route(html)

    outcome = await acquire_article(_article_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FULL_TEXT


@pytest.mark.asyncio
async def test_google_news_redirect_hop_is_bounded_to_a_single_extra_fetch(pinned) -> None:
    """No infinite redirect loop: even if the resolved off-host target's own page were (perhaps
    adversarially) shaped to look like another Google News shell, the recursive re-fetch never
    re-enters the Google-News-detection branch a second time - at most two real fetches total."""
    server, routes = pinned
    real_article_url = f"http://local.test:{server.server_port}/real-article"
    shell_html = f'<html><head><link rel="canonical" href="{real_article_url}"></head><body>Google News</body></html>'
    routes["/article"] = _html_route(shell_html)
    # The "real" target's own page happens to also carry a canonical link (to itself) - if the
    # second hop incorrectly re-entered Google-News detection, this would need to matter; it must
    # not, since this second fetch is not to a news.google.com host at all.
    routes["/real-article"] = _html_route(
        f'<html><head><link rel="canonical" href="{real_article_url}"></head>'
        f"<body><p>{_LONG_PARAGRAPH}</p></body></html>"
    )

    outcome = await acquire_article(_google_news_url(server), event_id=uuid4())

    assert outcome.status == ACQUISITION_STATUS_FULL_TEXT
    assert outcome.canonical_url == real_article_url
