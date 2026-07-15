"""arXiv adapter for the Source Collector.

The arXiv API (https://arxiv.org/help/api/user-manual) returns Atom, the
same format RSSSourceAdapter already parses via feedparser - this adapter
reuses the same entry-date helper rather than re-implementing it, and adds
only what's arXiv-specific: making sure max_results is set, and preferring
the abstract-page link over the PDF link that arXiv also includes.
"""
import logging

import feedparser
import httpx

from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter, SourceFetchContext
from integrations.sources.feed_parsing import parse_entry_date
from schemas.raw_news_item import RawNewsItem

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
MAX_RESULTS = 50
USER_AGENT = "ai-newsroom"


class ArxivSourceAdapter(SourceAdapter):
    """Fetches recent papers from an arXiv API query feed."""

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch source.url (with max_results applied) and parse its Atom entries."""
        if not source.url:
            return []

        url = self._with_max_results(source.url)

        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS, headers={"User-Agent": USER_AGENT}) as client:
            response = await client.get(url)
            response.raise_for_status()

        parsed = feedparser.parse(response.content)
        items = [item for entry in parsed.entries if (item := self._to_raw_item(entry)) is not None]

        logger.info("Fetched %d papers from %s", len(items), url)
        return items

    @staticmethod
    def _with_max_results(url: str) -> str:
        """Add max_results to the query if the configured url doesn't already set it."""
        parsed_url = httpx.URL(url)
        if "max_results" in parsed_url.params:
            return url
        return str(parsed_url.copy_merge_params({"max_results": str(MAX_RESULTS)}))

    @staticmethod
    def _to_raw_item(entry: feedparser.FeedParserDict) -> RawNewsItem | None:
        """Convert one Atom entry into a RawNewsItem, or None to skip it."""
        external_id = entry.get("id")
        if not external_id:
            return None

        text = _normalize_whitespace(entry.get("summary") or entry.get("title") or "")
        if not text:
            return None

        return RawNewsItem(
            external_id=external_id,
            text=text,
            url=_abstract_page_link(entry),
            published_at=parse_entry_date(entry),
        )


def _abstract_page_link(entry: feedparser.FeedParserDict) -> str | None:
    """Prefer the rel="alternate" (abstract page) link over the PDF link arXiv also lists."""
    for link in entry.get("links", []) or []:
        if link.get("rel") == "alternate":
            return link.get("href")
    return entry.get("link")


def _normalize_whitespace(text: str) -> str:
    """Collapse arXiv's line-wrapped title/summary whitespace into a single line."""
    return " ".join(text.split())
