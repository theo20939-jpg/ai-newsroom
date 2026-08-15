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

# Real production forensic (2026-08-15): feeds that moved to a new URL respond with a normal
# 301/302/307/308 redirect. httpx defaults to follow_redirects=False, which means
# response.raise_for_status() treats an unfollowed 3xx as an error (httpx raises for any
# non-2xx when redirects were not followed, not only 4xx/5xx) - every such feed was retried
# 3x by services.collector._fetch_with_retry and then counted as a hard source failure,
# indistinguishable from a real 403/404. Following redirects here (bounded, so a redirect loop
# still fails deterministically instead of hanging) fixes that.
#
# Documented, NOT fixed, remaining limitation: this adapter has no redirect-target SSRF/
# private-IP validation (unlike integrations/http/safe_fetch.py's DNS-pinned path, used only by
# Image Intelligence) - neither before nor after this change. Before, that gap was inert for
# redirects specifically, because a 3xx was never followed at all; the only fetch destination
# was ever the exact configured source URL. After this change, whatever Location header that
# URL's operator (or a man-in-the-middle) returns is now actually fetched, bounded only by
# MAX_REDIRECTS and http(s)-scheme routing (httpx's default AsyncClient only mounts http(s)
# transports, so a same-request scheme change - e.g. to file:///ftp:// - fails safely with
# UnsupportedProtocol; see tests/test_rss_source.py's dedicated scheme-safety test) - a
# same-scheme redirect straight to a private/internal address is not rejected. Practical risk is
# bounded (feed URLs come from the curated, admin-maintained source pack, never user input; a
# redirect to an internal IP requires either a compromised/misconfigured feed or an on-path
# attacker), but it is a real, new reachable-destination surface this change introduces, not
# zero new surface - migrating this adapter onto safe_fetch() would close it but is a materially
# larger change than this fix, left for a separate, dedicated pass.
MAX_REDIRECTS = 5


class RSSSourceAdapter(SourceAdapter):
    """Fetches recent entries from an RSS or Atom feed."""

    async def fetch(self, source: NewsSource, context: SourceFetchContext) -> list[RawNewsItem]:
        """Fetch source.url and parse its feed entries into RawNewsItem."""
        if not source.url:
            return []

        async with httpx.AsyncClient(
            timeout=FETCH_TIMEOUT_SECONDS, follow_redirects=True, max_redirects=MAX_REDIRECTS
        ) as client:
            response = await client.get(source.url)
            response.raise_for_status()
            if response.history:
                logger.info(
                    "Followed %d redirect(s) fetching %s -> %s",
                    len(response.history),
                    source.url,
                    response.url,
                )

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
