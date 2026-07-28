"""Phase 16 M1: Image Intelligence - zero-download, zero-LLM native media candidate discovery
(docs/phase16_m1_native_media_ingestion_report.md).

Two independent call sites share every function in this module (docs/phase16_image_intelligence_
discovery_report.md §11, §20):

1. services/collector.py, after a NewsEvent is flushed (real `event.id` available) - consumes
   the full source-native hints an adapter produced at fetch time (`extract_telegram_native_media`/
   `extract_rss_native_media`) and logs a structured audit trail. Nothing here is persisted to
   PostgreSQL: NewsEvent has no image/media column and M1 adds no migration (discovery report
   §11/§21) - this is observability only, not durable storage.
2. capabilities/executor.py, at the CONTENT_GENERATION "copywriting" step - best-effort
   reconstruction using only what NewsEvent already durably persists (`reconstruct_hints_from_
   content`), since the adapter-time hints from (1) never reach this later, separate worker
   process. This intentionally recovers RSS inline-image candidates (real HTML already stored in
   `NewsEvent.content`) and legitimately finds nothing for Telegram/GitHub/HN/arXiv events -
   documented as a known M1 limitation, not a bug (see the M1 report §21).

No network access, no image byte download, no LLM/provider call anywhere in this module.
"""
import hashlib
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from database.models.news_source import SourceType
from schemas.image_candidate import (
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    ImageIntelligenceResult,
    NativeMediaHint,
    TelegramReference,
)

logger = logging.getLogger(__name__)

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_CAPTION_LENGTH = 500
_MAX_ALT_TEXT_LENGTH = 300
_MAX_FILE_NAME_LENGTH = 200
_LAZY_LOAD_ATTRS = ("data-src", "data-original", "data-lazy-src")

# Telethon document attribute type names that disqualify an image-mimetype document from being an
# image candidate (docs/phase16_image_intelligence_discovery_report.md's own M1 task brief §3.5:
# "Video, audio, stickers, voice, and other document types must not become image candidates").
_DISQUALIFYING_DOCUMENT_ATTRIBUTES = {
    "DocumentAttributeSticker",
    "DocumentAttributeVideo",
    "DocumentAttributeAudio",
}


# ---------------------------------------------------------------------------
# Telegram (Telethon) native extraction - operates on an already-fetched Message, zero network.
# ---------------------------------------------------------------------------


def extract_telegram_native_media(message: Any) -> list[NativeMediaHint]:
    """Extract native photo/document hints from one already-fetched Telethon Message.

    Never downloads media, never accesses `.access_hash`/`.file_reference` (session-bound,
    excluded by design - see schemas.image_candidate.TelegramReference's own docstring). Each
    extractor is isolated in its own try/except so one malformed/unexpected attribute shape can
    never crash the other, or the caller (test: "missing optional media attributes do not crash
    extraction")."""
    message_id = getattr(message, "id", None)
    hints: list[NativeMediaHint] = []

    try:
        photo_hint = _telegram_photo_hint(message)
        if photo_hint is not None:
            hints.append(photo_hint)
    except Exception:
        logger.warning("telegram_photo_extraction_failed", extra={"message_id": message_id})

    try:
        document_hint = _telegram_document_hint(message)
        if document_hint is not None:
            hints.append(document_hint)
    except Exception:
        logger.warning("telegram_document_extraction_failed", extra={"message_id": message_id})

    return hints


def _telegram_photo_hint(message: Any) -> NativeMediaHint | None:
    photo = getattr(message, "photo", None)
    if photo is None:
        return None

    width = height = None
    for size in getattr(photo, "sizes", None) or []:
        w = getattr(size, "w", None)
        h = getattr(size, "h", None)
        if w is None or h is None:
            continue  # e.g. PhotoStrippedSize carries no real dimensions
        if width is None or (w * h) > (width * height):
            width, height = w, h

    return NativeMediaHint(
        discovery_method=ImageDiscoveryMethod.TELEGRAM_PHOTO,
        declared_width=width,
        declared_height=height,
        caption=_safe_caption(message),
        telegram=TelegramReference(
            message_id=message.id,
            grouped_id=getattr(message, "grouped_id", None),
            media_kind="photo",
            media_id=getattr(photo, "id", None),
        ),
    )


def _telegram_document_hint(message: Any) -> NativeMediaHint | None:
    document = getattr(message, "document", None)
    if document is None:
        return None

    mime_type = getattr(document, "mime_type", None) or ""
    if not mime_type.startswith("image/"):
        return None  # not an image document at all

    attributes = getattr(document, "attributes", None) or []
    attribute_type_names = {type(attribute).__name__ for attribute in attributes}
    if attribute_type_names & _DISQUALIFYING_DOCUMENT_ATTRIBUTES:
        return None  # sticker/video/audio sent as a document - never an image candidate

    width = height = None
    file_name = None
    for attribute in attributes:
        w = getattr(attribute, "w", None)
        h = getattr(attribute, "h", None)
        if w is not None and h is not None:
            width, height = w, h
        raw_name = getattr(attribute, "file_name", None)
        if raw_name:
            file_name = _sanitize_file_name(raw_name)

    return NativeMediaHint(
        discovery_method=ImageDiscoveryMethod.TELEGRAM_DOCUMENT,
        declared_width=width,
        declared_height=height,
        declared_mime_type=mime_type,
        caption=_safe_caption(message),
        telegram=TelegramReference(
            message_id=message.id,
            grouped_id=getattr(message, "grouped_id", None),
            media_kind="document",
            media_id=getattr(document, "id", None),
            file_name=file_name,
        ),
    )


def _safe_caption(message: Any) -> str | None:
    text = getattr(message, "text", None)
    if not text:
        return None
    return text[:_MAX_CAPTION_LENGTH]


def _sanitize_file_name(raw_name: str) -> str | None:
    """Basename only, no path separators/traversal, bounded length - metadata-stage safety only
    (never used to construct a filesystem path in M1, since nothing is downloaded yet)."""
    candidate = raw_name.replace("\\", "/").rsplit("/", 1)[-1].strip()
    candidate = "".join(ch for ch in candidate if ch.isprintable())
    if not candidate or candidate in (".", ".."):
        return None
    return candidate[:_MAX_FILE_NAME_LENGTH]


# ---------------------------------------------------------------------------
# RSS (feedparser) native extraction - operates on an already-fetched entry, zero network.
# ---------------------------------------------------------------------------


def extract_rss_native_media(entry: Mapping[str, Any], *, article_url: str | None) -> list[NativeMediaHint]:
    """Extract native media hints from one already-fetched feedparser entry.

    Priority order matches docs/phase16_image_intelligence_discovery_report.md §5's "RSS source
    priority" hypothesis: article-level media_content, then image enclosure, then media_thumbnail,
    then inline content image - `discovery_order` on each hint preserves this for later ranking.
    Feed-level logo/icon is architecturally excluded: this function only ever receives one entry,
    never `feedparser.parse(...).feed` (the channel-level object logos live on) - so a feed logo
    can never be mistaken for an article image here, by construction.
    """
    hints: list[NativeMediaHint] = []
    order = 0

    for media in _safe_list(entry, "media_content"):
        try:
            hint = _media_content_hint(media, order)
        except Exception:
            hint = None
        if hint is not None:
            hints.append(hint)
            order += 1

    for enclosure in _safe_list(entry, "enclosures"):
        try:
            hint = _enclosure_hint(enclosure, order)
        except Exception:
            hint = None
        if hint is not None:
            hints.append(hint)
            order += 1

    for thumbnail in _safe_list(entry, "media_thumbnail"):
        try:
            hint = _media_thumbnail_hint(thumbnail, order)
        except Exception:
            hint = None
        if hint is not None:
            hints.append(hint)
            order += 1

    summary = entry.get("summary") if hasattr(entry, "get") else None
    hints.extend(_extract_inline_images(summary or "", base_url=article_url))

    return hints


def _safe_list(entry: Mapping[str, Any], key: str) -> list[Any]:
    value = entry.get(key) if hasattr(entry, "get") else None
    return list(value) if value else []


def _safe_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _media_content_hint(media: Mapping[str, Any], order: int) -> NativeMediaHint | None:
    medium = (media.get("medium") or "").lower()
    mime_type = (media.get("type") or "").lower()
    if medium not in ("", "image") and not mime_type.startswith("image/"):
        return None  # explicitly non-image medium (e.g. "video", "audio") and no image MIME either
    if medium == "" and not mime_type.startswith("image/"):
        return None  # no signal at all that this is an image
    url = media.get("url")
    if not url:
        return None
    return NativeMediaHint(
        discovery_method=ImageDiscoveryMethod.RSS_MEDIA_CONTENT,
        remote_url=url,
        declared_width=_safe_int(media.get("width")),
        declared_height=_safe_int(media.get("height")),
        declared_mime_type=mime_type or None,
    )


def _enclosure_hint(enclosure: Mapping[str, Any], order: int) -> NativeMediaHint | None:
    mime_type = (enclosure.get("type") or "").lower()
    if not mime_type.startswith("image/"):
        return None  # non-image enclosure (e.g. a podcast audio file) - not a candidate
    url = enclosure.get("href") or enclosure.get("url")
    if not url:
        return None
    return NativeMediaHint(
        discovery_method=ImageDiscoveryMethod.RSS_ENCLOSURE,
        remote_url=url,
        declared_mime_type=mime_type,
    )


def _media_thumbnail_hint(thumbnail: Mapping[str, Any], order: int) -> NativeMediaHint | None:
    url = thumbnail.get("url")
    if not url:
        return None
    return NativeMediaHint(
        discovery_method=ImageDiscoveryMethod.RSS_MEDIA_THUMBNAIL,
        remote_url=url,
        declared_width=_safe_int(thumbnail.get("width")),
        declared_height=_safe_int(thumbnail.get("height")),
    )


class _ImgTagCollector(HTMLParser):
    """Collects every `<img>` start tag's attributes. `convert_charrefs=True` (the default)
    already HTML-entity-decodes attribute values - no separate unescape step needed."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.images: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "img":
            return
        self.images.append({name.lower(): value for name, value in attrs if value is not None})


def _extract_inline_images(html_text: str, *, base_url: str | None) -> list[NativeMediaHint]:
    """Parse `<img>` tags out of already-received HTML (RSS `summary`/`content`, or - for the
    CONTENT_GENERATION-time reconstruction path - the already-persisted `NewsEvent.content`).
    Never fetches anything; malformed HTML degrades to an empty result, never a crash."""
    if not html_text or "<img" not in html_text.lower():
        return []

    parser = _ImgTagCollector()
    try:
        parser.feed(html_text)
    except Exception:
        logger.warning("inline_image_html_parse_failed")
        return []

    hints: list[NativeMediaHint] = []
    for attrs in parser.images:
        url, warnings = _resolve_img_url(attrs, base_url=base_url)
        if not url:
            continue
        alt = attrs.get("alt")
        hints.append(
            NativeMediaHint(
                discovery_method=ImageDiscoveryMethod.RSS_INLINE_IMAGE,
                remote_url=url,
                alt_text=(alt[:_MAX_ALT_TEXT_LENGTH] if alt else None),
                warnings=warnings,
            )
        )
    return hints


def _resolve_img_url(attrs: dict[str, str], *, base_url: str | None) -> tuple[str | None, list[str]]:
    """Lazy-load attributes win over `src` when present - common markup convention is a tiny
    placeholder in `src` and the real image in `data-src`/`data-original`/`data-lazy-src`."""
    warnings: list[str] = []
    chosen: str | None = None

    for attr_name in _LAZY_LOAD_ATTRS:
        if attrs.get(attr_name):
            chosen = attrs[attr_name]
            break

    srcset = attrs.get("srcset")
    if chosen is None and srcset:
        best = _best_srcset_candidate(srcset)
        if best is not None:
            chosen = best
        else:
            warnings.append("malformed_srcset_ignored")

    if chosen is None:
        chosen = attrs.get("src")

    if not chosen or not chosen.strip():
        return None, warnings

    resolved = urljoin(base_url, chosen.strip()) if base_url else chosen.strip()
    return resolved, warnings


def _best_srcset_candidate(srcset: str) -> str | None:
    """Prefer the candidate with the largest valid `Nw` width descriptor. Returns None (caller
    then falls back to `src`) when no candidate has a parseable `w` descriptor at all - density
    (`x`) descriptors alone are not a reliable size signal, so we deliberately don't guess."""
    best_url: str | None = None
    best_width = -1
    for part in srcset.split(","):
        tokens = part.strip().split()
        if len(tokens) < 2 or not tokens[1].endswith("w"):
            continue
        try:
            width = int(tokens[1][:-1])
        except ValueError:
            continue
        if width > best_width:
            best_width = width
            best_url = tokens[0]
    return best_url


# ---------------------------------------------------------------------------
# CONTENT_GENERATION-time reconstruction - only what's already durably persisted in NewsEvent.
# ---------------------------------------------------------------------------


def reconstruct_hints_from_content(content: str | None, article_url: str | None) -> list[NativeMediaHint]:
    """Best-effort candidate recovery at CONTENT_GENERATION time, using only `NewsEvent.content`/
    `NewsEvent.url` - the adapter-time hints from extract_telegram_native_media/extract_rss_
    native_media never reach this later, separate worker process (no migration exists to carry
    them - docs/phase16_image_intelligence_discovery_report.md §11/§21). This recovers real RSS
    inline-image candidates (the HTML is already stored verbatim in `content`) and correctly finds
    nothing for Telegram/GitHub/HN/arXiv events, since none of those ever put an `<img>` tag into
    `content` (confirmed live: 0/640 Telegram rows, 2/1593 NEWS_API rows contain `<img` - discovery
    report §8)."""
    return _extract_inline_images(content or "", base_url=article_url)


# ---------------------------------------------------------------------------
# Central consolidation - the single place identity, rejection, and dedup rules are applied.
# ---------------------------------------------------------------------------


def _validate_remote_url(url: str) -> str | None:
    """Return a rejection reason, or None if the URL passes metadata-stage validation. Never
    claims the URL is safe to download (that's M2's job) - only that it's a plausible http(s)
    location."""
    stripped = url.strip()
    if not stripped:
        return "empty_url"
    parsed = urlsplit(stripped)
    scheme = parsed.scheme.lower()
    if not scheme:
        return "missing_scheme"
    if scheme not in _ALLOWED_SCHEMES:
        return f"unsupported_scheme:{scheme}"
    if not parsed.netloc:
        return "malformed_url"
    return None


def _identity_key(hint: NativeMediaHint) -> tuple[str, ...]:
    """Deterministic, within-event duplicate-detection key. Telegram uses stable Telethon
    coordinates (never `access_hash`); RSS uses the exact validated URL - deliberately NOT
    canonicalized/stripped of query parameters (docs/phase16_image_intelligence_discovery_report.
    md §14: "prefer false duplicates remaining separate over incorrectly merging distinct
    assets" - some CDN query parameters select the actual image)."""
    if hint.telegram is not None:
        t = hint.telegram
        return ("telegram", str(t.message_id), str(t.grouped_id or ""), t.media_kind, str(t.media_id or ""))
    return ("url", (hint.remote_url or "").strip())


def _compute_candidate_id(event_id: UUID, discovery_method: ImageDiscoveryMethod, identity_key: tuple[str, ...]) -> str:
    """sha256 of event_id + discovery_method + identity - deterministic and idempotent (same
    source item processed twice for the same event yields the same id), never Python's randomized
    `hash()`. Mirrors services/collector.py::_compute_hash's own established sha256 precedent."""
    raw = ":".join((str(event_id), discovery_method.value, *identity_key))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def consolidate_candidates(
    hints: list[NativeMediaHint],
    *,
    event_id: UUID,
    source_type: SourceType,
    mode: Literal["off", "shadow"],
    now: datetime | None = None,
) -> ImageIntelligenceResult:
    """The single, shared consolidation entry point - identical logic for both the Collector-time
    (full source-native hints) and CONTENT_GENERATION-time (reconstructed-from-persisted-fields)
    call sites. `mode="off"` always returns an empty, zero-cost result without inspecting `hints`
    at all - the byte-for-byte-compatible default."""
    generated_at = now or datetime.now(timezone.utc)

    if mode == "off":
        return ImageIntelligenceResult(
            mode="off",
            event_id=event_id,
            candidates_discovered=0,
            candidates_accepted=0,
            candidates_rejected=0,
            candidates=[],
            generated_at=generated_at,
        )

    candidates: list[ImageCandidate] = []
    seen_identities: set[tuple[str, ...]] = set()

    for order, hint in enumerate(hints):
        identity_key = _identity_key(hint)
        reasons: list[str] = []

        if hint.remote_url is not None:
            url_error = _validate_remote_url(hint.remote_url)
            if url_error is not None:
                reasons.append(url_error)

        if not reasons and identity_key in seen_identities:
            reasons.append("duplicate_within_event")

        status = ImageCandidateStatus.REJECTED_METADATA if reasons else ImageCandidateStatus.DISCOVERED
        if not reasons:
            seen_identities.add(identity_key)

        candidates.append(
            ImageCandidate(
                candidate_id=_compute_candidate_id(event_id, hint.discovery_method, identity_key),
                event_id=event_id,
                source_type=source_type,
                discovery_method=hint.discovery_method,
                status=status,
                remote_url=hint.remote_url,
                telegram=hint.telegram,
                declared_width=hint.declared_width,
                declared_height=hint.declared_height,
                declared_mime_type=hint.declared_mime_type,
                alt_text=hint.alt_text,
                caption=hint.caption,
                rejection_reasons=reasons,
                warnings=hint.warnings,
                discovery_order=order,
                discovered_at=generated_at,
            )
        )

    accepted = sum(1 for c in candidates if c.status == ImageCandidateStatus.DISCOVERED)
    rejected = sum(1 for c in candidates if c.status == ImageCandidateStatus.REJECTED_METADATA)

    return ImageIntelligenceResult(
        mode="shadow",
        event_id=event_id,
        candidates_discovered=len(candidates),
        candidates_accepted=accepted,
        candidates_rejected=rejected,
        candidates=candidates,
        generated_at=generated_at,
    )
