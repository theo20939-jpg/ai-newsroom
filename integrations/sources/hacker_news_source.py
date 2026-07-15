"""Hacker News adapter for the Source Collector.

Uses the official, public, unauthenticated Firebase-backed HN API
(https://github.com/HackerNews/API). Top story ids come back as a single
list of up to 500 entries; item bodies must be fetched individually, so this
caps how many are fetched per cycle and bounds concurrency rather than
fetching all 500 every run.
"""
import asyncio
import html
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from database.models.news_source import NewsSource
from integrations.sources.base import SourceAdapter, SourceFetchContext
from schemas.raw_news_item import RawNewsItem

logger = logging.getLogger(__name__)

FETCH_TIMEOUT_SECONDS = 15.0
TOP_STORY_LIMIT = 30
MAX_CONCURRENT_REQUESTS = 10
ITEM_URL_TEMPLATE = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"


class HackerNewsSourceAdapter(SourceAdapter):
    """Fetches item details for the current top N Hacker News stories."""

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch source.url (topstories.json) then the top N items it lists."""
        if not source.url:
            return []

        async with httpx.AsyncClient(timeout=FETCH_TIMEOUT_SECONDS) as client:
            response = await client.get(source.url)
            response.raise_for_status()
            story_ids = response.json()

            if not isinstance(story_ids, list):
                logger.warning("Unexpected Hacker News response shape at %s, skipping", source.url)
                return []

            semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)
            results = await asyncio.gather(
                *(self._fetch_item(client, semaphore, story_id) for story_id in story_ids[:TOP_STORY_LIMIT])
            )

        items = [item for item in results if item is not None]
        logger.info("Fetched %d Hacker News stories", len(items))
        return items

    async def _fetch_item(
        self, client: httpx.AsyncClient, semaphore: asyncio.Semaphore, story_id: int
    ) -> RawNewsItem | None:
        """Fetch and convert one story's item details, bounded by the semaphore."""
        async with semaphore:
            response = await client.get(ITEM_URL_TEMPLATE.format(story_id=story_id))

        if response.status_code != 200:
            return None

        try:
            item = response.json()
        except ValueError:
            return None

        return self._to_raw_item(story_id, item)

    @staticmethod
    def _to_raw_item(story_id: int, item: dict[str, Any] | None) -> RawNewsItem | None:
        """Convert one HN item into a RawNewsItem, or None to skip it (null/deleted/dead)."""
        if not item or item.get("deleted") or item.get("dead"):
            return None

        raw_title = item.get("title")
        if not raw_title:
            return None
        title = html.unescape(raw_title)

        raw_text = item.get("text")
        text = html.unescape(raw_text) if raw_text else title

        url = item.get("url") or f"https://news.ycombinator.com/item?id={story_id}"
        published_at = datetime.fromtimestamp(item["time"], tz=timezone.utc) if item.get("time") else None

        return RawNewsItem(
            external_id=str(story_id),
            text=text,
            url=url,
            published_at=published_at,
        )
