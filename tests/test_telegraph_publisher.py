"""TELEGRAPH LIVE PUBLISH: services.telegraph_publisher - the real Telegraph API client. Uses
httpx.MockTransport (mirrors tests/test_hacker_news_source.py's own established pattern) - never
hits the real telegra.ph API.
"""
from __future__ import annotations

import json

import httpx
import pytest

from core.config import settings
from services.telegraph_publisher import (
    TelegraphNotConfiguredError,
    TelegraphPublishError,
    build_telegraph_content_nodes,
    create_account,
    create_page,
)

_ARTICLE = {
    "headline": "Product Y Launch",
    "lead": "Company X released product Y.",
    "context": ["Background line one."],
    "timeline": ["2026-01-01: announced."],
    "confirmed_facts": ["Fact A.", "Fact B."],
    "analysis": ["This matters because of Z."],
    "implications": ["Users can now do W."],
    "background": ["Prior context."],
    "risks": ["Could change if X happens."],
    "conclusion": "The full impact remains to be seen.",
    "sources": ["https://example.com/source-a", "Trade publication interview"],
}


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.fixture(autouse=True)
def _configured_token(monkeypatch: pytest.MonkeyPatch):
    from pydantic import SecretStr

    monkeypatch.setattr(settings, "telegraph_access_token", SecretStr("test-token-ABC123"))
    monkeypatch.setattr(settings, "telegraph_author_name", "NINJA PULSE")
    monkeypatch.setattr(settings, "telegraph_author_url", None)


# ---------------------------------------------------------------------------------------------
# create_page / create_account - network behavior
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_page_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.telegra.ph/createPage"
        body = json.loads(request.content)
        assert body["access_token"] == "test-token-ABC123"
        assert body["title"] == "Product Y Launch"
        assert isinstance(body["content"], list)
        return httpx.Response(200, json={"ok": True, "result": {"path": "Product-Y-08-31", "url": "https://telegra.ph/Product-Y-08-31"}})

    _patch_httpx_client(monkeypatch, handler)
    page = await create_page(title="Product Y Launch", content=[{"tag": "p", "children": ["hi"]}])
    assert page.url == "https://telegra.ph/Product-Y-08-31"
    assert page.path == "Product-Y-08-31"


@pytest.mark.asyncio
async def test_create_page_unconfigured_token_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "telegraph_access_token", None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must never make a network call when unconfigured")

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphNotConfiguredError):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_page_malformed_api_response_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {}})  # missing url/path

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_page_non_json_response_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"not json")

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_page_api_reported_failure_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": False, "error": "CONTENT_TOO_BIG"})

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError, match="CONTENT_TOO_BIG"):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_page_network_error_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_page_timeout_fails_cleanly(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError):
        await create_page(title="X", content=[])


@pytest.mark.asyncio
async def test_create_account_success(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://api.telegra.ph/createAccount"
        return httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "short_name": "Ninja Pulse", "author_name": "NINJA PULSE",
                    "access_token": "brand-new-token", "auth_url": "https://edit.telegra.ph/auth/xyz",
                },
            },
        )

    _patch_httpx_client(monkeypatch, handler)
    account = await create_account(short_name="Ninja Pulse", author_name="NINJA PULSE")
    assert account.access_token == "brand-new-token"
    assert account.short_name == "Ninja Pulse"


# ---------------------------------------------------------------------------------------------
# Token never appears in logs / exceptions
# ---------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_token_never_appears_in_raised_error_text(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        token = body["access_token"]
        # Simulate a pathological API/error message that echoes the request's own token back -
        # _redact_token() must still strip it before the exception ever escapes this module.
        return httpx.Response(200, json={"ok": False, "error": f"bad token {token}"})

    _patch_httpx_client(monkeypatch, handler)
    with pytest.raises(TelegraphPublishError) as excinfo:
        await create_page(title="X", content=[])
    assert "test-token-ABC123" not in str(excinfo.value)
    assert "[REDACTED]" in str(excinfo.value)


@pytest.mark.asyncio
async def test_token_never_appears_in_logs(monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True, "result": {"path": "X-1", "url": "https://telegra.ph/X-1"}})

    _patch_httpx_client(monkeypatch, handler)
    with caplog.at_level("DEBUG"):
        await create_page(title="X", content=[])
    for record in caplog.records:
        assert "test-token-ABC123" not in record.getMessage()
        assert "test-token-ABC123" not in str(getattr(record, "__dict__", {}))


# ---------------------------------------------------------------------------------------------
# build_telegraph_content_nodes - deterministic converter
# ---------------------------------------------------------------------------------------------


def test_content_nodes_include_lead_paragraph() -> None:
    nodes = build_telegraph_content_nodes(_ARTICLE)
    assert {"tag": "p", "children": [_ARTICLE["lead"]]} in nodes


def test_content_nodes_render_sources_as_links_when_urls() -> None:
    nodes = build_telegraph_content_nodes(_ARTICLE)
    flat = json.dumps(nodes)
    assert '"tag": "a"' in flat
    assert "https://example.com/source-a" in flat


def test_content_nodes_render_non_url_sources_as_plain_text() -> None:
    nodes = build_telegraph_content_nodes(_ARTICLE)
    flat = json.dumps(nodes)
    assert "Trade publication interview" in flat


def test_content_nodes_headline_not_included_as_a_node() -> None:
    nodes = build_telegraph_content_nodes(_ARTICLE)
    flat = json.dumps(nodes)
    assert _ARTICLE["headline"] not in flat


def test_content_nodes_degrade_gracefully_on_malformed_list_field() -> None:
    malformed = {**_ARTICLE, "risks": "a single string, not a list"}
    nodes = build_telegraph_content_nodes(malformed)  # must not raise
    assert any("single string" in json.dumps(n) for n in nodes if isinstance(n, dict))


def test_content_nodes_never_empty_for_minimal_article() -> None:
    minimal = {
        "headline": "H", "lead": "", "context": [], "timeline": [], "confirmed_facts": [],
        "analysis": [], "implications": [], "background": [], "risks": [],
        "conclusion": "", "sources": [],
    }
    nodes = build_telegraph_content_nodes(minimal)
    assert len(nodes) >= 1


def test_content_nodes_use_only_allowed_tags() -> None:
    from services.telegraph_publisher import ALLOWED_NODE_TAGS

    def _walk(node: object) -> None:
        if isinstance(node, dict):
            assert node["tag"] in ALLOWED_NODE_TAGS
            for child in node.get("children", []) or []:
                _walk(child)

    for node in build_telegraph_content_nodes(_ARTICLE):
        _walk(node)
