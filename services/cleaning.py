"""Deterministic normalization of raw source items (Cleaning Service).

Provider-independent: knows nothing about Telegram, any other source, the
database, or NewsSource. Only decides whether a RawNewsItem has usable
content and, if so, normalizes it.
"""
import logging
from datetime import datetime

from pydantic import BaseModel

from schemas.raw_news_item import RawNewsItem

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 120


class CleanedItem(BaseModel):
    """A raw item after normalization, ready for hashing and storage by the Collector."""

    external_id: str
    title: str
    text: str
    url: str | None
    published_at: datetime | None


def clean_item(raw: RawNewsItem) -> CleanedItem | None:
    """Normalize a raw item into a CleanedItem, or None if it should be dropped.

    Drops items with no usable text (media-only posts, empty messages).
    """
    if raw.text is None:
        return None

    normalized_text = _normalize_whitespace(raw.text)
    if not normalized_text:
        return None

    return CleanedItem(
        external_id=raw.external_id,
        title=_extract_title(normalized_text),
        text=normalized_text,
        url=raw.url,
        published_at=raw.published_at,
    )


def _normalize_whitespace(text: str) -> str:
    """Collapse blank lines and trim whitespace from each line."""
    lines = [line.strip() for line in text.splitlines()]
    non_empty_lines = [line for line in lines if line]
    return "\n".join(non_empty_lines)


def _extract_title(normalized_text: str) -> str:
    """Take the first non-empty line, trimmed and capped at TITLE_MAX_LENGTH."""
    first_line = normalized_text.splitlines()[0]
    if len(first_line) <= TITLE_MAX_LENGTH:
        return first_line

    truncated = first_line[:TITLE_MAX_LENGTH]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated
