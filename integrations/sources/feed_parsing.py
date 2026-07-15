"""Shared Atom/RSS entry parsing helpers, reused by any feedparser-based adapter.

Currently used by RSSSourceAdapter (RSS + Atom) and ArxivSourceAdapter (Atom,
via the arXiv API) - both parse feedparser entries and only need the date
logic, not a full second implementation of it.
"""
import calendar
from datetime import datetime, timezone
from time import struct_time

import feedparser


def parse_entry_date(entry: feedparser.FeedParserDict) -> datetime | None:
    """Read published/updated date from a feedparser entry as an aware UTC datetime."""
    parsed_time: struct_time | None = entry.get("published_parsed") or entry.get("updated_parsed")
    if parsed_time is None:
        return None

    return datetime.fromtimestamp(calendar.timegm(parsed_time), tz=timezone.utc)
