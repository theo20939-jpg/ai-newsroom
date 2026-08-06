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
    ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE,
)
from services.article_acquisition import acquire_article


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
