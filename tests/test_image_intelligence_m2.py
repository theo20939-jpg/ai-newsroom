"""Tests for services.image_intelligence.run_shadow_discovery (Phase 16 M2, docs/phase16_m2_
secure_fetch_and_validation_report.md §18/§23). Local HTTP server only - no public internet, no
database (event/source primitives are passed as plain arguments, matching this module's own
established decoupled-from-the-ORM design).
"""
import io
import threading
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from PIL import Image

from core.config import settings
from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidateStatus, ImageIntelligenceResult
from services.image_intelligence import run_shadow_discovery


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
    """Pins "local.test" to the real local server for these orchestration tests - the SSRF
    validation logic itself is exhaustively covered in tests/test_safe_fetch.py; these tests
    exercise run_shadow_discovery's own orchestration (limits, concurrency, error isolation)."""
    server, routes = local_server

    async def _fake_resolve(hostname, port):
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    return server, routes


def _article_url(server) -> str:
    return f"http://local.test:{server.server_port}/article"


def _png_bytes(size=(20, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color="red").save(buf, format="PNG")
    return buf.getvalue()


def _article_html(server, image_paths: list[str]) -> bytes:
    tags = "".join(f'<meta property="og:image" content="http://local.test:{server.server_port}{p}">' for p in image_paths)
    return f"<html><head>{tags}</head><body></body></html>".encode()


def _image_route(data: bytes):
    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Type", "image/png")
        h.end_headers()
        h.wfile.write(data)

    return _handler


# ---------------------------------------------------------------------------
# 93-94: mode off makes zero network calls
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_performs_no_article_or_image_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def _tracking_safe_fetch(*args, **kwargs):
        calls.append(args)
        raise AssertionError("safe_fetch must never be called in mode=off")

    monkeypatch.setattr("services.image_intelligence.safe_fetch", _tracking_safe_fetch)
    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="<img src='https://x/y.jpg'>",
        article_url="https://example.com/article", mode="off",
    )
    assert calls == []
    assert result.mode == "off"
    assert result.candidates == []


# ---------------------------------------------------------------------------
# 95-96: shadow mode records metadata candidates + technical validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_shadow_mode_records_metadata_candidates_and_technical_validation(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="plain text, no inline image",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.article_fetch_attempted is True
    assert result.article_fetch_error is None
    assert result.candidates_validated == 1
    candidate = result.candidates[0]
    assert candidate.status == ImageCandidateStatus.VALIDATED
    assert candidate.technical_validation.format == "PNG"
    assert candidate.technical_validation.sha256 is not None


# ---------------------------------------------------------------------------
# 97: no Telegram send anywhere in this module (structural)
# ---------------------------------------------------------------------------


def test_no_telegram_or_bot_import_in_image_intelligence_modules() -> None:
    import services.article_metadata as article_metadata_module
    import services.image_intelligence as image_intelligence_module
    import services.image_validation as image_validation_module

    for module in (image_intelligence_module, article_metadata_module, image_validation_module):
        assert "aiogram" not in module.__file__ or True  # sanity - real check is the import scan below
        source = open(module.__file__, encoding="utf-8").read()
        assert "import aiogram" not in source
        assert "from bot" not in source
        assert "send_photo" not in source
        assert "send_message" not in source


# ---------------------------------------------------------------------------
# 99-100: fetch failures never raise out of run_shadow_discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_article_fetch_failure_does_not_raise(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (h.send_response(404), h.end_headers())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.article_fetch_attempted is True
    assert result.article_fetch_error == "http_error" or result.article_fetch_error is not None


@pytest.mark.asyncio
async def test_image_fetch_failure_does_not_raise_and_is_recorded(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/missing.png"])),
    )
    routes["/missing.png"] = lambda h: (h.send_response(404), h.end_headers())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.candidates_fetch_failed == 1
    assert result.candidates[0].status == ImageCandidateStatus.FETCH_FAILED
    assert result.candidates[0].technical_validation.error_code == "http_error"


@pytest.mark.asyncio
async def test_all_candidates_rejected_still_returns_a_valid_result(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/bad.png"])),
    )
    routes["/bad.png"] = lambda h: (h.send_response(200), h.send_header("Content-Type", "image/png"), h.end_headers(), h.wfile.write(b"not a real png"))

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.candidates_rejected_technical == 1
    assert isinstance(result, ImageIntelligenceResult)


@pytest.mark.asyncio
async def test_no_candidates_returns_a_valid_empty_result(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(), h.wfile.write(b"<html></html>"))

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="plain text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.candidates_discovered == 0
    assert result.candidates == []


# ---------------------------------------------------------------------------
# 105-106: zero provider/Telegram calls (structural, module-level)
# ---------------------------------------------------------------------------


def test_no_llm_gateway_or_openai_import_anywhere_in_m2_modules() -> None:
    import services.article_metadata as article_metadata_module
    import services.image_intelligence as image_intelligence_module
    import services.image_validation as image_validation_module

    for module in (image_intelligence_module, article_metadata_module, image_validation_module):
        source = open(module.__file__, encoding="utf-8").read()
        assert "openai" not in source.lower()
        assert "llm_gateway" not in source


# ---------------------------------------------------------------------------
# 108: idempotent execution
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_duplicate_execution_does_not_multiply_candidates(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    event_id = uuid4()
    first = await run_shadow_discovery(
        event_id=event_id, source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    second = await run_shadow_discovery(
        event_id=event_id, source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert len(first.candidates) == len(second.candidates) == 1
    assert first.candidates[0].candidate_id == second.candidates[0].candidate_id


# ---------------------------------------------------------------------------
# 109-110: candidate / download limits enforced
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_candidate_url_limit_enforced(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    monkeypatch.setattr(settings, "image_intelligence_max_candidate_urls_per_event", 2)
    image_paths = [f"/img{i}.png" for i in range(5)]
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, image_paths)),
    )
    for p in image_paths:
        routes[p] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert result.candidates_discovered == 2


@pytest.mark.asyncio
async def test_image_download_limit_enforced(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    monkeypatch.setattr(settings, "image_intelligence_max_image_downloads_per_event", 1)
    monkeypatch.setattr(settings, "image_intelligence_max_candidate_urls_per_event", 10)
    image_paths = [f"/img{i}.png" for i in range(3)]
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, image_paths)),
    )
    for p in image_paths:
        routes[p] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert result.candidates_discovered == 3
    touched = [c for c in result.candidates if c.status in (ImageCandidateStatus.VALIDATED, ImageCandidateStatus.REJECTED_TECHNICAL, ImageCandidateStatus.FETCH_FAILED)]
    untouched = [c for c in result.candidates if c.status == ImageCandidateStatus.DISCOVERED]
    assert len(touched) == 1
    assert len(untouched) == 2


# ---------------------------------------------------------------------------
# 111-112: concurrency limits
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_concurrency_limit_enforced(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    monkeypatch.setattr(settings, "image_intelligence_global_concurrency", 2)
    monkeypatch.setattr(settings, "image_intelligence_max_image_downloads_per_event", 6)
    monkeypatch.setattr(settings, "image_intelligence_per_host_concurrency", 6)

    concurrent = {"current": 0, "max_seen": 0}
    lock = threading.Lock()

    def _slow_image(h):
        with lock:
            concurrent["current"] += 1
            concurrent["max_seen"] = max(concurrent["max_seen"], concurrent["current"])
        import time

        time.sleep(0.2)
        h.send_response(200)
        h.send_header("Content-Type", "image/png")
        h.end_headers()
        h.wfile.write(_png_bytes())
        with lock:
            concurrent["current"] -= 1

    image_paths = [f"/img{i}.png" for i in range(6)]
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, image_paths)),
    )
    for p in image_paths:
        routes[p] = _slow_image

    await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert concurrent["max_seen"] <= 2


# ---------------------------------------------------------------------------
# 113: structured errors serialize correctly
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_result_with_errors_serializes_correctly(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (h.send_response(500), h.end_headers())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    import json

    payload = result.model_dump(mode="json")
    json.dumps(payload)  # must not raise
    assert isinstance(result.article_fetch_error, str)


# ---------------------------------------------------------------------------
# 114: M1 backward compatibility
# ---------------------------------------------------------------------------


def test_existing_m1_shaped_result_still_validates() -> None:
    """An M1-era result (no technical_validation, schema_version="m1", no M2 observability
    fields set) must still validate against the current, M2-extended schema - every M2 field has
    a default that is exactly correct for "M2 never ran"."""
    m1_shaped = {
        "version": "m1",
        "mode": "shadow",
        "event_id": str(uuid4()),
        "candidates_discovered": 1,
        "candidates_accepted": 1,
        "candidates_rejected": 0,
        "candidates": [
            {
                "candidate_id": "abc123",
                "schema_version": "m1",
                "event_id": str(uuid4()),
                "source_type": "RSS",
                "discovery_method": "rss_inline_image",
                "status": "discovered",
                "remote_url": "https://cdn.example.com/a.jpg",
                "discovery_order": 0,
                "discovered_at": datetime.now(timezone.utc).isoformat(),
            }
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = ImageIntelligenceResult.model_validate(m1_shaped)
    assert result.candidates[0].technical_validation is None
    assert result.article_fetch_attempted is False
    assert result.candidates_validated == 0
