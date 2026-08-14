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
import re
import time
from dataclasses import dataclass, field
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
from services.text_normalization import is_google_news_redirect_host, normalize_loose
from services.text_normalization import strip_google_news_title_suffix as _strip_google_news_title_suffix
from services.video_discovery import extract_article_video_metadata

logger = logging.getLogger(__name__)

# Deterministic char-count thresholds (raw, pre-cleaning extraction) - a hand-curated,
# reviewable classification, not a judgment call. services/article_cleaning.py may later
# downgrade this toward PARTIAL_TEXT if cleaning confidence is low (M2's own reconcile_status()).
_FULL_TEXT_MIN_CHARS = 2000
_SUBSTANTIAL_TEXT_MIN_CHARS = 800
_PARTIAL_TEXT_MIN_CHARS = 200

# NEWS Stability - Google News sibling-evidence-reuse fix (docs/
# google_news_sibling_reuse_fix_checkpoint.md, forensic evidence: docs/
# story_cluster_fragmentation_focused_forensic_report.md): the same two trusted completeness
# tiers as services/evidence_package.py::TRUSTED_FULL_ARTICLE_STATUSES - duplicated here (not
# imported) because evidence_package.py itself imports from this module, and importing back would
# be circular. Kept as a literal value-copy, matching this codebase's own established convention
# for a small, rarely-changed constant that a real import-direction constraint prevents sharing
# (e.g. bot/formatting.py's _SAFE_LIMIT vs. services/news_telegram_presentation.py's own copy).
_SIBLING_REUSE_TRUSTED_STATUSES = frozenset({ACQUISITION_STATUS_FULL_TEXT, ACQUISITION_STATUS_PARTIAL_TEXT})
# How close two NewsEvents' own published_at values must be to even be considered for sibling
# reuse - the real, decisive safety signal (both confirmed real cases share the identical
# published_at second; a coincidental identical-second match between two genuinely different
# articles is not realistic, unlike title similarity or shared category/entity).
_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS = 5
# A prefix/suffix-stripped title match shorter than this is never trusted alone (avoids a short,
# generic titlefragment coincidentally prefixing an unrelated longer one).
_SIBLING_REUSE_MIN_TITLE_LEN = 20

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
    # Phase 19 M10: raw discovery only (services.video_discovery.extract_article_video_metadata()
    # against this same already-fetched HTML - zero additional network request), never validated
    # here - a new, additive, defaulted field so every existing call site above is unaffected.
    # The caller (services/content_draft_service.py, gated on video_discovery_mode) decides
    # whether/how to validate and persist these.
    discovered_video_hints: list = field(default_factory=list)


class _ArticleTextCollector(HTMLParser):
    """Collects raw visible text (outside script/style/etc.) and `<link>` attributes, in document
    order - the same technique services/article_metadata.py's `_MetadataCollector` uses, purposed
    here for body-text extraction plus canonical-link discovery instead of image metadata."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.link_tags: list[dict[str, str]] = []
        # NEWS Output Stability Fix (Case A): meta tags, collected the same way link_tags always
        # have been - added so resolve_meta_refresh_url() below can find a <meta http-equiv=
        # "refresh"> signal without a second HTML parser class (never a new scraper).
        self.meta_tags: list[dict[str, str]] = []
        self._text_parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "link":
            self.link_tags.append({name.lower(): value for name, value in attrs if value is not None})
        elif lowered == "meta":
            self.meta_tags.append({name.lower(): value for name, value in attrs if value is not None})
        elif lowered in _SKIP_TEXT_TAGS:
            self._skip_depth += 1

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        lowered = tag.lower()
        if lowered == "link":
            self.link_tags.append({name.lower(): value for name, value in attrs if value is not None})
        elif lowered == "meta":
            self.meta_tags.append({name.lower(): value for name, value in attrs if value is not None})

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


# NEWS Output Stability Fix (Case H, docs/news_output_stability_forensic_report.md §9): a hand-
# curated, narrow, deterministic lexicon (English-focused - interstitial/consent/sign-in-wall
# pages from Western platforms are overwhelmingly served in English regardless of the article's
# own language) covering the categories the corrective phase named: cookie consent, sign-in wall,
# access denied, challenge page, navigation-only shell. Mirrors services/content_quality_gates.py's
# own _GENERIC_FILLER_PHRASES/_UNSUPPORTED_SUPERLATIVES convention exactly - a fixed list, never a
# general classifier, matched per-LINE (not against the whole text) so a genuine article that
# merely has a cookie-consent banner mixed in alongside abundant real prose is never penalized -
# only the matching banner/wall lines themselves are excluded from the substantive-content count.
_INTERSTITIAL_LINE_MARKERS: tuple[str, ...] = (
    # cookie consent
    "we use cookies", "uses cookies", "cookie policy", "accept all cookies", "manage cookies",
    "respects your privacy", "essential and non-essential cookies", "reject non-essential",
    # sign-in / registration / subscription wall
    "sign in to view", "sign in to continue", "create your free account", "join now to view",
    "log in to continue", "subscribe to continue reading", "subscribe to read", "become a member to",
    "sign in with email", "new to linkedin", "agree & join", "you've reached your limit",
    "sign in to view more content", "create your free account or sign in",
    # access denied / bot-challenge page
    "access denied", "you have been blocked", "checking your browser", "verify you are human",
    "enable javascript to continue", "are you a robot", "attention required", "just a moment",
    "please enable cookies",
    # navigation-only shell chrome
    "skip to main content",
)


def _is_interstitial_boilerplate_line(line: str) -> bool:
    normalized = normalize_loose(line)
    return any(marker in normalized for marker in _INTERSTITIAL_LINE_MARKERS)


def estimate_substantive_char_count(raw_text: str) -> int:
    """Pure. Excludes lines matching `_INTERSTITIAL_LINE_MARKERS` before counting - a page that IS
    substantially a cookie-consent/sign-in-wall/access-denied/challenge/navigation-only shell (most
    or all of its extracted lines match) is correctly measured as thin; a normal article that
    merely has a cookie banner mixed in alongside abundant real prose is unaffected, since only the
    matched lines are excluded, never the whole text merely for containing a recognized phrase
    somewhere. Used only to choose the acquisition STATUS (classify_acquisition_status()) - never
    changes what is persisted as raw_extracted_text/extracted_char_count, which remain the true,
    complete, verbatim extraction for audit purposes (database/models/news_event_article_
    acquisition.py's own documented "verbatim extraction, pre-cleaning" contract)."""
    if not raw_text:
        return 0
    lines = raw_text.split("\n")
    substantive_lines = [line for line in lines if not _is_interstitial_boilerplate_line(line)]
    return len("\n".join(substantive_lines))


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


# NEWS Output Stability Fix (Case A, docs/news_output_stability_forensic_report.md §2): a Google
# News RSS "articles" URL (https://news.google.com/rss/articles/CBMi...) never itself contains the
# destination article - fetching it (confirmed empirically, single diagnostic fetch against a real
# affected URL) returns Google's own ~580KB Angular application shell (visible text: literally
# "Google News", no destination URL embedded anywhere in the static HTML - the real article
# requires Google's own undocumented internal batchexecute API to resolve, which this codebase
# deliberately does not implement, matching the "no second scraper" instruction). Host-suffix
# matching only (never payload decoding, which is unreliable and fragile against Google's own
# encoding changes, and was empirically confirmed NOT to contain a readable destination URL for
# the current format) - the same convention services/video_discovery.py::classify_video_url()
# already established for YouTube/Vimeo host matching. is_google_news_redirect_host() itself now
# lives in services/text_normalization.py (imported above) - a second caller (services/
# story_delta_engine.py) needs it too, without importing this much heavier module.
_META_REFRESH_URL_RE = re.compile(r"url\s*=\s*['\"]?([^'\";]+)", re.IGNORECASE)


def resolve_meta_refresh_url(html: str, *, base_url: str) -> str | None:
    """Pure. A general, non-Google-specific redirect signal: `<meta http-equiv="refresh"
    content="N;url=...">` - a standard HTML mechanism some redirect/interstitial pages provide for
    non-JS clients (the real Google News shell page this fix was built against does NOT include
    one, confirmed empirically - this remains a real, general mechanism worth checking for other
    redirect-shell pages that do). Never itself triggers a fetch (mirrors resolve_canonical_url()'s
    own "extraction only" contract) - the caller decides whether/how to follow the result."""
    if not html:
        return None
    collector = _ArticleTextCollector()
    try:
        collector.feed(html)
    except Exception:
        return None

    for tag in collector.meta_tags:
        if (tag.get("http-equiv") or "").strip().lower() != "refresh":
            continue
        match = _META_REFRESH_URL_RE.search(tag.get("content") or "")
        if not match:
            continue
        resolved = urljoin(base_url, match.group(1).strip())
        try:
            _validate_url(resolved)
        except SafeFetchError:
            logger.warning("article_acquisition_meta_refresh_url_rejected", extra={"base_url": base_url})
            continue
        return resolved
    return None


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


async def acquire_article(url: str, *, event_id: UUID, _google_news_hop: bool = False) -> AcquisitionOutcome:
    """The one real fetch. Never raises - every failure mode is a status/error_code pair. Bounded
    by settings.article_acquisition_max_extracted_chars regardless of how much raw text the page
    contained (a hard cap, not a classification input).

    `_google_news_hop` (NEWS Output Stability Fix, Case A, internal use only - never passed by an
    external caller): set True on the one, bounded recursive re-fetch this function makes when a
    Google News redirect-shell URL's own canonical-link/meta-refresh resolves to a real, off-Google
    destination - guarantees at most one extra hop, never a chain, mirroring safe_fetch()'s own
    `max_redirects` bound in spirit (a distinct mechanism, since Google's redirect is not a real
    HTTP 3xx safe_fetch() can already follow - see is_google_news_redirect_host()'s own docstring)."""
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

    # NEWS Output Stability Fix (Case A): a Google News redirect-shell URL's own extracted text
    # (Google's application shell, not the real article) must never be silently classified as if
    # it were real HEADLINE_ONLY/PARTIAL_TEXT article content - two general, non-Google-specific
    # resolution signals are tried first (an off-Google canonical link, a meta-refresh tag); if
    # neither resolves a real destination, this honestly reports REDIRECT_UNRESOLVED instead of
    # running the normal char-count classifier on the shell's own incidental visible text.
    if not _google_news_hop and is_google_news_redirect_host(url):
        redirect_target: str | None = None
        if canonical_url and not is_google_news_redirect_host(canonical_url):
            redirect_target = canonical_url
        else:
            meta_refresh_url = resolve_meta_refresh_url(html, base_url=result.final_url)
            if meta_refresh_url and not is_google_news_redirect_host(meta_refresh_url):
                redirect_target = meta_refresh_url

        if redirect_target is not None:
            return await acquire_article(redirect_target, event_id=event_id, _google_news_hop=True)

        return AcquisitionOutcome(
            status=ACQUISITION_STATUS_REDIRECT_UNRESOLVED, raw_extracted_text=None,
            extracted_char_count=None, canonical_url=canonical_url,
            source_html_bytes=result.received_byte_count, fetch_duration_ms=duration_ms,
            error_code="google_news_redirect_unresolved",
        )

    # Phase 19 M10: zero additional network request - extracted from this same already-fetched
    # HTML. Best-effort: an extraction failure must never affect article acquisition's own
    # result, mirrors this module's own "never raises" discipline throughout.
    video_hints: list = []
    if settings.video_discovery_mode != "off":
        try:
            video_hints = extract_article_video_metadata(html, base_url=result.final_url)
        except Exception:
            logger.warning("article_video_discovery_failed", extra={"event_id": str(event_id)})

    # NEWS Output Stability Fix (Case H): the STATUS is classified from the substantive char
    # count (interstitial/consent-wall/sign-in-wall/access-denied/challenge-page/navigation-shell
    # lines excluded) rather than the raw extraction length - a page that is substantially just
    # such a shell must never be classified FULL_TEXT/SUBSTANTIAL_TEXT/PARTIAL_TEXT as if it were
    # real article content (the required invariant). `extracted_char_count`/`raw_extracted_text`
    # themselves are untouched - both remain the true, complete, verbatim extraction, exactly as
    # documented on NewsEventArticleAcquisition; only the classification decision changes.
    return AcquisitionOutcome(
        status=classify_acquisition_status(estimate_substantive_char_count(raw_text)),
        raw_extracted_text=raw_text or None, extracted_char_count=char_count, canonical_url=canonical_url,
        source_html_bytes=result.received_byte_count, fetch_duration_ms=duration_ms, error_code=None,
        discovered_video_hints=video_hints,
    )


def _titles_confidently_match(title_a: str, title_b: str) -> bool:
    """Pure. Conservative same-article title check, deliberately NOT a fuzzy/loose similarity
    score - docs/google_news_sibling_reuse_fix_checkpoint.md's own required safety invariant
    ("never reuse solely because of same company/topic/category/loose title similarity"). True
    only for: an exact match (after stripping a Google News title suffix from either side), or one
    title being a genuine, substantial prefix of the other (the real RSS-truncation pattern
    confirmed in the Twitch/Amazon case, where the wrapper's own title was cut short mid-sentence
    by the feed itself) - never a short/generic fragment (`_SIBLING_REUSE_MIN_TITLE_LEN` floor)."""
    a = _strip_google_news_title_suffix(title_a)
    b = _strip_google_news_title_suffix(title_b)
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= _SIBLING_REUSE_MIN_TITLE_LEN and longer.startswith(shorter)


async def _find_acquisition_failure_sibling(
    session: AsyncSession, news_event: NewsEvent,
) -> NewsEventArticleAcquisition | None:
    """Conservative post-failure fallback (docs/google_news_sibling_reuse_fix_checkpoint.md),
    called ONLY after this event's own acquisition already failed with
    ACQUISITION_STATUS_REDIRECT_UNRESOLVED - never replaces or precedes a real fetch attempt,
    never runs speculatively. Real evidence: docs/
    story_cluster_fragmentation_focused_forensic_report.md - both confirmed cases were a Google
    News RSS wrapper of an article whose direct-feed sibling had already been fully, successfully
    acquired 48-62 seconds earlier under a different NewsEvent/source_id.

    Requires ALL of, none individually sufficient:
    - the candidate's own NewsEvent.published_at is within
      `_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS` of this event's own published_at (the
      decisive safety signal - see that constant's own comment);
    - the two titles confidently match per `_titles_confidently_match()` (never loose similarity);
    - the candidate's own acquisition reached a trusted completeness tier
      (`_SIBLING_REUSE_TRUSTED_STATUSES`) - never promotes another weak/failed acquisition;
    - the candidate is not itself a reuse row, and carries real text - the same one-hop invariant
      `_find_reuse_candidate()` already enforces;
    - within the existing `article_acquisition_reuse_window_hours` staleness window - reuses the
      existing bound, introduces no new one;
    - a different NewsEvent (never matches itself).

    Never creates or mutates a Story, never touches services/story_memory.py, never affects
    Telegram delivery - purely an acquisition-evidence upgrade, structurally identical in shape to
    the existing canonical-URL reuse path this function sits beside, just triggered by a different,
    later condition (a failed fetch, not a known-identical URL)."""
    if not news_event.published_at or not news_event.title:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.article_acquisition_reuse_window_hours)
    window_start = news_event.published_at - timedelta(seconds=_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS)
    window_end = news_event.published_at + timedelta(seconds=_SIBLING_REUSE_PUBLISHED_AT_TOLERANCE_SECONDS)
    stmt = (
        select(NewsEventArticleAcquisition, NewsEvent.title)
        .join(NewsEvent, NewsEvent.id == NewsEventArticleAcquisition.news_event_id)
        .where(
            NewsEventArticleAcquisition.news_event_id != news_event.id,
            NewsEventArticleAcquisition.reused_from_news_event_id.is_(None),
            NewsEventArticleAcquisition.raw_extracted_text.is_not(None),
            NewsEventArticleAcquisition.effective_completeness_status.in_(_SIBLING_REUSE_TRUSTED_STATUSES),
            NewsEventArticleAcquisition.created_at >= cutoff,
            NewsEvent.published_at >= window_start,
            NewsEvent.published_at <= window_end,
        )
        .order_by(NewsEventArticleAcquisition.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    for acquisition, candidate_title in rows:
        if _titles_confidently_match(news_event.title, candidate_title):
            logger.info(
                "article_acquisition_sibling_reused",
                extra={
                    "news_event_id": str(news_event.id),
                    "sibling_news_event_id": str(acquisition.news_event_id),
                },
            )
            return acquisition
    return None


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

    if outcome.status == ACQUISITION_STATUS_REDIRECT_UNRESOLVED:
        sibling = await _find_acquisition_failure_sibling(session, news_event)
        if sibling is not None:
            row = NewsEventArticleAcquisition(
                news_event_id=news_event.id, canonical_url=sibling.canonical_url,
                reused_from_news_event_id=sibling.news_event_id,
                acquisition_status=sibling.acquisition_status,
                effective_completeness_status=sibling.effective_completeness_status,
                cleaning_version=sibling.cleaning_version, triggered_by=triggered_by,
            )
            session.add(row)
            return row

    row = NewsEventArticleAcquisition(
        news_event_id=news_event.id, canonical_url=outcome.canonical_url,
        acquisition_status=outcome.status, raw_extracted_text=outcome.raw_extracted_text,
        effective_completeness_status=outcome.status, extracted_char_count=outcome.extracted_char_count,
        source_html_bytes=outcome.source_html_bytes, fetch_duration_ms=outcome.fetch_duration_ms,
        error_code=outcome.error_code, triggered_by=triggered_by,
    )
    session.add(row)

    if outcome.discovered_video_hints:
        await _persist_discovered_video_hints(session, event_id=news_event.id, hints=outcome.discovered_video_hints)

    return row


async def _persist_discovered_video_hints(session: AsyncSession, *, event_id: UUID, hints: list) -> None:
    """Phase 19 M10: best-effort, never allowed to affect article acquisition's own row above -
    an unapplied migration or any other persistence failure here degrades to a logged no-op,
    mirrors every other Phase 19 shadow-persistence call site's SAVEPOINT-guarded discipline."""
    from schemas.video_candidate import VideoPlatform
    from services.video_discovery import validate_direct_hosted_video, video_discovery_fetch_policy
    from services.video_discovery_persistence import persist_video_hint, unvalidated_hosted_platform_result

    try:
        async with session.begin_nested():
            for hint in hints:
                if hint.platform == VideoPlatform.UNKNOWN:
                    continue  # not a usable candidate - nothing gained by persisting it
                if hint.platform == VideoPlatform.DIRECT_HOSTED:
                    validation = await validate_direct_hosted_video(
                        hint.remote_url, policy=video_discovery_fetch_policy()
                    )
                else:
                    validation = unvalidated_hosted_platform_result()
                await persist_video_hint(session, event_id=event_id, hint=hint, validation=validation)
    except Exception:
        logger.warning("video_discovery_persistence_failed", extra={"event_id": str(event_id)})


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
