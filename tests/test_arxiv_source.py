"""Tests for integrations.sources.arxiv_source.ArxivSourceAdapter.

Uses httpx.MockTransport - never hits the real arXiv API.
"""
import httpx
import pytest

from database.models.news_source import NewsSource, SourceType
from integrations.sources.arxiv_source import ArxivSourceAdapter
from integrations.sources.base import SourceFetchContext

CONTEXT = SourceFetchContext(definition=None)

ARXIV_BODY = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2401.12345v1</id>
    <title>  A Paper About
      Something Interesting  </title>
    <summary>This paper studies something interesting in depth.</summary>
    <published>2024-01-15T10:30:00Z</published>
    <link href="http://arxiv.org/abs/2401.12345v1" rel="alternate" type="text/html"/>
    <link title="pdf" href="http://arxiv.org/pdf/2401.12345v1" rel="related" type="application/pdf"/>
  </entry>
</feed>
"""


def _source(url: str) -> NewsSource:
    return NewsSource(name="arXiv cs.AI", type=SourceType.NEWS_API, url=url)


def _patch_httpx_client(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    original_init = httpx.AsyncClient.__init__

    def patched_init(self: httpx.AsyncClient, *args, **kwargs) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original_init(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched_init)


@pytest.mark.asyncio
async def test_parses_entry_preferring_abstract_link_over_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=ARXIV_BODY)

    _patch_httpx_client(monkeypatch, handler)
    items = await ArxivSourceAdapter().fetch(
        _source("https://export.arxiv.org/api/query?search_query=cat:cs.AI&sortBy=submittedDate&sortOrder=descending"),
        CONTEXT,
    )

    assert len(items) == 1
    assert items[0].external_id == "http://arxiv.org/abs/2401.12345v1"
    assert items[0].url == "http://arxiv.org/abs/2401.12345v1"
    assert "pdf" not in (items[0].url or "")
    assert items[0].text == "This paper studies something interesting in depth."
    assert items[0].published_at is not None


@pytest.mark.asyncio
async def test_max_results_is_added_when_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=ARXIV_BODY)

    _patch_httpx_client(monkeypatch, handler)
    await ArxivSourceAdapter().fetch(_source("https://export.arxiv.org/api/query?search_query=cat:cs.AI"), CONTEXT)

    assert "max_results=50" in requested_urls[0]


@pytest.mark.asyncio
async def test_max_results_is_not_duplicated_when_present(monkeypatch: pytest.MonkeyPatch) -> None:
    requested_urls = []

    def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(str(request.url))
        return httpx.Response(200, content=ARXIV_BODY)

    _patch_httpx_client(monkeypatch, handler)
    await ArxivSourceAdapter().fetch(
        _source("https://export.arxiv.org/api/query?search_query=cat:cs.AI&max_results=25"), CONTEXT
    )

    assert requested_urls[0].count("max_results") == 1


@pytest.mark.asyncio
async def test_no_url_returns_empty() -> None:
    items = await ArxivSourceAdapter().fetch(_source(url=None), CONTEXT)
    assert items == []
