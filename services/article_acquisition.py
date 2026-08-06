"""Phase 19 M1: post-selection full-article acquisition (docs/phase19_m0_audit.md).

Wiring point (verified, not assumed - see the audit doc): scripts/run_content_generation.py::
run_content_generation_for_event(), between workflow_service.create_task() and
WorkflowRunner.run() - only ever reached for an event that has already passed
worker/content_cycle.py::_select_eligible_events()'s score gate. Never called from
services/collector.py, worker/analysis_cycle.py, or services/triage_orchestrator.py - collection
and the existing selection pipeline are untouched by this module.

Reuses integrations/http/safe_fetch.py::safe_fetch() exactly as services/image_intelligence.py
already does for article-page HTML - no new fetch mechanism. Reuses stdlib html.parser.HTMLParser
only, matching services/article_metadata.py's own established no-new-HTML-dependency precedent.

Reuse design (Correction 3): a resolved `<link rel="canonical">` URL is a matching KEY for a
*future* selected event, never fetched a second time itself - this module never issues a second
network request for the canonical URL, which sidesteps the "should we trust a possibly-malicious
canonical tag enough to fetch it" question entirely. It is still structurally validated (via
safe_fetch's own `_validate_url` - the exact same scheme/credentials/hostname check every other
fetch in this codebase is bound by) before being trusted as a reuse key, so a malformed or
adversarial canonical tag can never corrupt the reuse index.

Split into pure functions (extraction, classification, validation) and thin async orchestration
(acquire_article, get_or_acquire, get_effective_acquisition) - mirrors services/story_memory.py's
own established convention.
"""
from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FETCH_FAILED,
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_HEADLINE_ONLY,
    ACQUISITION_STATUS_PARTIAL_TEXT,
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED,
    ACQUISITION_STATUS_SUBSTANTIAL_TEXT,
    ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE,
    NewsEventArticleAcquisition,
)
from integrations.http.safe_fetch import (
    FetchErrorCode,
    SafeFetchError,
    SafeFetchPolicy,
    _validate_url,
    safe_fetch,
)

logger = logging.getLogger(__name__)

# Deterministic char-count thresholds (raw, pre-cleaning extraction) - a hand-curated,
# reviewable classification, not a judgment call. services/article_cleaning.py may later
# downgrade this toward PARTIAL_TEXT if cleaning confidence is low (M2's own reconcile_status()).
_FULL_TEXT_MIN_CHARS = 2000
_SUBSTANTIAL_TEXT_MIN_CHARS = 800
_PARTIAL_TEXT_MIN_CHARS = 200

_HTML_CONTENT_TYPE_PREFIXES = ("text/html", "application/xhtml+xml")

# Tags whose text content is never part of the article body.
_SKIP_TEXT_TAGS = frozenset({"script", "style", "noscript", "template", "svg"})


@dataclass(frozen=True)
class AcquisitionOutcome:
    """Everything a single real fetch attempt produced - never raises; every failure mode is an
    `error_code` string, matching integrations.http.safe_fetch.FetchErrorCode's values."""

    status: str
    raw_extracted_text: str | None
    extracted_char_count: int | None
    canonical_url: str | None
    source_html_bytes: int | None
    fetch_duration_ms: int | None
    error_code: str | None


class _ArticleTextCollector(HTMLParser):
    """Collects raw visible text (outside script/style/etc.) and `<link>` attributes, in document
    order - the same technique services/article_metadata.py's `_MetadataCollector` uses, purposed
    here for body-text extraction plus canonical-link discovery instead of image metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.link_tags: list[dict[str, str]] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "link":
            self.link_tags.append({name.lower(): value for name, value in attrs if value is not None})
        elif lowered in _SKIP_TEXT_TAGS:
            self._skip_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "link":
            self.link_tags.append({name.lower(): value for name, value in attrs if value is not None})

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in _SKIP_TEXT_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0 and data.strip():
            self._text_parts.append(data.strip())

    @property
    def text(self) -> str:
        return "\n".join(self._text_parts)


def extract_raw_text(html: str) -> str:
    """Pure. Strips markup, scripts, and styles down to raw visible text - deliberately unrefined
    (services/article_cleaning.py performs the actual boilerplate removal in M2); this function's
    only job is "turn HTML into plain text without losing paragraphs," never main-content
    detection."""
    if not html:
        return ""
    collector = _ArticleTextCollector()
    try:
        collector.feed(html)
    except Exception:
        logger.warning("article_acquisition_html_parse_failed")
        return ""
    return collector.text


def resolve_canonical_url(html: str, *, base_url: str) -> str | None:
    """Pure. Prefers `<link rel="canonical">` if present and structurally valid (scheme/hostname,
    via the exact same integrations.http.safe_fetch._validate_url() check every other fetch in
    this codebase is bound by - never a second, divergent validation); falls back to `base_url`
    (the URL that was actually fetched) otherwise. Never itself triggers a fetch of the resolved
    URL - see module docstring."""
    if not html:
        return base_url or None
    collector = _ArticleTextCollector()
    try:
        collector.feed(html)
    except Exception:
        return base_url or None

    for tag in collector.link_tags:
        rel_values = (tag.get("rel") or "").lower().split()
        href = tag.get("href")
        if "canonical" in rel_values and href:
            resolved = urljoin(base_url, href.strip())
            try:
                _validate_url(resolved)
            except SafeFetchError:
                logger.warning("article_acquisition_canonical_url_rejected", extra={"base_url": base_url})
                continue
            return resolved
    return base_url or None


def classify_acquisition_status(char_count: int) -> str:
    """Pure. Deterministic thresholds only - never a judgment call."""
    if char_count >= _FULL_TEXT_MIN_CHARS:
        return ACQUISITION_STATUS_FULL_TEXT
    if char_count >= _SUBSTANTIAL_TEXT_MIN_CHARS:
        return ACQUISITION_STATUS_SUBSTANTIAL_TEXT
    if char_count >= _PARTIAL_TEXT_MIN_CHARS:
        return ACQUISITION_STATUS_PARTIAL_TEXT
    return ACQUISITION_STATUS_HEADLINE_ONLY


def _fetch_policy() -> SafeFetchPolicy:
    return SafeFetchPolicy(
        connect_timeout_seconds=settings.article_acquisition_connect_timeout_seconds,
        read_timeout_seconds=settings.article_acquisition_read_timeout_seconds,
        total_timeout_seconds=settings.article_acquisition_total_timeout_seconds,
        max_redirects=settings.article_acquisition_max_redirects,
        max_bytes=settings.article_acquisition_max_html_bytes,
    )


async def acquire_article(url: str, *, event_id: UUID) -> AcquisitionOutcome:
    """The one real fetch. Never raises - every failure mode is a status/error_code pair. Bounded
    by settings.article_acquisition_max_extracted_chars regardless of how much raw text the page
    contained (a hard cap, not a classification input)."""
    start = time.monotonic()
    try:
        result = await safe_fetch(url, policy=_fetch_policy())
    except SafeFetchError as error:
        status = (
            ACQUISITION_STATUS_REDIRECT_UNRESOLVED
            if error.code in (FetchErrorCode.TOO_MANY_REDIRECTS, FetchErrorCode.REDIRECT_LOOP, FetchErrorCode.BLOCKED_REDIRECT)
            else ACQUISITION_STATUS_FETCH_FAILED
        )
        return AcquisitionOutcome(
            status=status, raw_extracted_text=None, extracted_char_count=None, canonical_url=None,
            source_html_bytes=None, fetch_duration_ms=int((time.monotonic() - start) * 1000),
            error_code=error.code.value,
        )
    except Exception:
        logger.warning("article_acquisition_unexpected_fetch_error", extra={"event_id": str(event_id)})
        return AcquisitionOutcome(
            status=ACQUISITION_STATUS_FETCH_FAILED, raw_extracted_text=None, extracted_char_count=None,
            canonical_url=None, source_html_bytes=None,
            fetch_duration_ms=int((time.monotonic() - start) * 1000), error_code="internal_fetch_error",
        )

    duration_ms = int((time.monotonic() - start) * 1000)
    if result.status_code >= 400:
        return AcquisitionOutcome(
            status=ACQUISITION_STATUS_FETCH_FAILED, raw_extracted_text=None, extracted_char_count=None,
            canonical_url=result.final_url, source_html_bytes=result.received_byte_count,
            fetch_duration_ms=duration_ms, error_code="http_error",
        )

    content_type = (result.declared_content_type or "").split(";")[0].strip().lower()
    if content_type and not content_type.startswith(_HTML_CONTENT_TYPE_PREFIXES):
        return AcquisitionOutcome(
            status=ACQUISITION_STATUS_UNSUPPORTED_CONTENT_TYPE, raw_extracted_text=None,
            extracted_char_count=None, canonical_url=result.final_url,
            source_html_bytes=result.received_byte_count, fetch_duration_ms=duration_ms,
            error_code="unsupported_content_type",
        )

    try:
        html = result.body.decode("utf-8", errors="replace")
    except Exception:
        logger.warning("article_acquisition_decode_failed", extra={"event_id": str(event_id)})
        return AcquisitionOutcome(
            status=ACQUISITION_STATUS_FETCH_FAILED, raw_extracted_text=None, extracted_char_count=None,
            canonical_url=result.final_url, source_html_bytes=result.received_byte_count,
            fetch_duration_ms=duration_ms, error_code="decode_failed",
        )

    raw_text = extract_raw_text(html)[: settings.article_acquisition_max_extracted_chars]
    canonical_url = resolve_canonical_url(html, base_url=result.final_url)
    char_count = len(raw_text)

    return AcquisitionOutcome(
        status=classify_acquisition_status(char_count), raw_extracted_text=raw_text or None,
        extracted_char_count=char_count, canonical_url=canonical_url,
        source_html_bytes=result.received_byte_count, fetch_duration_ms=duration_ms, error_code=None,
    )


async def _find_reuse_candidate(
    session: AsyncSession, *, canonical_url_guess: str
) -> NewsEventArticleAcquisition | None:
    """Fast-path reuse lookup only (Correction 3's disclosed, documented scope): compares the
    new event's own raw URL against previously-*resolved* canonical URLs already on file. This
    does not fetch to discover a reuse opportunity it can't see without fetching - doing so would
    require a second fetch, defeating the purpose. Never matches a row that is itself a reuse row
    (reused_from_news_event_id IS NULL) - the one-hop invariant. Never matches a row without real
    text (a fetch that failed has nothing to reuse). Respects the reuse window."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.article_acquisition_reuse_window_hours)
    stmt = (
        select(NewsEventArticleAcquisition)
        .where(
            NewsEventArticleAcquisition.canonical_url == canonical_url_guess,
            NewsEventArticleAcquisition.reused_from_news_event_id.is_(None),
            NewsEventArticleAcquisition.raw_extracted_text.is_not(None),
            NewsEventArticleAcquisition.created_at >= cutoff,
        )
        .order_by(NewsEventArticleAcquisition.created_at.desc())
        .limit(1)
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def get_or_acquire(
    session: AsyncSession, news_event: NewsEvent, *, triggered_by: str
) -> NewsEventArticleAcquisition:
    """The orchestration entry point. Idempotent per news_event_id (a retried selection of the
    same event never re-fetches - the existing row is returned as-is). Never raises and never
    blocks/fails the caller - every failure mode is a persisted status. Caller (scripts/
    run_content_generation.py) is responsible for the settings.article_acquisition_mode != "off"
    and source_type != TELEGRAM gates - this function assumes both are already satisfied."""
    existing = await session.get(NewsEventArticleAcquisition, news_event.id)
    if existing is not None:
        return existing

    if not news_event.url:
        row = NewsEventArticleAcquisition(
            news_event_id=news_event.id, acquisition_status=ACQUISITION_STATUS_FETCH_FAILED,
            effective_completeness_status=ACQUISITION_STATUS_FETCH_FAILED, error_code="missing_url",
            triggered_by=triggered_by,
        )
        session.add(row)
        return row

    reuse_candidate = await _find_reuse_candidate(session, canonical_url_guess=news_event.url)
    if reuse_candidate is not None:
        row = NewsEventArticleAcquisition(
            news_event_id=news_event.id, canonical_url=reuse_candidate.canonical_url,
            reused_from_news_event_id=reuse_candidate.news_event_id,
            acquisition_status=reuse_candidate.acquisition_status,
            effective_completeness_status=reuse_candidate.effective_completeness_status,
            cleaning_version=reuse_candidate.cleaning_version, triggered_by=triggered_by,
        )
        session.add(row)
        return row

    outcome = await acquire_article(news_event.url, event_id=news_event.id)
    row = NewsEventArticleAcquisition(
        news_event_id=news_event.id, canonical_url=outcome.canonical_url,
        acquisition_status=outcome.status, raw_extracted_text=outcome.raw_extracted_text,
        effective_completeness_status=outcome.status, extracted_char_count=outcome.extracted_char_count,
        source_html_bytes=outcome.source_html_bytes, fetch_duration_ms=outcome.fetch_duration_ms,
        error_code=outcome.error_code, triggered_by=triggered_by,
    )
    session.add(row)
    return row


async def get_effective_acquisition(
    session: AsyncSession, news_event_id: UUID
) -> NewsEventArticleAcquisition | None:
    """Resolves the row that actually holds text, following `reused_from_news_event_id` at most
    one hop. If a second hop is ever found (should be structurally impossible - a reuse row is
    never itself a valid reuse target, checked in _find_reuse_candidate before write), this
    degrades safely rather than chaining further or raising."""
    row = await session.get(NewsEventArticleAcquisition, news_event_id)
    if row is None or row.reused_from_news_event_id is None:
        return row
    target = await session.get(NewsEventArticleAcquisition, row.reused_from_news_event_id)
    if target is not None and target.reused_from_news_event_id is not None:
        logger.warning(
            "article_acquisition_reuse_chain_exceeded_one_hop", extra={"news_event_id": str(news_event_id)}
        )
        return None
    return target


def compute_text_hash(text: str) -> str:
    """Pure. SHA-256 of whichever text was actually selected - the exact provenance value stored
    on the acquisition row and copied onto EvidencePackage (services/evidence_package.py)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
