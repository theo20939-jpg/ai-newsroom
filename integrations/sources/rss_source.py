"""RSS/Atom adapter for the Source Collector.

Fetches the feed body with httpx and parses it with feedparser - feedparser
transparently handles both RSS and Atom, so one adapter covers both formats
without branching on which one a given source uses.
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


class RSSSourceAdapter(SourceAdapter):
    """Fetches recent entries from an RSS or Atom feed."""

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch source.url and parse its feed entries into RawNewsItem."""
        if not source.url:
            return []

        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(source.url)
            response.raise_for_status()

        parsed = feedparser.parse(response.content)
        items = [item for entry in parsed.entries if (item := self._to_raw_item(entry)) is not None]

        logger.info("Fetched %d entries from %s", len(items), source.url)
        return items

    @staticmethod
    def _to_raw_item(entry: feedparser.FeedParserDict) -> RawNewsItem | None:
        """Convert one feedparser entry into a RawNewsItem, or None to skip it."""
        external_id = entry.get("id") or entry.get("link")
        if not external_id:
            return None

        text = entry.get("summary") or entry.get("title")
        if not text:
            return None

        return RawNewsItem(
            external_id=external_id,
            text=text,
            url=entry.get("link"),
            published_at=parse_entry_date(entry),
        )
