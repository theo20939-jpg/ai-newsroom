"""Deterministic normalization of raw source items (Cleaning Service).

Provider-independent: knows nothing about Telegram, any other source, the
database, or NewsSource. Only decides whether a RawNewsItem has usable
content and, if so, normalizes it.

Phase 15 M1: title normalization is deterministic only - HTML tags/entities
are stripped/unescaped and whitespace is collapsed, but no title is ever
invented or repaired by an LLM. An item whose title cannot be reduced to
readable text (empty, HTML-only, or a bare URL) is dropped here rather than
stored with a malformed title - see is_valid_title(), also reused by
services.triage_orchestrator as a defense-in-depth gate for events that
reach Triage with an invalid title (e.g. collected before this fix).

Phase 15 M3: the four engagement fields (views/forwards/replies/reactions_count) are passed
through verbatim from RawNewsItem to CleanedItem - no normalization, no fabrication. `None`
stays `None` (metric unavailable from this source); a real `0` stays `0` (observed, confirmed
zero). Nothing in this module ever converts one into the other.
"""
import html
import logging
import re
from datetime import datetime

from pydantic import BaseModel

from schemas.raw_news_item import RawNewsItem

logger = logging.getLogger(__name__)

TITLE_MAX_LENGTH = 120

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_BARE_URL_PATTERN = re.compile(r"^https?://\S+$", re.IGNORECASE)


class CleanedItem(BaseModel):
    """A raw item after normalization, ready for hashing and storage by the Collector."""

    external_id: str
    title: str
    text: str
    url: str | None
    published_at: datetime | None
    views_count: int | None
    forwards_count: int | None
    replies_count: int | None
    reactions_count: int | None


def clean_item(raw: RawNewsItem) -> CleanedItem | None:
    """Normalize a raw item into a CleanedItem, or None if it should be dropped.

    Drops items with no usable text (media-only posts, empty messages) and
    items whose title cannot be reduced to valid, readable text (see
    is_valid_title()) - never invents or repairs a title.
    """
    if raw.text is None:
        return None

    normalized_text = _normalize_whitespace(raw.text)
    if not normalized_text:
        return None

    title = _select_title(raw.title, normalized_text)
    if title is None:
        return None

    return CleanedItem(
        external_id=raw.external_id,
        title=title,
        text=normalized_text,
        url=raw.url,
        published_at=raw.published_at,
        views_count=raw.views_count,
        forwards_count=raw.forwards_count,
        replies_count=raw.replies_count,
        reactions_count=raw.reactions_count,
    )


def _select_title(raw_title: str | None, normalized_text: str) -> str | None:
    """Prefer an explicit title candidate; fall back to the text's first line.

    Returns None - never a fabricated placeholder - if neither candidate
    reduces to valid, readable text.
    """
    if raw_title:
        candidate = _clean_title_text(raw_title)
        if is_valid_title(candidate):
            return candidate

    fallback = _clean_title_text(_extract_title(normalized_text))
    return fallback if is_valid_title(fallback) else None


def is_valid_title(title: str) -> bool:
    """True iff title is non-empty, readable text - not HTML-only, not a bare URL.

    Deliberately conservative: only rejects titles that are structurally
    unusable (matches the malformed-title patterns Phase 15 M0 documented,
    e.g. '<a', '<details open="">'), never a real headline merely because it
    is short or unusual. Any remaining '<'/'>' after tag-stripping means an
    unclosed/malformed tag fragment (valid feed XML always entity-escapes a
    literal angle bracket in character data), so that alone is disqualifying
    even though it slips past a strict tag-only regex.
    """
    stripped = title.strip()
    if not stripped:
        return False
    if _BARE_URL_PATTERN.match(stripped):
        return False
    without_tags = _HTML_TAG_PATTERN.sub("", stripped).strip()
    if not without_tags or "<" in without_tags or ">" in without_tags:
        return False
    return any(character.isalnum() for character in without_tags)


def _clean_title_text(candidate: str) -> str:
    """Strip HTML tags, unescape entities, collapse whitespace, cap length.

    Tags are stripped before entities are unescaped: real markup is never
    entity-escaped in valid feed XML, so this order can't mistake an
    unescaped "<"/">" produced by a literal "&lt;"/"&gt;" in the source text
    for a tag once stripping has already happened.
    """
    without_tags = _HTML_TAG_PATTERN.sub("", candidate)
    unescaped = html.unescape(without_tags)
    collapsed = " ".join(unescaped.split())
    return _truncate(collapsed)


def _normalize_whitespace(text: str) -> str:
    """Collapse blank lines and trim whitespace from each line."""
    lines = [line.strip() for line in text.splitlines()]
    non_empty_lines = [line for line in lines if line]
    return "\n".join(non_empty_lines)


def _extract_title(normalized_text: str) -> str:
    """Take the first non-empty line as the title candidate for _clean_title_text().

    Deliberately not truncated here - truncating before _clean_title_text()
    strips HTML tags could cut a tag in half and leave an unclosed fragment
    in the output.
    """
    return normalized_text.splitlines()[0]


def _truncate(text: str) -> str:
    """Cap text at TITLE_MAX_LENGTH, breaking on the last whole word where possible."""
    if len(text) <= TITLE_MAX_LENGTH:
        return text

    truncated = text[:TITLE_MAX_LENGTH]
    last_space = truncated.rfind(" ")
    return truncated[:last_space] if last_space > 0 else truncated
