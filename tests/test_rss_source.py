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


# Phase 16 M1 (docs/phase16_m1_native_media_ingestion_report.md): adapter-level wiring - proves
# _to_raw_item() actually calls services.image_intelligence.extract_rss_native_media() and
# threads its result onto RawNewsItem.native_media_hints (see tests/test_image_intelligence.py
# for the extraction logic itself).
INLINE_IMAGE_BODY = b"""<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example Feed</title>
    <item>
      <title>Post with an image</title>
      <link>https://example.com/with-image</link>
      <guid>https://example.com/with-image</guid>
      <description>&lt;p&gt;Body &lt;img src="https://cdn.example.com/inline.jpg"/&gt;&lt;/p&gt;</description>
      <pubDate>Mon, 01 Jan 2024 12:00:00 GMT</pubDate>
    </item>
  </channel>
</rss>
"""


@pytest.mark.asyncio
async def test_fetch_populates_native_media_hints_for_inline_image(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=INLINE_IMAGE_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://example.com/feed.rss"), CONTEXT)

    assert len(items) == 1
    assert len(items[0].native_media_hints) == 1
    assert items[0].native_media_hints[0].remote_url == "https://cdn.example.com/inline.jpg"


@pytest.mark.asyncio
async def test_fetch_populates_no_hints_when_no_native_media_present(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=RSS_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://example.com/feed.rss"), CONTEXT)

    assert all(item.native_media_hints == [] for item in items)


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    """Route httpx.AsyncClient through a MockTransport for the duration of a test."""
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


# Real production forensic (2026-08-15): feeds returning 301/302/307/308 to a valid new
# location were being counted as hard source failures because httpx.AsyncClient defaulted to
# follow_redirects=False, and raise_for_status() raises on an unfollowed 3xx. These regression
# tests prove the fix (integrations/sources/rss_source.py: follow_redirects=True,
# max_redirects=MAX_REDIRECTS).


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [301, 302, 307, 308])
async def test_fetch_follows_single_redirect_to_valid_feed(
    monkeypatch: pytest.MonkeyPatch, status_code: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/old-feed.rss":
            return httpx.Response(status_code, headers={"Location": "https://example.com/new-feed.rss"})
        return httpx.Response(200, content=RSS_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source("https://example.com/old-feed.rss"), CONTEXT)

    assert len(items) == 2
    assert items[0].external_id == "https://example.com/first"


@pytest.mark.asyncio
async def test_fetch_follows_bounded_redirect_chain(monkeypatch: pytest.MonkeyPatch) -> None:
    """A chain within MAX_REDIRECTS still succeeds - the bound rejects only pathological chains."""
    hops = ["https://example.com/hop0", "https://example.com/hop1", "https://example.com/hop2"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url in hops:
            next_index = hops.index(url) + 1
            if next_index < len(hops):
                return httpx.Response(301, headers={"Location": hops[next_index]})
            return httpx.Response(301, headers={"Location": "https://example.com/feed.rss"})
        return httpx.Response(200, content=RSS_BODY)

    _patch_httpx_client(monkeypatch, handler)

    items = await RSSSourceAdapter().fetch(_source(hops[0]), CONTEXT)

    assert len(items) == 2


@pytest.mark.asyncio
async def test_fetch_rejects_redirect_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        other = "https://example.com/b" if url == "https://example.com/a" else "https://example.com/a"
        return httpx.Response(302, headers={"Location": other})

    _patch_httpx_client(monkeypatch, handler)

    with pytest.raises(httpx.TooManyRedirects):
        await RSSSourceAdapter().fetch(_source("https://example.com/a"), CONTEXT)


@pytest.mark.asyncio
async def test_fetch_rejects_redirect_chain_beyond_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        n = int(str(request.url).rsplit("/", 1)[-1])
        return httpx.Response(301, headers={"Location": f"https://example.com/hop/{n + 1}"})

    _patch_httpx_client(monkeypatch, handler)

    with pytest.raises(httpx.TooManyRedirects):
        await RSSSourceAdapter().fetch(_source("https://example.com/hop/0"), CONTEXT)


@pytest.mark.asyncio
async def test_fetch_raises_on_final_404(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404)

    _patch_httpx_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await RSSSourceAdapter().fetch(_source("https://example.com/missing.rss"), CONTEXT)
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_fetch_raises_on_final_403(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    _patch_httpx_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await RSSSourceAdapter().fetch(_source("https://example.com/forbidden.rss"), CONTEXT)
    assert exc_info.value.response.status_code == 403


@pytest.mark.asyncio
async def test_fetch_redirect_to_404_still_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """A redirect must not mask a genuinely dead target at the end of the chain."""

    def handler(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://example.com/moved.rss":
            return httpx.Response(301, headers={"Location": "https://example.com/gone.rss"})
        return httpx.Response(404)

    _patch_httpx_client(monkeypatch, handler)

    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        await RSSSourceAdapter().fetch(_source("https://example.com/moved.rss"), CONTEXT)
    assert exc_info.value.response.status_code == 404


@pytest.mark.asyncio
async def test_fetch_successful_redirect_does_not_trigger_retry(monkeypatch: pytest.MonkeyPatch) -> None:
    """services.collector._fetch_with_retry only retries when adapter.fetch() raises - a
    followed redirect must resolve inside the single httpx.AsyncClient.get() call and never
    raise, so this proves the retry path is never even entered for a successful redirect."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        if str(request.url) == "https://example.com/old-feed.rss":
            return httpx.Response(301, headers={"Location": "https://example.com/new-feed.rss"})
        return httpx.Response(200, content=RSS_BODY)

    _patch_httpx_client(monkeypatch, handler)

    from services.collector import _fetch_with_retry

    items = await _fetch_with_retry(
        RSSSourceAdapter(), _source("https://example.com/old-feed.rss"), CONTEXT
    )

    assert len(items) == 2
    # One request per hop (old-feed -> new-feed), never multiplied by a retry attempt.
    assert call_count == 2


# A narrow scheme-safety test (redirect Location switching to file://, ftp://, etc.) was
# evaluated and deliberately NOT added: proving it faithfully requires a real, unconfigured
# httpx.AsyncClient's default per-scheme transport routing (no mount matches a non-http(s)
# scheme, so it fails client-side with UnsupportedProtocol before any network I/O) - but this
# repo's own tests/conftest.py Barrier 3 network-egress guard (`_is_mock_transport`) only
# recognizes a client whose single top-level `_transport` attribute is itself a MockTransport
# instance, which is exactly the fallback httpx uses for any scheme with no matching mount -
# making a client that both satisfies the guard and genuinely lacks a route for file://
# self-contradictory to construct. Reproducing the real behavior would require weakening or
# reshaping that shared guard, which is out of this task's scope. See the MAX_REDIRECTS comment
# in integrations/sources/rss_source.py for the documented (not fixed) limitation this would
# have covered.


@pytest.mark.asyncio
async def test_fetch_with_retry_still_retries_and_isolates_a_real_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Source-failure isolation and retry behavior for a genuine (non-redirect) failure must be
    unchanged: a persistently-403 source is retried MAX_FETCH_ATTEMPTS times and then raises,
    without affecting unrelated sources (services.collector._process_source/run_collection_cycle
    already isolate one source's exception from the rest of the cycle - this proves the adapter
    side of that contract still raises so isolation has something to catch)."""
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(403)

    _patch_httpx_client(monkeypatch, handler)
    monkeypatch.setattr("services.collector.RETRY_BACKOFF_SECONDS", 0.0)

    from services.collector import MAX_FETCH_ATTEMPTS, _fetch_with_retry

    with pytest.raises(httpx.HTTPStatusError):
        await _fetch_with_retry(RSSSourceAdapter(), _source("https://example.com/forbidden.rss"), CONTEXT)

    assert call_count == MAX_FETCH_ATTEMPTS
