"""Tests for integrations.sources.rss_source.RSSSourceAdapter.

Uses httpx.MockTransport so these never hit the network - the adapter is
exercised against static RSS/Atom bodies instead of a live feed.
"""
import httpx
import pytest

from database.models.news_source import NewsSource, SourceType
from integrations.sources.base import SourceFetchContext
from integrations.sources.rss_source import RSSSourceAdapter

CONTEXT = SourceFetchContext(definition=None)

RSS_BODY = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>First post</title>
      <link>https://example.com/first</link>
      <guid>https://example.com/first</guid>
      <description>Body of the first post</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
    <item>
      <title>Second post</title>
      <link>https://example.com/second</link>
      <guid>https://example.com/second</guid>
      <description>Body of the second post</description>
      <pubDate>Tue, 02 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""

ATOM_BODY = b"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>Example Atom Feed</title>
  <entry>
    <title>Release 1.0</title>
    <link href="https://example.com/releases/1.0"/>
    <id>https://example.com/releases/1.0</id>
    <summary>Release notes for 1.0</summary>
    <updated>2024-01-01T12:00:00Z</updated>
  </entry>
</feed>
"""

# Shaped after the real, live-observed malformation (Phase 15 M0 discovery/observation
# report): Google News RSS wraps the real headline in an anchor inside <description>,
# while <title> itself stays a clean, readable headline.
GOOGLE_NEWS_STYLE_BODY = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Google News: Artificial Intelligence</title>
    <item>
      <title>OpenAI announces GPT-5 Turbo</title>
      <link>https://news.google.com/articles/abc</link>
      <guid>https://news.google.com/articles/abc</guid>
      <description>&lt;a href="https://news.google.com/articles/abc"&gt;OpenAI announces GPT-5 Turbo&lt;/a&gt;&amp;nbsp;&amp;nbsp;&lt;font color="#6f6f6f"&gt;Example News&lt;/font&gt;</description>
      <pubDate>Wed, 03 Jan 2024 09:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


def _source(url: str | None) -> NewsSource:
    return NewsSource(name="Test", type=SourceType.RSS, url=url)


@pytest.mark.asyncio
async def test_fetch_parses_rss_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://example.com/feed.rss"), CONTEXT)

    assert len(items) == 2
    assert items[0].external_id == "https://example.com/first"
    assert items[0].url == "https://example.com/first"
    assert items[0].title == "First post"
    assert items[0].text == "Body of the first post"
    assert items[0].published_at is not None


@pytest.mark.asyncio
async def test_fetch_parses_atom_entries(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ATOM_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://example.com/releases.atom"), CONTEXT)

    assert len(items) == 1
    assert items[0].external_id == "https://example.com/releases/1.0"
    assert items[0].title == "Release 1.0"
    assert items[0].text == "Release notes for 1.0"


@pytest.mark.asyncio
async def test_fetch_captures_clean_title_separately_from_html_heavy_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Root-cause regression (Phase 15 M1): the adapter itself must pass through the
    feed's own <title> element, not only the HTML-wrapped <description> - normalization
    and validation of the two candidates is services.cleaning's job, but the adapter
    must not silently drop the clean candidate before cleaning ever sees it."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=GOOGLE_NEWS_STYLE_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://news.google.com/rss"), CONTEXT)

    assert len(items) == 1
    assert items[0].title == "OpenAI announces GPT-5 Turbo"
    assert items[0].text.startswith("<a href=")


@pytest.mark.asyncio
async def test_fetch_returns_empty_list_for_missing_url() -> None:
    items = await RSSSourceAdapter().fetch(_source(url=None), CONTEXT)
    assert items == []


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route httpx.AsyncClient through a MockTransport for the duration of a test."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)
