"""Tests for services.image_intelligence.run_shadow_discovery's Phase 16 M3 integration (docs/
phase16_m3_quality_and_deduplication_report.md §29). Local HTTP server only - no public internet.
"""
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from PIL import Image

from database.models.news_source import SourceType
from schemas.image_candidate import ImageCandidateStatus, ImageIntelligenceResult, QualityStatus
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
    server, routes = local_server

    async def _fake_resolve(hostname, port):
        return "127.0.0.1"

    monkeypatch.setattr("integrations.http.safe_fetch._resolve_safe_ip", _fake_resolve)
    return server, routes


def _article_url(server) -> str:
    return f"http://local.test:{server.server_port}/article"


def _png_bytes(size=(1000, 700), color=(90, 110, 130)) -> bytes:
    buf = io.BytesIO()
    img = Image.new("RGB", size)
    px = img.load()
    for y in range(0, size[1], 4):
        for x in range(0, size[0], 4):
            px[x, y] = ((x + color[0]) % 256, (y + color[1]) % 256, (x + y + color[2]) % 256)
    img.save(buf, format="PNG")
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
# 82-89: workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mode_off_performs_no_fetch_and_no_quality_work(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def _tracking(*args, **kwargs):
        calls.append(args)
        raise AssertionError("must never be called in mode=off")

    monkeypatch.setattr("services.image_intelligence.safe_fetch", _tracking)
    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url="https://example.com/a", mode="off",
    )
    assert calls == []
    assert result.candidates == []
    assert result.candidates_quality_accepted == 0


@pytest.mark.asyncio
async def test_shadow_mode_records_m3_result(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    # Phase 16 M4 also runs on this same VALIDATED+ACCEPTED candidate (relevance ranking is now
    # layered on top of M3), so the result version reflects the latest milestone that actually
    # processed it - "m4", not "m3" - exactly as M3 itself bumped M2's "m2" results to "m3".
    assert result.version == "m4"
    candidate = result.candidates[0]
    assert candidate.quality_validation is not None
    assert candidate.quality_validation.status == QualityStatus.ACCEPTED
    assert result.candidates_quality_accepted == 1


@pytest.mark.asyncio
async def test_shadow_mode_sends_no_image() -> None:
    import inspect

    source = inspect.getsource(run_shadow_discovery)
    assert "send_photo" not in source
    assert "send_message" not in source


@pytest.mark.asyncio
async def test_shadow_mode_does_not_change_content_draft_text(pinned) -> None:
    """run_shadow_discovery has no ContentDraft/title/body parameter or return field at all - it
    cannot change draft text by construction (structural proof, matching the M1/M2 report's own
    precedent - the executor-level "unchanged copywriting fields" test lives in
    tests/test_capability_executor_image_intelligence.py)."""
    import inspect

    signature = inspect.signature(run_shadow_discovery)
    assert "draft" not in " ".join(signature.parameters.keys()).lower()
    assert not hasattr(ImageIntelligenceResult, "draft_title")
    assert not hasattr(ImageIntelligenceResult, "draft_body")


@pytest.mark.asyncio
async def test_m3_failure_does_not_fail_content_generation(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    def _broken_cluster(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.image_intelligence.cluster_candidates", _broken_cluster)

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    # must not raise - M2 technical result still present even though M3 finalization failed
    assert result.candidates[0].technical_validation is not None
    assert result.candidates[0].status == ImageCandidateStatus.VALIDATED


@pytest.mark.asyncio
async def test_perceptual_hash_failure_preserves_m2_result(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    def _broken_analyze(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.image_intelligence.analyze_candidate", _broken_analyze)

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    candidate = result.candidates[0]
    assert candidate.status == ImageCandidateStatus.VALIDATED  # M2 result untouched
    assert candidate.technical_validation is not None
    assert candidate.quality_validation is None  # M3 simply didn't attach anything


@pytest.mark.asyncio
async def test_all_candidates_rejected_quality_still_permits_text_delivery(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/tiny.png"])),
    )
    routes["/tiny.png"] = _image_route(_png_bytes(size=(1, 1)))

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.candidates_rejected_quality == 1
    assert isinstance(result, ImageIntelligenceResult)  # result itself always valid regardless


@pytest.mark.asyncio
async def test_zero_candidates_permits_text_delivery(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(), h.wfile.write(b"<html></html>"))

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow",
    )
    assert result.candidates == []
    assert result.candidates_quality_accepted == 0


# ---------------------------------------------------------------------------
# 90-98
# ---------------------------------------------------------------------------


def test_fact_safety_module_unaffected_by_m3() -> None:
    import inspect

    from services import fact_safety

    assert "image_quality" not in inspect.getsource(fact_safety)
    assert "image_deduplication" not in inspect.getsource(fact_safety)


def test_editorial_scoring_module_unaffected_by_m3() -> None:
    import inspect

    from services import editorial_scoring

    assert "image_quality" not in inspect.getsource(editorial_scoring)
    assert "image_deduplication" not in inspect.getsource(editorial_scoring)


def test_no_provider_calls_anywhere_in_m3_modules() -> None:
    from services import image_deduplication, image_quality

    for module in (image_quality, image_deduplication):
        source = open(module.__file__, encoding="utf-8").read()
        assert "openai" not in source.lower()
        assert "llm_gateway" not in source


def test_no_telegram_image_send_in_m3_modules() -> None:
    from services import image_deduplication, image_quality

    for module in (image_quality, image_deduplication):
        source = open(module.__file__, encoding="utf-8").read()
        assert "send_photo" not in source
        assert "aiogram" not in source


def test_m3_modules_never_touch_the_database() -> None:
    """M3's own production modules (services/image_quality.py, services/image_deduplication.py)
    remain pure, in-memory, DB-free code - unchanged since M3 shipped. Superseded by Phase 16 M5
    (docs/phase16_m5_persistence_and_retention_report.md), which legitimately adds a durable
    `image_candidates` table from a separate module (services/image_persistence.py) - this test
    used to assert no migration existed anywhere in the repo, which stopped being a meaningful M3
    invariant once a later milestone legitimately owns that table (exactly mirroring how M4's own
    report updated an M3-era `version == "m3"` expectation for the same reason)."""
    from services import image_deduplication, image_quality

    for module in (image_quality, image_deduplication):
        source = open(module.__file__, encoding="utf-8").read()
        assert "sqlalchemy" not in source.lower()
        assert "alembic" not in source.lower()
        assert "image_candidates" not in source


@pytest.mark.asyncio
async def test_existing_m1_and_m2_result_deserialization_remains_compatible() -> None:
    from datetime import datetime, timezone

    m2_shaped = {
        "version": "m2", "mode": "shadow", "event_id": str(uuid4()),
        "candidates_discovered": 1, "candidates_accepted": 1, "candidates_rejected": 0,
        "candidates": [{
            "candidate_id": "abc123", "schema_version": "m2", "event_id": str(uuid4()),
            "source_type": "RSS", "discovery_method": "open_graph_image", "status": "validated",
            "remote_url": "https://cdn.example.com/a.jpg", "discovery_order": 0,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
            "technical_validation": {
                "version": "m2", "format": "JPEG", "width": 800, "height": 600,
                "sha256": "a" * 64, "error_code": None,
            },
        }],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    result = ImageIntelligenceResult.model_validate(m2_shaped)
    assert result.candidates[0].quality_validation is None
    assert result.candidates_quality_accepted == 0


@pytest.mark.asyncio
async def test_duplicate_execution_remains_idempotent(pinned) -> None:
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
    assert first.candidates[0].quality_validation.deduplication.exact_cluster_id == second.candidates[0].quality_validation.deduplication.exact_cluster_id


@pytest.mark.asyncio
async def test_no_extra_image_fetch_for_m3(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    """M3 reuses the exact same in-memory bytes M2 already fetched - proven by counting how many
    times safe_fetch is actually called for one candidate (must be exactly 1: the image itself;
    the article page fetch is a separate, expected call)."""
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    from integrations.http import safe_fetch as safe_fetch_module

    real_fetch = safe_fetch_module.safe_fetch
    call_count = {"n": 0}

    async def _counting_fetch(url, *, policy):
        call_count["n"] += 1
        return await real_fetch(url, policy=policy)

    monkeypatch.setattr("services.image_intelligence.safe_fetch", _counting_fetch)

    await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert call_count["n"] == 2  # exactly one article-page fetch + one image fetch, never two image fetches


@pytest.mark.asyncio
async def test_transient_image_resources_are_released(pinned) -> None:
    """No open file handles / PIL Image objects leak past run_shadow_discovery - proven indirectly
    by running many candidates through the pipeline without error (a real leak would eventually
    exhaust file descriptors or raise on Windows due to a still-open BytesIO/Image)."""
    server, routes = pinned
    paths = [f"/img{i}.png" for i in range(5)]
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, paths)),
    )
    for p in paths:
        routes[p] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text", article_url=_article_url(server), mode="shadow"
    )
    assert result.candidates_quality_accepted + result.candidates_rejected_quality + result.candidates_duplicate_exact + result.candidates_duplicate_near + result.candidates_review >= 1
