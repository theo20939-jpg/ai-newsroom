"""Tests for integrations.sources.bluesky_source.BlueskyTrendSourceAdapter.

Uses httpx.MockTransport - never hits the real Bluesky (AT Protocol) API.
"""
import httpx
import pytest
from pydantic import SecretStr

from core.config import settings
from integrations.sources.bluesky_source import BlueskyTrendSourceAdapter
from services.trend_fingerprint import TrendSourceNotConfigured
from services.trend_source_scope import TrendDiscoveryScope

SESSION_URL = "https://bsky.social/xrpc/com.atproto.server.createSession"
SEARCH_URL = "https://bsky.social/xrpc/app.bsky.feed.searchPosts"


def _scope(*terms: str) -> TrendDiscoveryScope:
    return TrendDiscoveryScope(ninja_verticals=list(terms))


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.mark.asyncio
async def test_raises_not_configured_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bluesky_handle", None)
    monkeypatch.setattr(settings, "bluesky_app_password", None)
    with pytest.raises(TrendSourceNotConfigured):
        await BlueskyTrendSourceAdapter().fetch_candidates(_scope("gadgets"))


@pytest.mark.asyncio
async def test_session_and_search_produce_real_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bluesky_handle", "ninja.bsky.social")
    monkeypatch.setattr(settings, "bluesky_app_password", SecretStr("fake-app-password"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SESSION_URL):
            return httpx.Response(200, json={"accessJwt": "fake-jwt", "handle": "ninja.bsky.social"})
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, json={"posts": [{
                "uri": "at://did:plc:abc/app.bsky.feed.post/xyz",
                "author": {"handle": "someone.bsky.social"},
                "record": {"text": "everyone's talking about the new foldable phone"},
                "likeCount": 900, "repostCount": 40, "replyCount": 12,
            }]})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await BlueskyTrendSourceAdapter().fetch_candidates(_scope("foldable phone"))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "bluesky"
    assert candidate.source_item_id == "at://did:plc:abc/app.bsky.feed.post/xyz"
    assert "foldable phone" in candidate.raw_topic_text
    assert candidate.engagement_snapshot == {"likeCount": 900, "repostCount": 40, "replyCount": 12}
    assert candidate.canonical_url == "https://bsky.app/profile/someone.bsky.social/post/xyz"


@pytest.mark.asyncio
async def test_session_failure_returns_no_candidates_never_fabricated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bluesky_handle", "ninja.bsky.social")
    monkeypatch.setattr(settings, "bluesky_app_password", SecretStr("wrong-password"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SESSION_URL):
            return httpx.Response(401, json={"error": "AuthenticationRequired"})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await BlueskyTrendSourceAdapter().fetch_candidates(_scope("gadgets"))

    assert candidates == []


@pytest.mark.asyncio
async def test_post_without_text_is_never_returned_as_a_fabricated_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bluesky_handle", "ninja.bsky.social")
    monkeypatch.setattr(settings, "bluesky_app_password", SecretStr("fake-app-password"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SESSION_URL):
            return httpx.Response(200, json={"accessJwt": "fake-jwt"})
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, json={"posts": [{
                "uri": "at://did:plc:abc/app.bsky.feed.post/xyz", "author": {"handle": "someone.bsky.social"},
                "record": {}, "likeCount": 5,
            }]})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await BlueskyTrendSourceAdapter().fetch_candidates(_scope("gadgets"))

    assert candidates == []


@pytest.mark.asyncio
async def test_duplicate_terms_never_double_count_the_same_post(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "bluesky_handle", "ninja.bsky.social")
    monkeypatch.setattr(settings, "bluesky_app_password", SecretStr("fake-app-password"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SESSION_URL):
            return httpx.Response(200, json={"accessJwt": "fake-jwt"})
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, json={"posts": [{
                "uri": "at://did:plc:abc/app.bsky.feed.post/xyz", "author": {"handle": "someone.bsky.social"},
                "record": {"text": "same post both times"}, "likeCount": 5,
            }]})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await BlueskyTrendSourceAdapter().fetch_candidates(_scope("gadgets", "tech"))

    assert len(candidates) == 1
