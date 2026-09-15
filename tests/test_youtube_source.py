"""Tests for integrations.sources.youtube_source.YouTubeTrendSourceAdapter.

Uses httpx.MockTransport - never hits the real YouTube Data API.
"""
import httpx
import pytest
from pydantic import SecretStr

from core.config import settings
from integrations.sources.youtube_source import YouTubeTrendSourceAdapter
from services.trend_fingerprint import TrendSourceNotConfigured
from services.trend_source_scope import TrendDiscoveryScope

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"


def _scope(*terms: str) -> TrendDiscoveryScope:
    return TrendDiscoveryScope(ninja_verticals=list(terms))


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.mark.asyncio
async def test_raises_not_configured_without_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_api_key", None)
    with pytest.raises(TrendSourceNotConfigured):
        await YouTubeTrendSourceAdapter().fetch_candidates(_scope("gadgets"))


@pytest.mark.asyncio
async def test_search_and_video_details_produce_real_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_api_key", SecretStr("fake-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "abc123"}}]})
        if str(request.url).startswith(VIDEOS_URL):
            return httpx.Response(200, json={"items": [{
                "id": "abc123",
                "snippet": {"title": "New foldable phone unboxing", "description": "first look"},
                "statistics": {"viewCount": "50000", "likeCount": "1200", "commentCount": "not_a_number"},
            }]})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await YouTubeTrendSourceAdapter().fetch_candidates(_scope("foldable phone"))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.source == "youtube"
    assert candidate.source_item_id == "abc123"
    assert "foldable phone" in candidate.raw_topic_text
    # A non-numeric statistic value is never coerced into a fabricated int.
    assert candidate.engagement_snapshot == {"viewCount": 50000, "likeCount": 1200}
    assert candidate.canonical_url == "https://www.youtube.com/watch?v=abc123"


@pytest.mark.asyncio
async def test_search_failure_for_one_term_does_not_crash_the_whole_fetch(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_api_key", SecretStr("fake-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(500, json={"error": "quota exceeded"})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await YouTubeTrendSourceAdapter().fetch_candidates(_scope("gadgets"))

    assert candidates == []


@pytest.mark.asyncio
async def test_video_missing_a_title_is_never_returned_as_a_fabricated_candidate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "youtube_api_key", SecretStr("fake-key"))

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url).startswith(SEARCH_URL):
            return httpx.Response(200, json={"items": [{"id": {"videoId": "no-title"}}]})
        if str(request.url).startswith(VIDEOS_URL):
            return httpx.Response(200, json={"items": [{"id": "no-title", "snippet": {}, "statistics": {}}]})
        raise AssertionError(f"unexpected URL {request.url}")

    _patch_httpx_client(monkeypatch, handler)
    candidates = await YouTubeTrendSourceAdapter().fetch_candidates(_scope("gadgets"))

    assert candidates == []
