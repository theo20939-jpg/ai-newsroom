"""Phase 16 M1/M2: Image Intelligence - native media discovery (M1, docs/phase16_m1_native_media_
ingestion_report.md) plus secure article-metadata discovery and technical image validation (M2,
docs/phase16_m2_secure_fetch_and_validation_report.md).

Two independent M1 call sites share the extraction/consolidation functions in this module (docs/
phase16_image_intelligence_discovery_report.md §11, §20):

1. services/collector.py, after a NewsEvent is flushed (real `event.id` available) - consumes
   the full source-native hints an adapter produced at fetch time (`extract_telegram_native_media`/
   `extract_rss_native_media`) and logs a structured audit trail. Nothing here is persisted to
   PostgreSQL: NewsEvent has no image/media column and M1 adds no migration (discovery report
   §11/§21) - this is observability only, not durable storage.
2. capabilities/executor.py, at the CONTENT_GENERATION "copywriting" step, calls
   `run_shadow_discovery()` - the single M2 orchestration entry point. It reconstructs M1 hints
   from already-persisted NewsEvent fields, optionally fetches the article page and candidate
   image bytes through the SSRF-safe boundary (integrations/http/safe_fetch.py), technically
   validates them (services/image_validation.py), and returns one `ImageIntelligenceResult`. No
   low-level networking lives in capabilities/executor.py itself (Step 13 of the M2 task brief) -
   it only calls this one function and preserves the result.

Zero LLM/provider call anywhere in this module, in M1 or M2.
"""
import asyncio
import hashlib
import logging
from collections.abc import Mapping
from datetime import datetime, timezone
from html.parser import HTMLParser
from typing import Any, Literal
from urllib.parse import urljoin, urlsplit
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_source import SourceType
from integrations.http.safe_fetch import SafeFetchError, SafeFetchPolicy, safe_fetch
from schemas.image_candidate import (
    DeduplicationInfo,
    ImageCandidate,
    ImageCandidateStatus,
    ImageDiscoveryMethod,
    ImageIntelligenceResult,
    NativeMediaHint,
    QualityStatus,
    QualityValidation,
    RelevanceStatus,
    TechnicalValidation,
    TelegramReference,
)
from services.article_metadata import extract_article_image_metadata
from services.image_deduplication import cluster_candidates
from services.image_persistence import persist_image_intelligence_result
from services.image_quality import QualityAnalysis, analyze_candidate
from services.image_relevance import rank_candidates
from services.image_validation import validate_image_bytes

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
                source_url=base_url,
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
                source_url=hint.source_url,
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


# ---------------------------------------------------------------------------
# Phase 16 M2: article-metadata fetch + technical image validation orchestration.
# ---------------------------------------------------------------------------


def _html_fetch_policy() -> SafeFetchPolicy:
    return SafeFetchPolicy(
        connect_timeout_seconds=settings.image_intelligence_connect_timeout_seconds,
        read_timeout_seconds=settings.image_intelligence_read_timeout_seconds,
        total_timeout_seconds=settings.image_intelligence_total_timeout_seconds,
        max_redirects=settings.image_intelligence_max_redirects,
        max_bytes=settings.image_intelligence_max_html_bytes,
    )


def _image_fetch_policy() -> SafeFetchPolicy:
    return SafeFetchPolicy(
        connect_timeout_seconds=settings.image_intelligence_connect_timeout_seconds,
        read_timeout_seconds=settings.image_intelligence_read_timeout_seconds,
        total_timeout_seconds=settings.image_intelligence_total_timeout_seconds,
        max_redirects=settings.image_intelligence_max_redirects,
        max_bytes=settings.image_intelligence_max_image_bytes,
    )


_HTML_CONTENT_TYPES = ("text/html", "application/xhtml+xml")


async def _fetch_article_metadata_hints(
    article_url: str, *, event_id: UUID
) -> tuple[list[NativeMediaHint], str | None]:
    """Returns (hints, error_code). Never raises - every failure mode is reported as an
    `error_code` string, matching integrations.http.safe_fetch.FetchErrorCode's values plus
    "unsupported_content_type" for a non-HTML response."""
    try:
        result = await safe_fetch(article_url, policy=_html_fetch_policy())
    except SafeFetchError as error:
        return [], error.code.value
    except Exception:
        logger.warning("article_metadata_fetch_unexpected_error", extra={"event_id": str(event_id)})
        return [], "internal_fetch_error"

    if result.status_code >= 400:
        return [], "http_error"

    declared_type = (result.declared_content_type or "").split(";")[0].strip().lower()
    if declared_type and declared_type not in _HTML_CONTENT_TYPES:
        return [], "unsupported_content_type"

    html_text = result.body.decode("utf-8", errors="replace")
    try:
        hints = extract_article_image_metadata(html_text, base_url=result.final_url)
    except Exception:
        logger.warning("article_metadata_parse_unexpected_error", extra={"event_id": str(event_id)})
        return [], "internal_fetch_error"
    return hints, None


async def _fetch_and_validate_candidate(
    candidate: ImageCandidate,
) -> tuple[ImageCandidate, QualityAnalysis | None, bytes | None]:
    """Fetches one candidate's image bytes through the safe-fetch boundary, technically validates
    them (M2), and - only when M2 accepts the bytes - runs M3 quality analysis on the *same*
    in-memory bytes before they go out of scope (docs/phase16_m3_quality_and_deduplication_
    report.md §3: "M3 must not refetch an image solely to calculate quality or perceptual
    hashes" - `fetch_result.body` is fetched exactly once here and reused for M2, M3, and - as of
    Phase 16 M5 - optionally M5's own finalist storage, docs/phase16_m5_persistence_and_retention_
    report.md §11 - never a second network request). Always returns a candidate (never raises) -
    `status` becomes exactly one of VALIDATED/REJECTED_TECHNICAL/FETCH_FAILED, `technical_
    validation` is always populated. The third tuple element is the raw validated bytes (only when
    `status == VALIDATED`, `None` otherwise) - the caller (`run_shadow_discovery`) is solely
    responsible for keeping this bounded and discarding it once M5's finalist-storage stage (or the
    end of the function, when persistence never runs) has used it; it is never attached to the
    `ImageCandidate` model itself, never serialized, never logged."""
    assert candidate.remote_url is not None  # only ever called for candidates that have one
    try:
        fetch_result = await safe_fetch(candidate.remote_url, policy=_image_fetch_policy())
    except SafeFetchError as error:
        technical = TechnicalValidation(error_code=error.code.value)
        updated = candidate.model_copy(
            update={"status": ImageCandidateStatus.FETCH_FAILED, "technical_validation": technical, "schema_version": "m2"}
        )
        return updated, None, None
    except Exception:
        logger.warning("image_fetch_unexpected_error", extra={"candidate_id": candidate.candidate_id})
        technical = TechnicalValidation(error_code="internal_fetch_error")
        updated = candidate.model_copy(
            update={"status": ImageCandidateStatus.FETCH_FAILED, "technical_validation": technical, "schema_version": "m2"}
        )
        return updated, None, None

    if fetch_result.status_code >= 400:
        technical = TechnicalValidation(
            final_url=fetch_result.final_url, http_status=fetch_result.status_code,
            redirect_count=fetch_result.redirect_count, error_code="http_error",
        )
        updated = candidate.model_copy(
            update={"status": ImageCandidateStatus.FETCH_FAILED, "technical_validation": technical, "schema_version": "m2"}
        )
        return updated, None, None

    technical = validate_image_bytes(fetch_result.body, max_pixels=settings.image_intelligence_max_decoded_pixels)
    technical = technical.model_copy(
        update={
            "final_url": fetch_result.final_url,
            "http_status": fetch_result.status_code,
            "redirect_count": fetch_result.redirect_count,
            "duration_ms": (technical.duration_ms or 0) + int(fetch_result.duration_seconds * 1000),
        }
    )
    status = ImageCandidateStatus.VALIDATED if technical.error_code is None else ImageCandidateStatus.REJECTED_TECHNICAL
    updated = candidate.model_copy(
        update={"status": status, "technical_validation": technical, "schema_version": "m2"}
    )

    if status != ImageCandidateStatus.VALIDATED:
        return updated, None, None

    try:
        analysis = analyze_candidate(fetch_result.body, candidate=updated)
    except Exception:
        logger.warning("quality_analysis_stage_unexpected_error", extra={"candidate_id": candidate.candidate_id})
        analysis = None
    return updated, analysis, fetch_result.body


async def _validate_selected_candidates(
    candidates: list[ImageCandidate],
) -> list[tuple[ImageCandidate, QualityAnalysis | None, bytes | None]]:
    """Bounded, in-process-only concurrency (docs/phase16_m2_secure_fetch_and_validation_report.md
    §17 - a single `content_worker` process exists today, so a distributed limiter is not
    justified; this is documented as a known limitation, not an oversight, should that ever
    change). Fresh semaphores per call: `content_worker` processes events sequentially (tests/
    test_content_worker_cycle.py's own "sequential_no_gather" naming), so per-invocation limiting
    already correctly bounds the only concurrency that can occur - the fan-out across one event's
    own candidates."""
    eligible = [c for c in candidates if c.status == ImageCandidateStatus.DISCOVERED and c.remote_url is not None]
    selected_ids = {c.candidate_id for c in eligible[: settings.image_intelligence_max_image_downloads_per_event]}
    if not selected_ids:
        return [(candidate, None, None) for candidate in candidates]

    global_semaphore = asyncio.Semaphore(settings.image_intelligence_global_concurrency)
    host_semaphores: dict[str, asyncio.Semaphore] = {}

    def _host_semaphore(url: str) -> asyncio.Semaphore:
        host = urlsplit(url).hostname or ""
        if host not in host_semaphores:
            host_semaphores[host] = asyncio.Semaphore(settings.image_intelligence_per_host_concurrency)
        return host_semaphores[host]

    async def _bounded_validate(candidate: ImageCandidate) -> tuple[ImageCandidate, QualityAnalysis | None, bytes | None]:
        assert candidate.remote_url is not None
        async with global_semaphore, _host_semaphore(candidate.remote_url):
            return await _fetch_and_validate_candidate(candidate)

    async def _passthrough(candidate: ImageCandidate) -> tuple[ImageCandidate, QualityAnalysis | None, bytes | None]:
        return candidate, None, None

    tasks = [
        _bounded_validate(candidate) if candidate.candidate_id in selected_ids else _passthrough(candidate)
        for candidate in candidates
    ]
    return list(await asyncio.gather(*tasks))


def _decide_quality_status(analysis: QualityAnalysis, dedup: DeduplicationInfo) -> QualityStatus:
    """Precedence exactly matches docs/phase16_m3_quality_and_deduplication_report.md §17: hard
    rejection wins regardless of duplicate/ambiguity status; exact duplicate before near duplicate
    (distinguished by `hamming_distance == 0`, the sentinel services.image_deduplication always
    assigns to exact-cluster members); an unresolved-but-close near-duplicate or an ambiguous
    logo/banner signal becomes `review`, never silently `accepted`."""
    if analysis.decode_error is not None:
        return QualityStatus.REVIEW
    if analysis.hard_rejection_reasons:
        return QualityStatus.REJECTED_QUALITY
    if dedup.duplicate_of is not None:
        return QualityStatus.DUPLICATE_EXACT if dedup.hamming_distance == 0 else QualityStatus.DUPLICATE_NEAR
    if analysis.signals.possible_logo or analysis.signals.possible_banner:
        return QualityStatus.REVIEW
    if dedup.hamming_distance is not None:  # close to another cluster, but not close enough to auto-merge
        return QualityStatus.REVIEW
    return QualityStatus.ACCEPTED


def _finalize_quality(
    items: list[tuple[ImageCandidate, QualityAnalysis | None]],
) -> list[ImageCandidate]:
    """The M3 finalization step: clusters every successfully-analyzed candidate in this one event
    (services.image_deduplication.cluster_candidates - never across events, per the M3 task
    brief's own explicit scoping), then builds and attaches one `QualityValidation` per candidate.
    Candidates M3 never analyzed (M2 didn't validate them, or analysis itself failed with no
    result at all) keep `quality_validation=None` - M2's own status/technical_validation is never
    touched (docs §2's "keep separate concerns" requirement)."""
    analyzable = [(candidate, analysis) for candidate, analysis in items if analysis is not None and analysis.decode_error is None]
    dedup_by_id = cluster_candidates(analyzable) if analyzable else {}

    finalized: list[ImageCandidate] = []
    for candidate, analysis in items:
        if analysis is None:
            finalized.append(candidate)
            continue

        dedup = dedup_by_id.get(
            candidate.candidate_id,
            DeduplicationInfo(perceptual_hash=analysis.perceptual_hash),
        )
        status = _decide_quality_status(analysis, dedup)
        quality = QualityValidation(
            status=status,
            quality_score=analysis.quality_score,
            quality_components=analysis.quality_components,
            quality_penalties=analysis.quality_penalties,
            hard_rejection_reasons=analysis.hard_rejection_reasons,
            quality_warnings=analysis.quality_warnings + (["quality_analysis_failed"] if analysis.decode_error else []),
            signals=analysis.signals,
            deduplication=dedup,
            duration_ms=analysis.duration_ms,
        )
        finalized.append(candidate.model_copy(update={"quality_validation": quality, "schema_version": "m3"}))
    return finalized


async def run_shadow_discovery(
    *,
    event_id: UUID,
    source_type: SourceType,
    content: str | None,
    article_url: str | None,
    mode: Literal["off", "shadow"],
    now: datetime | None = None,
    event_title: str | None = None,
    source_name: str | None = None,
    session: AsyncSession | None = None,
    editorial_task_id: UUID | None = None,
) -> ImageIntelligenceResult:
    """The single M2-M4 orchestration entry point, called once per CONTENT_GENERATION "copywriting"
    step (capabilities/executor.py). `mode="off"` is a zero-cost, zero-network no-op - delegates
    straight to `consolidate_candidates`'s own off-mode short-circuit without inspecting anything.

    Article-page fetching is attempted only when `source_type != TELEGRAM` (a Telegram NewsEvent's
    `url` is an internal `t.me/...` link, not an external article page - fetching it would target
    Telegram's own web interface, a different risk/scope than "the original article page
    associated with the NewsEvent") and only up to `image_intelligence_max_articles_per_event`
    (always 1 in this milestone's default config).

    `event_title`/`source_name` (Phase 16 M4, docs/phase16_m4_relevance_ranking_report.md §3) are
    additive, optional keyword-only parameters - callers that predate M4 (existing scripts/tests)
    keep working unchanged with `None`, which `services.image_relevance` treats as "no evidence
    available," never as an error.

    `session`/`editorial_task_id` (Phase 16 M5, docs/phase16_m5_persistence_and_retention_report.md
    §19) are likewise additive and optional - persistence only ever runs when a caller explicitly
    passes a real `session` (capabilities/executor.py does; every pre-M5 script/test does not, and
    keeps behaving exactly as before). This keeps `run_shadow_discovery`'s own return type
    unchanged (still just `ImageIntelligenceResult`) - the bounded, transient validated bytes this
    function holds internally for M5's own finalist-storage stage are never returned, never
    attached to any model, and go out of scope the moment this function returns.
    """
    generated_at = now or datetime.now(timezone.utc)
    native_hints = reconstruct_hints_from_content(content, article_url)

    if mode == "off":
        return consolidate_candidates([], event_id=event_id, source_type=source_type, mode="off", now=generated_at)

    metadata_hints: list[NativeMediaHint] = []
    article_fetch_attempted = False
    article_fetch_error: str | None = None

    should_fetch_article = (
        source_type != SourceType.TELEGRAM
        and bool(article_url)
        and settings.image_intelligence_max_articles_per_event > 0
    )
    if should_fetch_article:
        article_fetch_attempted = True
        assert article_url is not None
        try:
            metadata_hints, article_fetch_error = await asyncio.wait_for(
                _fetch_article_metadata_hints(article_url, event_id=event_id),
                timeout=settings.image_intelligence_total_timeout_seconds + 1,
            )
        except asyncio.TimeoutError:
            article_fetch_error = "total_timeout"
        except Exception:
            logger.warning("article_metadata_stage_unexpected_error", extra={"event_id": str(event_id)})
            article_fetch_error = "internal_fetch_error"

    combined_hints = (native_hints + metadata_hints)[: settings.image_intelligence_max_candidate_urls_per_event]
    result = consolidate_candidates(
        combined_hints, event_id=event_id, source_type=source_type, mode="shadow", now=generated_at
    )

    try:
        validation_items = await _validate_selected_candidates(result.candidates)
    except Exception:
        logger.warning("image_validation_stage_unexpected_error", extra={"event_id": str(event_id)})
        validation_items = [(candidate, None, None) for candidate in result.candidates]

    # Phase 16 M5 (docs/phase16_m5_persistence_and_retention_report.md §10-11): the bounded,
    # transient handle to each VALIDATED candidate's already-fetched bytes, kept only in this
    # function's local scope - never attached to a model, never logged, discarded (falls out of
    # scope, nothing to explicitly free) once the M5 persistence call below returns or is skipped.
    image_bytes_by_candidate_id: dict[str, bytes] = {
        candidate.candidate_id: data for candidate, _, data in validation_items if data is not None
    }

    validated_count = sum(1 for c, _, _ in validation_items if c.status == ImageCandidateStatus.VALIDATED)
    rejected_technical_count = sum(
        1 for c, _, _ in validation_items if c.status == ImageCandidateStatus.REJECTED_TECHNICAL
    )
    fetch_failed_count = sum(1 for c, _, _ in validation_items if c.status == ImageCandidateStatus.FETCH_FAILED)
    m2_ran = article_fetch_attempted or validated_count or rejected_technical_count or fetch_failed_count

    try:
        finalized_candidates = _finalize_quality([(c, a) for c, a, _ in validation_items])
    except Exception:
        logger.warning("quality_finalization_stage_unexpected_error", extra={"event_id": str(event_id)})
        finalized_candidates = [candidate for candidate, _, _ in validation_items]

    quality_accepted = sum(
        1 for c in finalized_candidates if c.quality_validation and c.quality_validation.status == QualityStatus.ACCEPTED
    )
    rejected_quality = sum(
        1 for c in finalized_candidates if c.quality_validation and c.quality_validation.status == QualityStatus.REJECTED_QUALITY
    )
    duplicate_exact = sum(
        1 for c in finalized_candidates if c.quality_validation and c.quality_validation.status == QualityStatus.DUPLICATE_EXACT
    )
    duplicate_near = sum(
        1 for c in finalized_candidates if c.quality_validation and c.quality_validation.status == QualityStatus.DUPLICATE_NEAR
    )
    review_count = sum(
        1 for c in finalized_candidates if c.quality_validation and c.quality_validation.status == QualityStatus.REVIEW
    )
    m3_ran = bool(quality_accepted or rejected_quality or duplicate_exact or duplicate_near or review_count)

    try:
        ranked_candidates = rank_candidates(
            finalized_candidates, event_title=event_title, event_content=content, event_url=article_url,
            source_name=source_name, top_candidates=settings.image_intelligence_top_candidates,
        )
    except Exception:
        logger.warning("relevance_ranking_stage_unexpected_error", extra={"event_id": str(event_id)})
        ranked_candidates = finalized_candidates

    quality_eligible = sum(
        1 for c in ranked_candidates
        if c.relevance_validation and c.relevance_validation.status != RelevanceStatus.INELIGIBLE
    )
    ranked_count = sum(
        1 for c in ranked_candidates
        if c.relevance_validation and c.relevance_validation.status == RelevanceStatus.RANKED
    )
    top_ranked_candidates = [
        c for c in ranked_candidates if c.relevance_validation and c.relevance_validation.eligible_for_editorial
    ]
    top_ranked_candidates.sort(key=lambda c: c.relevance_validation.rank or 0)  # type: ignore[union-attr]
    top_candidate_ids = [c.candidate_id for c in top_ranked_candidates]
    m4_ran = any(c.relevance_validation is not None for c in ranked_candidates)

    logger.info(
        "image_intelligence_shadow_result",
        extra={
            "event_id": str(event_id),
            "source_type": source_type.value,
            "mode": mode,
            "article_fetch_attempted": article_fetch_attempted,
            "article_fetch_error": article_fetch_error,
            "candidates_discovered": result.candidates_discovered,
            "candidates_validated": validated_count,
            "candidates_rejected_technical": rejected_technical_count,
            "candidates_fetch_failed": fetch_failed_count,
            "candidates_quality_accepted": quality_accepted,
            "candidates_rejected_quality": rejected_quality,
            "candidates_duplicate_exact": duplicate_exact,
            "candidates_duplicate_near": duplicate_near,
            "candidates_review": review_count,
            "candidates_quality_eligible": quality_eligible,
            "candidates_ranked": ranked_count,
            "top_candidate_count": len(top_candidate_ids),
        },
    )

    final_result = result.model_copy(
        update={
            "version": "m4" if m4_ran else ("m3" if m3_ran else ("m2" if m2_ran else result.version)),
            "candidates": ranked_candidates,
            "article_fetch_attempted": article_fetch_attempted,
            "article_fetch_error": article_fetch_error,
            "candidates_validated": validated_count,
            "candidates_rejected_technical": rejected_technical_count,
            "candidates_fetch_failed": fetch_failed_count,
            "candidates_quality_accepted": quality_accepted,
            "candidates_rejected_quality": rejected_quality,
            "candidates_duplicate_exact": duplicate_exact,
            "candidates_duplicate_near": duplicate_near,
            "candidates_review": review_count,
            "candidates_quality_eligible": quality_eligible,
            "candidates_ranked": ranked_count,
            "top_candidate_ids": top_candidate_ids,
        }
    )

    # Phase 16 M5 (docs/phase16_m5_persistence_and_retention_report.md §19): only runs when a
    # caller passed a real session (capabilities/executor.py does) AND persistence is not "off".
    # A persistence failure is logged and swallowed - it never fails CONTENT_GENERATION and never
    # changes the ImageIntelligenceResult already computed above.
    if session is not None and settings.image_candidate_persistence_mode != "off":
        try:
            await persist_image_intelligence_result(
                session, result=final_result, editorial_task_id=editorial_task_id,
                image_bytes_by_candidate_id=image_bytes_by_candidate_id,
            )
        except Exception:
            logger.warning("image_persistence_stage_unexpected_error", extra={"event_id": str(event_id)})

    return final_result
