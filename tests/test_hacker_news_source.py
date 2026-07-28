"""Tests for integrations.sources.hacker_news_source.HackerNewsSourceAdapter.

Uses httpx.MockTransport - never hits the real Hacker News API.
"""
import httpx
import pytest

from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from integrations.sources.hacker_news_source import HackerNewsSourceAdapter

CONTEXT = SourceFetchContext(definition=None)

TOPSTORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"

STORY_WITH_URL = {"id": 1, "title": "New AI model released", "url": "https://example.com/article", "time": 1700000000}
ASK_HN_STORY = {"id": 2, "title": "Ask HN: best editor?", "text": "Looking for &amp; opinions", "time": 1700000100}


def _source() -> NewsSource:
    return NewsSource(name="HN Front Page", type=SourceType.NEWS_API, url=TOPSTORIES_URL)


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


def _item_router(items_by_id: dict) -> "callable":
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == TOPSTORIES_URL:
            return httpx.Response(200, json=list(items_by_id.keys()))

        story_id = int(str(request.url).rsplit("/", 1)[-1].removesuffix(".json"))
        item = items_by_id.get(story_id)
        return httpx.Response(200, json=item)

    return handler


@pytest.mark.asyncio
async def test_story_with_external_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx_client(monkeypatch, _item_router({1: STORY_WITH_URL}))
    items = await HackerNewsSourceAdapter().fetch(_source(), CONTEXT)

    assert len(items) == 1
    assert items[0].external_id == "1"
    assert items[0].url == "https://example.com/article"
    assert items[0].text == "New AI model released"
    assert items[0].published_at is not None


@pytest.mark.asyncio
async def test_hacker_news_produces_no_native_image_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    """Phase 16 M1 (docs/phase16_m1_native_media_ingestion_report.md §8): the HN Firebase API has
    no image field for any item shape - an empty native_media_hints list is the correct, non-error
    M1 behavior."""
    _patch_httpx_client(monkeypatch, _item_router({1: STORY_WITH_URL}))
    items = await HackerNewsSourceAdapter().fetch(_source(), CONTEXT)
    assert len(items) == 1
    assert items[0].native_media_hints == []


@pytest.mark.asyncio
async def test_self_post_falls_back_to_discussion_url(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_httpx_client(monkeypatch, _item_router({2: ASK_HN_STORY}))
    items = await HackerNewsSourceAdapter().fetch(_source(), CONTEXT)

    assert len(items) == 1
    assert items[0].url == "https://news.ycombinator.com/item?id=2"
    assert items[0].text == "Looking for & opinions"  # html.unescape applied


@pytest.mark.asyncio
async def test_deleted_and_dead_and_null_stories_are_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    items_by_id = {
        1: STORY_WITH_URL,
        3: {"id": 3, "deleted": True},
        4: {"id": 4, "dead": True, "title": "dead story"},
        5: None,
    }
    _patch_httpx_client(monkeypatch, _item_router(items_by_id))
    items = await HackerNewsSourceAdapter().fetch(_source(), CONTEXT)

    assert len(items) == 1
    assert items[0].external_id == "1"


@pytest.mark.asyncio
async def test_story_without_title_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    items_by_id = {1: STORY_WITH_URL, 6: {"id": 6, "time": 1700000200}}
    _patch_httpx_client(monkeypatch, _item_router(items_by_id))
    items = await HackerNewsSourceAdapter().fetch(_source(), CONTEXT)

    assert len(items) == 1
    assert items[0].external_id == "1"


@pytest.mark.asyncio
async def test_no_url_returns_empty() -> None:
    items = await HackerNewsSourceAdapter().fetch(NewsSource(name="x", type=SourceType.NEWS_API, url=None), CONTEXT)
    assert items == []
