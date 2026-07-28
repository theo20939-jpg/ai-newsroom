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
from schemas.image_candidate import NativeMediaHint
from schemas.raw_news_item import RawNewsItem
from services.image_intelligence import extract_rss_native_media

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

        article_url = entry.get("link")
        return RawNewsItem(
            external_id=external_id,
            title=entry.get("title"),
            text=text,
            url=article_url,
            published_at=parse_entry_date(entry),
            # Phase 16 M1: native media_content/media_thumbnail/enclosure/inline-<img> metadata
            # only - zero additional network request (docs/phase16_m1_native_media_ingestion_
            # report.md). Relative image URLs are resolved against this same entry's article_url.
            # Extraction failure must never break collection of the entry's text.
            native_media_hints=_safe_extract_native_media(entry, article_url),
        )


def _safe_extract_native_media(
    entry: feedparser.FeedParserDict, article_url: str | None
) -> list[NativeMediaHint]:
    try:
        return extract_rss_native_media(entry, article_url=article_url)
    except Exception:
        logger.warning("rss_native_media_extraction_failed", extra={"entry_link": article_url})
        return []
