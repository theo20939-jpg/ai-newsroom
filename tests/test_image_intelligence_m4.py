"""Tests for services.image_intelligence.run_shadow_discovery's Phase 16 M4 integration (docs/
phase16_m4_relevance_ranking_report.md §26). Local HTTP server only - no public internet.
"""
import inspect
import io
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from uuid import uuid4

import pytest
from PIL import Image

from database.models.news_source import SourceType
from schemas.image_candidate import ImageIntelligenceResult, RelevanceStatus
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


def _png_bytes(size=(1200, 630), color=(90, 110, 130)) -> bytes:
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
    return f"<html><head><title>GPT-5 launch</title>{tags}</head><body></body></html>".encode()


def _image_route(data: bytes):
    def _handler(h):
        h.send_response(200)
        h.send_header("Content-Type", "image/png")
        h.end_headers()
        h.wfile.write(data)

    return _handler


# ---------------------------------------------------------------------------
# 77-92: workflow
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_77_mode_off_performs_no_network_and_no_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def _tracking(*args, **kwargs):
        calls.append(args)
        raise AssertionError("must never be called in mode=off")

    monkeypatch.setattr("services.image_intelligence.safe_fetch", _tracking)
    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url="https://example.com/a", mode="off", event_title="GPT-5 launch", source_name="TechSite",
    )
    assert calls == []
    assert result.candidates == []
    assert result.candidates_ranked == 0
    assert result.top_candidate_ids == []


@pytest.mark.asyncio
async def test_78_shadow_mode_records_m4_result(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="GPT-5 launch article body",
        article_url=_article_url(server), mode="shadow", event_title="OpenAI announces GPT-5", source_name="TechSite",
    )
    assert result.version == "m4"
    candidate = result.candidates[0]
    assert candidate.relevance_validation is not None
    assert candidate.relevance_validation.status == RelevanceStatus.RANKED
    assert result.candidates_ranked == 1
    assert result.top_candidate_ids == [candidate.candidate_id]


@pytest.mark.asyncio
async def test_79_shadow_mode_sends_no_image() -> None:
    source = inspect.getsource(run_shadow_discovery)
    assert "send_photo" not in source
    assert "send_message" not in source


@pytest.mark.asyncio
async def test_80_shadow_mode_does_not_change_content_draft_text() -> None:
    signature = inspect.signature(run_shadow_discovery)
    assert "draft" not in " ".join(signature.parameters.keys()).lower()
    assert not hasattr(ImageIntelligenceResult, "draft_title")
    assert not hasattr(ImageIntelligenceResult, "draft_body")


@pytest.mark.asyncio
async def test_81_m4_failure_does_not_fail_content_generation(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    def _boom(*args, **kwargs):
        raise RuntimeError("simulated relevance-ranking failure")

    monkeypatch.setattr("services.image_intelligence.rank_candidates", _boom)
    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow", event_title="GPT-5", source_name="TechSite",
    )
    # No exception raised - M2/M3 evidence preserved even though M4 ranking failed.
    assert result.candidates[0].quality_validation is not None
    assert result.candidates[0].relevance_validation is None


@pytest.mark.asyncio
async def test_82_one_candidate_failure_does_not_block_others(monkeypatch: pytest.MonkeyPatch, pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png", "/img2.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes(color=(10, 20, 30)))
    routes["/img2.png"] = _image_route(_png_bytes(color=(200, 150, 40)))

    import services.image_relevance as relevance_module

    original = relevance_module.score_candidate
    call_count = {"n": 0}

    def _flaky(candidate, ctx):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise RuntimeError("simulated single-candidate failure")
        return original(candidate, ctx)

    monkeypatch.setattr(relevance_module, "score_candidate", _flaky)

    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow", event_title="GPT-5", source_name="TechSite",
    )
    statuses = [c.relevance_validation.status for c in result.candidates if c.relevance_validation]
    assert RelevanceStatus.INSUFFICIENT_EVIDENCE in statuses or RelevanceStatus.RANKED in statuses
    assert len(result.candidates) == 2


@pytest.mark.asyncio
async def test_83_zero_ranked_candidates_still_permits_text_delivery() -> None:
    result = await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content=None,
        article_url=None, mode="shadow", event_title="GPT-5", source_name="TechSite",
    )
    assert result.candidates_ranked == 0
    assert result.top_candidate_ids == []


@pytest.mark.asyncio
async def test_84_fact_safety_remains_unchanged() -> None:
    source = inspect.getsource(run_shadow_discovery)
    assert "fact_safety" not in source.lower()


@pytest.mark.asyncio
async def test_85_editorial_scoring_remains_unchanged() -> None:
    source = inspect.getsource(run_shadow_discovery)
    assert "editorial_scoring" not in source.lower()


def test_86_no_provider_calls() -> None:
    import ast

    tree = ast.parse(inspect.getsource(__import__("services.image_relevance", fromlist=["x"])))
    forbidden = {"openai", "httpx", "requests", "aiohttp"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = {node.module.split(".")[0]}
        else:
            continue
        assert not (names & forbidden)


@pytest.mark.asyncio
async def test_87_no_telegram_image_send() -> None:
    import services.image_relevance as relevance_module

    source = inspect.getsource(relevance_module)
    assert "send_photo" not in source
    assert "aiogram" not in source


def test_88_no_database_migration() -> None:
    import services.image_relevance as relevance_module

    source = inspect.getsource(relevance_module)
    assert "alembic" not in source.lower()
    assert "CREATE TABLE" not in source.upper()


def test_89_existing_m1_m3_deserialization_remains_compatible() -> None:
    from datetime import datetime, timezone
    from uuid import uuid4 as _uuid4

    m1_payload = {
        "candidate_id": "cand-old", "schema_version": "m1", "event_id": str(_uuid4()),
        "source_type": "RSS", "discovery_method": "rss_media_content", "status": "discovered",
        "discovery_order": 0, "discovered_at": datetime.now(timezone.utc).isoformat(),
    }
    from schemas.image_candidate import ImageCandidate

    rebuilt = ImageCandidate.model_validate(m1_payload)
    assert rebuilt.relevance_validation is None
    assert rebuilt.quality_validation is None


@pytest.mark.asyncio
async def test_90_duplicate_execution_is_idempotent(pinned) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    kwargs = dict(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow", event_title="GPT-5", source_name="TechSite",
    )
    result_a = await run_shadow_discovery(**kwargs)
    result_b = await run_shadow_discovery(**kwargs)
    assert result_a.candidates[0].relevance_validation.relevance_score == result_b.candidates[0].relevance_validation.relevance_score
    assert result_a.top_candidate_ids != [] and result_b.top_candidate_ids != []


@pytest.mark.asyncio
async def test_91_m4_adds_no_extra_image_fetch(pinned, monkeypatch: pytest.MonkeyPatch) -> None:
    server, routes = pinned
    routes["/article"] = lambda h: (
        h.send_response(200), h.send_header("Content-Type", "text/html"), h.end_headers(),
        h.wfile.write(_article_html(server, ["/img1.png"])),
    )
    routes["/img1.png"] = _image_route(_png_bytes())

    from integrations.http import safe_fetch as safe_fetch_module

    call_count = {"n": 0}
    original_fetch = safe_fetch_module.safe_fetch

    async def _counting(*args, **kwargs):
        call_count["n"] += 1
        return await original_fetch(*args, **kwargs)

    monkeypatch.setattr("services.image_intelligence.safe_fetch", _counting)
    await run_shadow_discovery(
        event_id=uuid4(), source_type=SourceType.RSS, content="text",
        article_url=_article_url(server), mode="shadow", event_title="GPT-5", source_name="TechSite",
    )
    # Exactly one article fetch + one image fetch - M4 issues zero additional requests.
    assert call_count["n"] == 2


def test_92_image_bytes_remain_transient() -> None:
    import inspect as _inspect

    import services.image_relevance as relevance_module

    source = _inspect.getsource(relevance_module)
    assert "open(" not in source
    assert ".write(" not in source
