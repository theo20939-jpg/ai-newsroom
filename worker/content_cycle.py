"""One automation-content cycle: query eligible NEWS_ANALYSIS(COMPLETED) events, generate
CONTENT_GENERATION content for each via the existing, unmodified scripts/run_content_generation.py
pipeline, and send a Telegram notification for each resulting ContentDraft. No business logic of
its own - orchestration only (docs/phase14_autonomous_newsroom_implementation_plan.md §4)."""
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from aiogram import Bot
from aiogram.types import BufferedInputFile, MediaUnion
from sqlalchemy import exists, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from bot.formatting import CardTooLongError, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_source_only_keyboard
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import NewsEventArticleAcquisition
from database.models.news_source import NewsSource
from database.models.story_telegram_delivery import DeliveryStatus, DeliveryType
from database.session import async_session_factory
from schemas.editorial_route import EditorialDestination
from schemas.image_candidate import ImageDiscoveryMethod, ResolutionBand
from schemas.media_ranking import MediaRankingInput, MediaRankingResult
from schemas.workflow import WorkflowType
from scripts.run_content_generation import run_content_generation_for_event
from services.cost_tracker import CostTracker
from services.editorial_treatment import SKIP, EditorialTreatmentDecision, treatment_from_intelligence_and_evidence
from services.image_quality import aspect_ratio_band, hamming_distance, resolution_band
from services.image_relevance import PROVENANCE_TABLE
from services.media_ranking import _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE, rank_media_candidates
from services.story_duplicate_guard import check_duplicate_story_delivery, check_update_would_fail_closed
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    get_recently_attached_image_source_urls,
    sanitize_url,
)
from services.image_preview_notifier import build_rich_media_plan, send_news_with_image_preview
from services.news_telegram_presentation import (
    build_compact_news_body,
    is_v8_family_output,
    render_v81_news_card_html,
)
from services.pricing_catalog import PricingCatalog
from services.quote_lookup import get_quote_for_draft, resolve_display_text
from services.story_telegram_delivery import (
    FAIL_CLOSED_ROUTE_TO_REVIEW,
    determine_reply_target,
    get_root_delivery,
    persist_reply_routing_proposal,
    record_delivery,
)
from services.telegram_notifier import send_editorial_card, to_editorial_card
from services.telegram_routing import (
    send_media_group_to_editorial_destination,
    send_photo_to_editorial_destination,
    send_to_editorial_destination,
)

# Phase 23.1Q (Media Roadmap Recovery step 1): initial product cap on router-mode NEWS media-group
# delivery - "1 strong image for ordinary stories; 2-3 images only when additional images
# materially add useful visual information" (not to be raised without authorization).
_MAX_ROUTER_IMAGES = 3


# NEWS Output Stability Fix (Case E, docs/news_output_stability_forensic_report.md §6): the real
# Honor Robot Phone UPDATE delivered two images that were, in fact, the same underlying photo -
# one served directly from the publisher (9to5google.com/.../honor-robot-phone-2.jpg) and one
# served through WordPress/Jetpack's own "Photon" CDN proxy (i0.wp.com/9to5google.com/.../
# honor-robot-phone-2.jpg?resize=1200%2C628...). Their real, measured perceptual-hash Hamming
# distance is 9 - above the existing, calibrated <=4 threshold - so the existing hash-based check
# alone did not (and, evidenced against 15+ other same-base-filename real pairs in this dataset,
# should NOT be loosened to) catch it: raising the global threshold to 9 would also make several
# real, visually-DISTINCT differently-cropped variants of other real articles' images (measured
# Hamming distances of 22-33 for genuinely different crops of the same master photo, e.g. real
# Guardian/CNET/Verge candidates in this same dataset) register as false-positive duplicates. This
# is a narrow, additional, independent signal instead - not a threshold change, not a replacement
# for the existing hash-based check, and does not touch services/media_ranking.py's own cross-
# story reuse mechanism (find_story_reused_image_signatures()/is_perceptually_reused()) at all.
_IMAGE_CDN_PROXY_HOST_RE = re.compile(r"^i[0-3]\.wp\.com$", re.IGNORECASE)


# NEWS Stability Acceptance follow-up (multi-crop album dedup, docs/post_acceptance_followup_
# checkpoint.md §A): a WordPress "intermediate image size" filename suffix (e.g.
# "photo-1200x900.jpg", generated by WordPress itself from "photo.jpg") - a second, real,
# deterministic same-source-asset-identity pattern distinct from the query-string resize params
# already stripped by urlsplit()'s own path/query split below. Stripped from the PATH only, never
# the query string (which is dropped entirely regardless).
_WORDPRESS_DIMENSION_SUFFIX_RE = re.compile(r"-\d+x\d+(?=\.[A-Za-z0-9]+$)")


def _normalize_image_origin(url: str | None) -> str | None:
    """Pure. Strips a known CDN-proxy host prefix (WordPress/Jetpack Photon: i0-i3.wp.com, whose
    own URL path embeds the ORIGINAL host+path as its first path segment, e.g.
    "i0.wp.com/9to5google.com/wp-content/uploads/.../honor-robot-phone-2.jpg" - confirmed
    empirically: this pattern recurs across 25+ real candidates in this dataset, not a one-off)
    so the same underlying image served directly vs. through the proxy normalizes to the same
    signature. The query string (resize/quality/crop/strip params - never identity) is always
    stripped, and a trailing WordPress dimension suffix in the path itself (see _WORDPRESS_
    DIMENSION_SUFFIX_RE) is stripped too. Returns None for an empty/unparseable URL - never
    raises, never a false "match".

    Used for two independent purposes (see _compute_within_event_duplicate_flags()): gating the
    relaxed same-origin Hamming threshold (unchanged), and - as of the acceptance follow-up phase
    - as its own standalone, hash-independent same-source-asset-identity duplicate signal."""
    if not url:
        return None
    try:
        parsed = urlsplit(url)
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    path = parsed.path
    if _IMAGE_CDN_PROXY_HOST_RE.match(host):
        segments = path.lstrip("/").split("/", 1)
        if len(segments) == 2 and "." in segments[0]:
            host, path = segments[0].lower(), "/" + segments[1]
    if not host:
        return None
    path = _WORDPRESS_DIMENSION_SUFFIX_RE.sub("", path)
    return f"{host}{path}"


def _compute_within_event_duplicate_flags(candidates: list[EditorialImageCandidate]) -> dict[UUID, bool]:
    """Phase 23.1Q media-quality corrective phase, extended by the NEWS Stability Acceptance
    follow-up (docs/post_acceptance_followup_checkpoint.md §A): the earliest-appearing (best-
    ranked, since `candidates` already arrives ordered by the existing `rank` column) instance of
    any exact, same-source, or near-identical image always survives; only later occurrences in the
    same set are flagged. Three independent signals, checked in this priority order (cheapest/most
    certain first):

    1. Exact sha256 match.
    2. Same normalized image origin (_normalize_image_origin()) - a deterministic same-SOURCE-
       FILE identity signal, sufficient on its own, with NO hash-distance requirement. This is the
       acceptance-run fix: real acceptance-canary albums (the $70M SF-estate Guardian album and the
       Apple/iCloud Private Relay CNET album) presented the SAME underlying source photograph
       (identical host+path once query-string resize/crop params are stripped) 3 times each, at
       different crop/resize dimensions, with measured perceptual-Hamming distances of 12-28 -
       well above the old, narrower, origin-AND-hash-gated check this replaces (which required
       both a shared origin AND distance <=10; see git history / docs/post_acceptance_followup_
       checkpoint.md §A for why that combination is now provably insufficient - genuine same-
       source crop variants can differ far more than 10 in perceptual hash, since cropping to a
       different aspect ratio shifts the hash substantially). Per the product invariant "different
       transformations of the same source photograph must occupy only one album slot," sharing a
       source file is sufficient by itself - no perceptual corroboration required. A genuinely
       different photo of the same subject, hosted at a different path, is untouched by this
       check (its origin simply won't match).
    3. Perceptual distance within the existing global _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE
       (services/media_ranking.py, unchanged), regardless of origin - the general, origin-
       independent case (e.g. two exact re-encodes with no `final_url` recorded at all).

    Reuses services.image_quality.hamming_distance() and services.media_ranking's own already-
    calibrated near-duplicate threshold verbatim (imported, not re-declared) - never a second,
    divergent duplicate-detection rule for the general case, and never touches services/
    media_ranking.py's own cross-STORY reuse mechanism at all. A candidate with neither a hash nor
    a resolvable origin is never flagged - absence of evidence is not evidence of duplication."""
    seen_sha256: set[str] = set()
    seen_origins: set[str] = set()
    seen_hashes: list[str] = []
    flags: dict[UUID, bool] = {}
    for candidate in candidates:
        is_duplicate = False
        origin = _normalize_image_origin(candidate.final_url)
        if candidate.sha256 and candidate.sha256 in seen_sha256:
            is_duplicate = True
        elif origin is not None and origin in seen_origins:
            is_duplicate = True
        elif candidate.perceptual_hash:
            for known_hash in seen_hashes:
                if hamming_distance(candidate.perceptual_hash, known_hash) <= _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE:
                    is_duplicate = True
                    break
        flags[candidate.id] = is_duplicate
        if not is_duplicate:
            if candidate.sha256:
                seen_sha256.add(candidate.sha256)
            if origin is not None:
                seen_origins.add(origin)
            if candidate.perceptual_hash:
                seen_hashes.append(candidate.perceptual_hash)
    return flags


def _build_media_ranking_input(
    candidate: EditorialImageCandidate, *, is_duplicate_within_event: bool = False,
) -> MediaRankingInput:
    """Phase 23.1Q media wiring: assembles services.media_ranking.MediaRankingInput from an
    already-persisted EditorialImageCandidate's own already-computed signals (Phase 16 M3/M4's
    quality_warnings/relevance_score/discovery_method) - never recomputes any of them. Reuses
    services.image_relevance.PROVENANCE_TABLE (scaled to MediaRankingInput's own 0-20 range) and
    services.image_quality.aspect_ratio_band() directly - the same tables/functions the rest of
    the image pipeline already uses, never a second, divergent priority ordering.

    `is_duplicate_within_event` (Phase 23.1Q media-quality corrective phase): the caller resolves
    this via `_compute_within_event_duplicate_flags()` before calling this function - this
    function itself never computes it. `story_reuse_match` (M11's own cross-STORY reuse check,
    a separate concern from within-one-event duplication) remains unwired this phase - it would
    additionally require a resolved `story_id`, disclosed, not silently skipped."""
    try:
        method = ImageDiscoveryMethod(candidate.discovery_method)
    except ValueError:
        method = None
    warnings = candidate.warnings or []
    width, height = candidate.width, candidate.height
    return MediaRankingInput(
        media_item_id=candidate.id,
        media_type="image",
        quality_score=candidate.quality_score if candidate.quality_score is not None else 0,
        source_priority=round((PROVENANCE_TABLE.get(method, 20) if method is not None else 20) / 100 * 20),
        relevance_score=candidate.relevance_score,
        is_duplicate_within_event=is_duplicate_within_event,
        possible_logo="possible_logo" in warnings,
        possible_banner="possible_banner" in warnings,
        possible_watermark="possible_watermark" in warnings,
        possible_tv_lower_third="possible_tv_lower_third" in warnings,
        possible_branded_screenshot="possible_branded_screenshot" in warnings,
        aspect_ratio_band=aspect_ratio_band(width / height).value if width and height else None,
    )


def _meets_additional_album_image_bar(result: MediaRankingResult, candidate: EditorialImageCandidate) -> bool:
    """Phase 23.1Q media-quality corrective phase: the stricter bar a candidate must clear to
    become a SECOND/THIRD album image - never applied to the single best-ranked candidate, which
    keeps today's existing, unchanged `eligible_for_delivery` bar (an imperfect sole image can
    still beat text-only; the "important distinction" this function exists for is that the same
    candidate must NOT be allowed to merely pad out an album next to a genuinely strong hero image).

    Reuses two already-computed, already-calibrated signals only - no new classification
    subsystem, no arbitrary constant: `branding_risk` (already computed by rank_media_candidates()
    itself from the existing possible_logo/possible_banner/possible_watermark/possible_tv_lower_
    third/possible_branded_screenshot warnings) must be exactly 0, and `resolution_band()` (Phase
    16 M3's own already-calibrated dimension bands - services/image_quality.py) must be ADEQUATE or
    GOOD, never TRACKING/ICON/WEAK. Evidence this cleanly separates the real forensic examples
    (docs/media_quality_checkpoint.md): the confirmed-bad 96x96 possible_avatar (WEAK, risk=25),
    140x74 icon-shaped candidate (WEAK, risk=0 - no possible_* token evidence existed for this one,
    which is exactly why resolution_band alone, not branding_risk alone, is required), and 128x128
    possible_branded_screenshot (WEAK, risk=25) are all excluded; the confirmed-good hero examples
    (3000x1500, 1920x1005 - both GOOD, risk=0) are unaffected, since they are always the single
    best-ranked candidate, never subject to this stricter check at all."""
    if result.branding_risk > 0:
        return False
    if candidate.width is None or candidate.height is None:
        return False  # unknown dimensions - never assumed good enough to pad out an album
    band = resolution_band(candidate.width, candidate.height)
    return band not in (ResolutionBand.TRACKING, ResolutionBand.ICON, ResolutionBand.WEAK)


def _select_top_ranked_image_candidates(
    candidates: list[EditorialImageCandidate], *, limit: int,
) -> list[EditorialImageCandidate]:
    """Phase 23.1Q media wiring, tightened in the media-quality corrective phase: calls the
    existing, unmodified rank_media_candidates() (Phase 19 M11) and returns up to `limit`
    candidates in ranked order - never sends every discovered image, never reimplements the
    ranking itself, and never treats `limit` as a target (a candidate is only ever added because
    it earned its place, not to fill the cap - see _meets_additional_album_image_bar()'s own
    docstring). Within-event duplicates (exact sha256 or near-identical perceptual hash) are hard-
    excluded here, not merely deprioritized - `rank_media_candidates()`'s own `is_duplicate_
    within_event` penalty only affects composite score/ordering, never eligibility, so the actual
    "at most one survives" guarantee is enforced at this selection layer."""
    if not candidates:
        return []
    duplicate_flags = _compute_within_event_duplicate_flags(candidates)
    by_id = {c.id: c for c in candidates}
    inputs = [
        _build_media_ranking_input(c, is_duplicate_within_event=duplicate_flags.get(c.id, False))
        for c in candidates
    ]
    ranked = rank_media_candidates(inputs)
    eligible = [
        (r, by_id[r.media_item_id]) for r in ranked
        if r.eligible_for_delivery and r.media_item_id in by_id and not duplicate_flags.get(r.media_item_id, False)
    ]
    if not eligible:
        return []

    selected = [eligible[0][1]]  # the single best candidate keeps today's existing, unchanged bar
    for result, candidate in eligible[1:]:
        if len(selected) >= limit:
            break
        if _meets_additional_album_image_bar(result, candidate):
            selected.append(candidate)
    return selected

# Phase 23.1E: the label this codebase's Telegram NEWS presentation uses for the inline source
# button - matches the Russian-language editorial card it accompanies (docs/
# phase23_1e_telegram_news_compact_profile_report.md §10). bot/keyboards/image_preview.py::
# build_source_only_keyboard()'s own default ("🔗 Open source") is untouched and still used by
# every pre-existing caller (services/image_preview_notifier.py).
_NEWS_SOURCE_BUTTON_LABEL = "🔗 Источник"

logger = logging.getLogger(__name__)


@dataclass
class ContentCycleResult:
    eligible_found: int = 0
    completed: int = 0
    failed: int = 0
    notified: int = 0
    notification_failed: int = 0
    dry_run_rendered: int = 0
    # Phase 15 M5.8: counts drafts whose live send was withheld specifically because of a
    # "review"/"block" fact-safety verdict under fact_safety_mode == "enforce" - a strict subset
    # of dry_run_rendered (every fact-safety-suppressed send is also counted there), kept
    # separately so a cycle's own logs distinguish "global dry-run" from "fact safety intervened".
    # Always 0 outside "enforce" mode.
    fact_safety_suppressed: int = 0
    # Phase 16 M6 + UX fix (docs/phase16_m6_telegram_editorial_preview_report.md §7, docs/
    # phase16_ux_combined_preview_fix_report.md): a strict subset of `notified` - counts drafts
    # whose single delivered message actually had a photo attached (image_editorial_preview_
    # enabled AND image_candidate_persistence_mode != "off" AND at least one eligible candidate
    # existed). A completed draft with zero eligible image candidates still counts in `notified`
    # (its one message was still sent, just text-only) - not counted here, and not an error.
    image_preview_sent: int = 0
    event_ids: list[UUID] = field(default_factory=list)
    # Phase 18.10 M3 (Telegram reply context, story_memory_mode != "off" only - all zero
    # otherwise). `story_fail_closed_review`: an update whose story had no discoverable root
    # message - never sent as a standalone post, routed to review instead (see
    # services/story_telegram_delivery.py::determine_reply_target()'s own fail-closed contract).
    # `story_delivery_persistence_failed`: the live Telegram send itself succeeded, but durably
    # recording that fact failed immediately after - a real, physically-sent message this system
    # could not fully account for; logged at CRITICAL, never silently dropped.
    story_fail_closed_review: int = 0
    story_delivery_persistence_failed: int = 0
    # Phase 19 M7: counts a "would have been fail-closed" case under
    # telegram_story_reply_mode == "shadow" - the reply-routing proposal is persisted for review,
    # but (unlike story_fail_closed_review) the send still proceeds as a standalone post; this
    # counter is purely observational and never reflects a skipped send. Always 0 outside "shadow".
    story_reply_would_fail_closed_shadow: int = 0
    # Phase 23.1H: counts an event whose Editorial Treatment decision (services/
    # editorial_treatment.py) was SKIP, gated BEFORE run_content_generation_for_event() is ever
    # called - no Copywriting call, no ContentDraft, no Telegram send. Always 0 outside
    # editorial_delivery_mode == "router" (see _classify_event_for_router_treatment()'s own
    # docstring for why this is scoped to router mode only).
    treatment_skipped: int = 0
    # Phase 23.1H: a strict subset of `notified` - counts a router-mode NEWS send that attached a
    # real photo (send_photo, as opposed to send_message). Mirrors `image_preview_sent`'s own
    # established counting convention for the legacy image-preview path.
    router_image_sent: int = 0
    # Phase 23.1Q (Media Roadmap Recovery step 1): a strict subset of `notified`, disjoint from
    # `router_image_sent` - counts a router-mode NEWS send delivered as a real Telegram media
    # group (2-3 images, send_media_group), as opposed to a single photo or plain text.
    router_media_group_sent: int = 0
    # Phase 23.1I Part B: counts an event whose standalone NEWS delivery was blocked by
    # services/story_duplicate_guard.py because its Story already has a delivered root post and
    # this event's own Story Memory match_type is SEMANTIC_DUPLICATE/SUPPORTING_SOURCE. Always 0
    # whenever no NewsEventStoryLink exists (story_memory_mode == "off", today's real default).
    duplicate_blocked: int = 0
    # NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §B): counts
    # an update-equivalent event whose fail-closed non-deliverability (no resolvable root Telegram
    # message) was already definitively known BEFORE run_content_generation_for_event() was ever
    # called, so the paid Research/Copywriting call was skipped entirely. A strict subset of what
    # story_fail_closed_review used to count alone - this counter fires INSTEAD of
    # story_fail_closed_review for the cases caught here (the late check never runs for these, so
    # it can never double-count them). Always 0 outside telegram_story_reply_mode == "enforce".
    update_fail_closed_before_generation: int = 0


def _fact_safety_delivery_decision(
    base_dry_run: bool, fact_safety_mode: str, fact_safety_status: str | None
) -> tuple[bool, bool]:
    """Phase 15 M5.8 enforcement design, factored out as a pure function for direct unit testing.

    Returns `(effective_dry_run, was_fact_safety_suppressed)`. Suppression only ever applies
    under `fact_safety_mode == "enforce"` and only for a "review"/"block" verdict - a "pass"
    verdict, or any mode other than "enforce" (including a missing/None status - fact safety
    never ran), always leaves `base_dry_run` untouched."""
    suppressed = fact_safety_mode == "enforce" and fact_safety_status in ("review", "block")
    return (base_dry_run or suppressed), suppressed


def _extract_scoring_result(workflow: dict[str, Any] | None) -> int | None:
    """Locate the "scoring" entry in EditorialTask.workflow["step_results"] and return its
    result["score"] - None if absent (a task whose scoring step never ran or was skipped is
    defensively excluded, never defaulted to "pass"). Duplicated intentionally rather than
    imported from services/content_draft_service.py's own _copywriting_output() - that helper
    is scoped to "copywriting", a different step name and a different failure mode (raises
    instead of returning None), not a shared abstraction worth factoring out for one caller
    each (mirrors this codebase's own established per-module floor-validation duplication
    convention, e.g. capabilities/engagement_capability.py's own docstring)."""
    if not workflow:
        return None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "scoring" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                score = result.get("score")
                if isinstance(score, int):
                    return score
    return None


def _extract_intelligence_result(workflow: dict[str, Any] | None) -> tuple[float | int | None, str | None]:
    """Phase 23.1H: the "intelligence" step lives in the exact same NEWS_ANALYSIS `workflow`
    JSON blob `_extract_scoring_result()` already reads (`workflows/definitions/news_analysis.py`
    - research -> intelligence -> engagement_analysis -> scoring, one workflow) - reading it here
    costs zero additional queries beyond the one EditorialTask row `_classify_event_for_router_
    treatment()` already fetches. Returns `(significance, recommendation)`, both `None` if the
    step never ran/failed - `services/editorial_treatment.py`'s own `classify_editorial_treatment()`
    already treats a missing significance as its own conservative BRIEF+review default, never as
    "pass"."""
    if not workflow:
        return None, None
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "intelligence" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                return result.get("significance"), result.get("recommendation")
    return None, None


async def _classify_event_for_router_treatment(
    session: AsyncSession, event_id: UUID,
) -> EditorialTreatmentDecision:
    """Phase 23.1H: composes the exact same real, already-computed signals Phase 23.1G's offline
    replay validated (docs/phase23_1g_editorial_treatment_review.md) - Intelligence significance/
    recommendation and Scoring score from the NEWS_ANALYSIS task's own workflow, evidence
    completeness from `NewsEventArticleAcquisition` (already populated via `article_acquisition_
    mode=shadow`), source reliability as its documented fallback. Only called from the
    `editorial_delivery_mode == "router"` branch of the main loop below - every other delivery
    mode (today's real default, "legacy") never calls this function and is therefore byte-for-byte
    unaffected by this phase's work (Phase 23.1H report §"legacy regression")."""
    na_task = await session.scalar(
        select(EditorialTask)
        .where(
            EditorialTask.event_id == event_id,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.status == TaskStatus.COMPLETED,
        )
        .order_by(EditorialTask.updated_at.desc())
        .limit(1)
    )
    workflow = na_task.workflow if na_task is not None else None
    score = _extract_scoring_result(workflow)
    significance, recommendation = _extract_intelligence_result(workflow)

    acquisition = await session.scalar(
        select(NewsEventArticleAcquisition).where(NewsEventArticleAcquisition.news_event_id == event_id)
    )
    evidence_completeness = acquisition.effective_completeness_status if acquisition is not None else None

    source_reliability = await session.scalar(
        select(NewsSource.reliability_score)
        .join(NewsEvent, NewsEvent.source_id == NewsSource.id)
        .where(NewsEvent.id == event_id)
    )

    # Phase 23.1P: event_title/event_content feed only classify_editorial_treatment()'s own
    # narrow FETCH_FAILED-thin-content check (services/editorial_treatment.py::
    # _fetch_failed_content_is_thin() - the real Terraria regression fix, docs/
    # phase23_1p_story_memory_quotes_gate_report.md). No new query shape - title/content are
    # plain NewsEvent columns already loaded everywhere else in this same module.
    event_row = await session.get(NewsEvent, event_id)

    return treatment_from_intelligence_and_evidence(
        {"significance": significance, "recommendation": recommendation},
        {"score": score},
        source_reliability=source_reliability,
        evidence_completeness=evidence_completeness,
        event_title=event_row.title if event_row is not None else None,
        event_content=event_row.content if event_row is not None else None,
    )


def _telegram_utf16_length(text: str) -> int:
    """Duplicated from bot/formatting.py's own private `_telegram_utf16_length()` intentionally
    (that name is underscore-prefixed, module-private) - the exact same one-line UTF-16 code-unit
    formula (Telegram's length limits are measured in UTF-16 code units, not Python's `len()`)."""
    return len(text.encode("utf-16-le")) // 2


async def _select_eligible_events(session: AsyncSession) -> list[UUID]:
    """SQL-side: status, workflow-name match, duplicate exclusion (§3 of the Plan - the entire
    duplicate-prevention mechanism), freshness bound (a technical safety boundary only - see the
    Plan's own §0/§3, never an editorial-freshness control - unchanged by Phase 15 M5.2, still
    `EditorialTask.updated_at >= cutoff`), ordering, and a scan-limit cap are all evaluated by
    Postgres. Only the final, capped result rows are ever materialized into Python, for the
    score-threshold check below - the worker never loads an unbounded number of NEWS_ANALYSIS
    tasks (Plan §3's own scan-limit guarantee).

    Phase 15 M5.2: ordering changed from `EditorialTask.updated_at.asc()` (oldest-task-COMPLETED-
    first - a technical FIFO, not an editorial signal) to freshest-EDITORIAL-content-first, using
    the exact same `coalesce(NewsEvent.published_at, NewsEvent.collected_at)` anchor
    `worker/analysis_cycle.py::_select_eligible_task_ids()` already established as this
    codebase's one authoritative freshness field - not a new convention. Root cause this fixes
    (docs/phase15_m5_fact_safety_report.md, "M5.2..."): after any sustained processing gap (a
    provider outage, a burst of collection), old-task-completion-first ordering can starve
    genuinely fresh, high-scoring stories behind a backlog of older-but-still-cutoff-eligible
    tasks once that backlog exceeds `content_generation_scan_limit` - freshest-first ordering
    means a truly fresh eligible story is never pushed out of the scan window by an older one,
    regardless of backlog depth. The eligibility WHERE clause (which rows qualify at all) is
    completely unchanged - only the ordering of already-eligible rows, before LIMIT, changed.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.content_generation_freshness_cutoff_hours)
    ContentGenTask = aliased(EditorialTask)
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    stmt = (
        select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow)
        .join(NewsEvent, EditorialTask.event_id == NewsEvent.id)
        .where(
            EditorialTask.status == TaskStatus.COMPLETED,
            EditorialTask.workflow["workflow_name"].as_string() == WorkflowType.NEWS_ANALYSIS.value,
            EditorialTask.updated_at >= cutoff,
            ~exists(
                select(1)
                .select_from(ContentGenTask)
                .where(
                    ContentGenTask.event_id == EditorialTask.event_id,
                    ContentGenTask.workflow["workflow_name"].as_string() == WorkflowType.CONTENT_GENERATION.value,
                )
            ),
        )
        .order_by(anchor.desc(), EditorialTask.id.asc())
        .limit(settings.content_generation_scan_limit)
    )
    rows = (await session.execute(stmt)).all()

    # Score threshold applied here, in Python, over the already SQL-capped candidate set only -
    # NOT an unbounded backlog scan (bounded above by content_generation_scan_limit). Score
    # cannot be expressed in the same SQL statement: it lives at
    # workflow["step_results"][i]["result"]["score"] for the entry whose step_name == "scoring" -
    # locating an array element by a sibling field's value, then reading a nested key, inside a
    # generic (non-JSONB) JSON column is not cleanly expressible with this stack.
    eligible: list[UUID] = []
    for _task_id, event_id, workflow in rows:
        score = _extract_scoring_result(workflow)
        if score is not None and score >= settings.content_generation_min_score:
            eligible.append(event_id)
        if len(eligible) >= settings.content_generation_batch_size:
            break
    return eligible


async def run_content_cycle(
    capability_registry: CapabilityRegistry,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    *,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> ContentCycleResult:
    result = ContentCycleResult()

    async with session_factory() as session:
        event_ids = await _select_eligible_events(session)
    result.eligible_found = len(event_ids)
    result.event_ids = event_ids

    # Attempted one at a time, in selection order - identical convention to
    # worker/analysis_cycle.py, and for the same reason: bounded, predictable work per cycle;
    # no refill if one is skipped/fails.
    for event_id in event_ids:
        # Phase 23.1H: Editorial Treatment is applied BEFORE the (paid) Copywriting call whenever
        # router mode is active - matching the phase's own pipeline diagram (Scoring/Intelligence
        # -> Editorial Treatment -> V6 Copywriting) and saving the Copywriting cost entirely for a
        # SKIP decision, rather than generating a draft that would never be sent. Scoped to
        # "router" only - "legacy" (today's real default) never computes a treatment decision at
        # all, so it is completely unaffected by this phase (Phase 23.1H report §"legacy
        # regression").
        if settings.editorial_delivery_mode == "router":
            async with session_factory() as treatment_session:
                treatment_decision = await _classify_event_for_router_treatment(treatment_session, event_id)
            if treatment_decision.treatment == SKIP:
                result.treatment_skipped += 1
                logger.info(
                    "editorial_treatment_skip",
                    extra={"event_id": str(event_id), "reason": treatment_decision.reason},
                )
                continue

            # Phase 23.1I Part B: a Story that already has a delivered root NEWS post should not
            # immediately receive a second standalone post from a source Story Memory itself
            # already classifies as adding no material information (SEMANTIC_DUPLICATE/
            # SUPPORTING_SOURCE). Checked before the (paid) Copywriting call, same cost-saving
            # reasoning as the SKIP gate above. A no-op (never blocks) whenever no
            # NewsEventStoryLink exists for this event - i.e. whenever story_memory_mode was "off"
            # at triage time, today's real default - so this is purely additive, never a
            # regression, for every environment where Story Memory did not run.
            async with session_factory() as duplicate_session:
                duplicate_check = await check_duplicate_story_delivery(duplicate_session, event_id)
            if duplicate_check.blocked:
                result.duplicate_blocked += 1
                logger.info(
                    "router_duplicate_story_delivery_blocked",
                    extra={"event_id": str(event_id), "reason": duplicate_check.reason},
                )
                continue
        else:
            treatment_decision = None

        # NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §B):
        # checked BEFORE the paid run_content_generation_for_event() call below, unconditionally
        # (unlike the treatment/duplicate gates above, this is NOT scoped to router mode - the
        # late reply-routing check it mirrors, further below, isn't either; telegram_story_reply_
        # mode governs reply-threading independently of editorial_delivery_mode). A no-op unless
        # telegram_story_reply_mode == "enforce" AND this event is an update-equivalent Story
        # Memory match with no resolvable root - see check_update_would_fail_closed()'s own
        # docstring for why moving this exact check earlier is safe.
        async with session_factory() as update_fail_closed_session:
            update_fail_closed_check = await check_update_would_fail_closed(update_fail_closed_session, event_id)
        if update_fail_closed_check.would_fail_closed:
            result.update_fail_closed_before_generation += 1
            logger.warning(
                "story_update_fail_closed_no_root_message_before_generation",
                extra={
                    "event_id": str(event_id), "story_id": str(update_fail_closed_check.story_id),
                    "reason": update_fail_closed_check.reason,
                },
            )
            continue

        outcome = await run_content_generation_for_event(
            event_id, capability_registry=capability_registry, session_factory=session_factory,
            cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
        )  # scripts/run_content_generation.py - imported, not copied (Phase 15 M5 extends its
           # ContentGenerationOutcome with fact_safety_status; the call site here is unchanged)
        if outcome.content_draft is None:
            result.failed += 1
            continue
        result.completed += 1

        async with session_factory() as session:
            event = await session.get(NewsEvent, event_id)
        assert event is not None  # guaranteed by the FK the selecting query itself already joined on

        # Phase 15 M5.8 enforcement design: the safest existing non-public mechanism is the
        # notifier's own, already-established dry_run branch (renders and logs, never calls the
        # Telegram API) - reused verbatim here, never a new suppression code path. Inert (always
        # False) unless fact_safety_mode == "enforce"; a "pass" verdict never suppresses.
        effective_dry_run, fact_safety_suppressed = _fact_safety_delivery_decision(
            settings.content_generation_dry_run, settings.fact_safety_mode, outcome.fact_safety_status
        )
        if fact_safety_suppressed:
            result.fact_safety_suppressed += 1
            logger.info(
                "content_notification_suppressed_by_fact_safety",
                extra={
                    "event_id": str(event_id), "draft_id": str(outcome.content_draft.id),
                    "fact_safety_status": outcome.fact_safety_status,
                },
            )

        # Phase 19 M7 (docs/phase19_m7_story_timeline_and_reply_routing.md, "Correction 1" fix):
        # resolve this draft's story context (if any) and, for a confirmed update, the reply
        # target - before any Telegram call. Gated on telegram_story_reply_mode alone, never on
        # story_memory_mode - the Phase 18.10 M3 code this replaces was gated on
        # `story_memory_mode != "off"` directly, which meant story_memory_mode == "shadow" could
        # itself change Telegram delivery behavior (reply target, or a fail-closed skip),
        # contradicting "shadow never changes production behavior" (docs/phase19_m0_audit.md §7,
        # docs/phase19_m6_story_memory_calibration_report.md §3.1). "off" (default): no story_link
        # query at all, reply_to_message_id stays None - byte-identical to pre-18.10 behavior,
        # regardless of story_memory_mode. "shadow": the decision is computed and persisted
        # (services.story_telegram_delivery.persist_reply_routing_proposal) for review, but the
        # real send always proceeds as a standalone post - reply_to_message_id stays None and a
        # fail-closed case is never skipped (only counted, via story_reply_would_fail_closed_
        # shadow). "enforce": applies the decision to the real send, preserving the original
        # fail-closed skip-and-route-to-review guarantee.
        story_link: ContentDraftStoryLink | None = None
        reply_to_message_id: int | None = None
        if settings.telegram_story_reply_mode != "off":
            async with session_factory() as story_session:
                story_link = await story_session.get(ContentDraftStoryLink, outcome.content_draft.id)
                if story_link is not None:
                    root_delivery = await get_root_delivery(story_session, story_link.story_id)
                    root_message_id = root_delivery.telegram_message_id if root_delivery is not None else None
            if story_link is not None:
                reply_decision = determine_reply_target(
                    is_story_update=story_link.is_story_update, root_message_id=root_message_id,
                )
                is_enforce = settings.telegram_story_reply_mode == "enforce"

                try:
                    async with session_factory() as proposal_session:
                        await persist_reply_routing_proposal(
                            proposal_session, content_draft_id=outcome.content_draft.id,
                            story_id=story_link.story_id, decision=reply_decision, applied=is_enforce,
                        )
                        await proposal_session.commit()
                except Exception:
                    logger.warning(
                        "story_reply_routing_proposal_persistence_failed",
                        extra={"event_id": str(event_id), "draft_id": str(outcome.content_draft.id)},
                    )

                if reply_decision.action == FAIL_CLOSED_ROUTE_TO_REVIEW:
                    if is_enforce:
                        result.story_fail_closed_review += 1
                        logger.warning(
                            "story_update_fail_closed_no_root_message_routed_to_review",
                            extra={
                                "event_id": str(event_id), "draft_id": str(outcome.content_draft.id),
                                "story_id": str(story_link.story_id),
                            },
                        )
                        continue  # never sent as a standalone post - explicit, non-negotiable requirement
                    result.story_reply_would_fail_closed_shadow += 1
                    logger.info(
                        "story_update_would_fail_closed_shadow_still_sending_as_standalone",
                        extra={
                            "event_id": str(event_id), "draft_id": str(outcome.content_draft.id),
                            "story_id": str(story_link.story_id),
                        },
                    )
                elif is_enforce:
                    reply_to_message_id = reply_decision.reply_to_message_id

        # Phase 19 M5 (docs/phase19_m0_audit.md): resolve any persisted, verified quote before
        # either Telegram call - byte-identical to today (neither call site received a quote
        # before this milestone, despite one being persisted) unless quote_telegram_rendering_
        # mode == "enforce". "shadow" looks up and logs what would be sent, without passing it
        # through - proves the lookup/logging path works before ever changing real output.
        quote_text: str | None = None
        quote_speaker: str | None = None
        if settings.quote_telegram_rendering_mode != "off":
            async with session_factory() as quote_session:
                quote_row = await get_quote_for_draft(quote_session, outcome.content_draft.id)
            if quote_row is not None:
                resolved_text, resolved_speaker = resolve_display_text(quote_row)
                if settings.quote_telegram_rendering_mode == "shadow":
                    logger.info(
                        "quote_would_render",
                        extra={"event_id": str(event_id), "draft_id": str(outcome.content_draft.id)},
                    )
                else:  # "enforce"
                    quote_text, quote_speaker = resolved_text, resolved_speaker

        # Phase 16 UX fix (docs/phase16_ux_combined_preview_fix_report.md): exactly one message is
        # ever sent per draft - never both. Live validation of the original M6 design (a second,
        # additive image-preview message) found operators saw two separate messages for one news
        # item; this now branches to the single delivery path appropriate for the current
        # settings, instead of always sending the text card and then conditionally adding a
        # second one. `send_editorial_card()` itself is completely unchanged and remains the exact
        # path used whenever the image-preview flow is inactive (every currently-deployed
        # environment other than this one).
        sent_message_id: int | None = None
        sent_chat_id: int | None = None
        if settings.editorial_delivery_mode == "router":
            # Phase 23.1A canary delivery adapter (docs/phase23_1a_canary_delivery_adapter_
            # report.md) - an explicit, separate mode, checked first, never a replacement for the
            # two legacy branches below (both stay byte-identical when editorial_delivery_mode ==
            # "legacy", the default). Hardcoded to EditorialDestination.NEWS - the only
            # destination this branch is capable of reaching; there is no setting, parameter, or
            # code path here that can select MEME/TELEGRAPH/INSTAGRAM/REELS. Reuses the exact same
            # card mapping/rendering send_editorial_card() itself uses internally (services/
            # telegram_notifier.py::to_editorial_card() + bot/formatting.py::
            # render_editorial_card()) so router-mode output is byte-identical in content to what
            # legacy mode would have sent - only the destination/transport differs. Phase 23.1Q:
            # now also passes reply_to_message_id (resolved once, above, identically for every
            # delivery mode) into both real send calls below - previously computed here but
            # silently dropped for router mode only (services/telegram_routing.py's send
            # functions had no such parameter at all until this phase), a disclosed, now-closed
            # gap (docs/phase23_1p_story_memory_quotes_gate_report.md §"newly-discovered items").
            card = to_editorial_card(
                outcome.content_draft, event, quote_text=quote_text, quote_speaker=quote_speaker,
            )
            # Phase 23.1E (docs/phase23_1e_telegram_news_compact_profile_report.md): a compact,
            # destination-specific NEWS presentation, applied only here - MEME/TELEGRAPH/
            # INSTAGRAM/REELS (none of which this branch can ever reach, per its own hardcoded
            # EditorialDestination.NEWS above) keep the full, rich V6 material untouched, and so
            # does `outcome.content_draft.body` itself (persistence is completely unaffected -
            # this only changes what gets rendered into the Telegram message). Falls back to the
            # unmodified full-body/URL-in-body/no-keyboard behavior when the raw structured
            # copywriting output isn't available at all (a disclosed, safe degradation, never a
            # crash - report §13).
            keyboard = None
            # Phase 23.1H: resolved below, only inside the `copywriting_output is not None` branch
            # (the disclosed V4/no-structured-output fallback below keeps attaching no image at
            # all - same scope discipline as its own pre-existing "no keyboard either" behavior).
            photo_input: str | BufferedInputFile | None = None
            media_group_items: list[MediaUnion] = []
            image_candidate_count = 0
            # Phase 23.1K: pre-rendered directly for V8-family output (§2, docs/
            # phase23_1k_v82_live_canary_report.md) - bypasses card/render_editorial_card()
            # entirely, since V8/V8.1/V8.2's own simplified card shape (headline + one paragraph +
            # optional ending, no "📰 category · date" header row) is a genuinely different
            # template, not a body substitution into the existing one. Stays `None` for V4/V6/V7
            # output, which keep using the exact same `render_editorial_card()` path as always.
            html: str | None = None
            if outcome.copywriting_output is not None:
                assert treatment_decision is not None  # guaranteed: router mode reaches here only past the SKIP gate
                is_v8 = is_v8_family_output(outcome.copywriting_output)
                if is_v8:
                    html = render_v81_news_card_html(
                        outcome.copywriting_output, treatment=treatment_decision.treatment,
                        quote_text=quote_text, quote_speaker=quote_speaker,
                        include_ninja_pulse_footer=True,
                    )
                else:
                    compact_body = build_compact_news_body(outcome.copywriting_output, treatment=treatment_decision.treatment)
                    card = card.model_copy(update={"draft_body": compact_body})
                keyboard = build_source_only_keyboard(event.url, label=_NEWS_SOURCE_BUTTON_LABEL)
                include_url = False

                # Phase 23.1H media integration (docs/phase23_1h_text_image_canary_report.md
                # §"media architecture"): reuses the exact same candidate retrieval/ranking/
                # validation the legacy image-preview path already relies on
                # (get_editorial_image_candidates() only ever returns eligible_for_editorial=True
                # rows, ordered by rank) - no second discovery/ranking/validation pipeline. An
                # already-expired candidate row (`is_expired`, computed by the same function) is
                # treated exactly like "no candidate" - safe text-only fallback, never a crash.
                async with session_factory() as preview_session:
                    image_candidates = await get_editorial_image_candidates(
                        preview_session, content_draft_id=outcome.content_draft.id,
                    )
                    # Phase 23.1N Part J: a narrow, migration-free cross-event duplicate-image
                    # guard - services/image_deduplication.py only ever deduplicates *within* one
                    # event's own candidates, never across different stories. Exact
                    # normalized-URL match only (no perceptual hashing), against the rank-1
                    # candidate actually attached to each of the last few real drafts - never
                    # blocks the whole send, only skips a candidate whose image was already used
                    # on a different, unrelated recent post; falls through to the next-ranked
                    # candidate, and to text-only (never a crash) if every candidate is a repeat.
                    recently_used_urls = await get_recently_attached_image_source_urls(
                        preview_session, exclude_news_event_id=event.id,
                    )
                image_candidate_count = len(image_candidates)
                eligible_candidates: list[EditorialImageCandidate] = []
                for candidate in image_candidates:
                    if candidate.is_expired:
                        continue
                    if candidate.source_url and sanitize_url(candidate.source_url) in recently_used_urls:
                        logger.info(
                            "router_image_duplicate_skipped",
                            extra={"draft_id": str(outcome.content_draft.id), "source_url": candidate.source_url},
                        )
                        continue
                    eligible_candidates.append(candidate)

                if is_v8 and html is not None and eligible_candidates:
                    # Phase 23.1Q (Media Roadmap Recovery step 1): rank -> cap at
                    # _MAX_ROUTER_IMAGES -> build_rich_media_plan() (Phase 19 M11/M12, reused
                    # verbatim, never reimplemented). build_rich_media_plan() itself already
                    # skips any candidate whose resolve_photo_input() fails and continues to the
                    # next ranked one - a single broken image never kills the whole media
                    # opportunity. <2 resolved photos degrades to the existing single-photo
                    # variable below; 0 resolved photos leaves both empty (existing text-only
                    # fallback, unchanged).
                    top_candidates = _select_top_ranked_image_candidates(eligible_candidates, limit=_MAX_ROUTER_IMAGES)
                    plan = build_rich_media_plan(top_candidates, None, caption=html)
                    if len(plan.media_group_items) >= 2:
                        # Phase 23.1Q media-quality corrective phase: the real [🔗 Источник] button
                        # is attached to the group's first message AFTER sending (see the
                        # send_media_group_to_editorial_destination() call below) via aiogram's own
                        # edit_message_reply_markup() - a real Telegram Bot API mechanism for
                        # exactly this "media groups can't carry reply_markup at send time"
                        # limitation. The caption itself is therefore never modified - no in-
                        # caption source link (an earlier, rejected approach), same `html` and
                        # same CAPTION_SAFE_LIMIT budget as every other path.
                        media_group_items = plan.media_group_items
                    elif plan.media_group_items:
                        # A single resolved candidate - reuse the already-resolved photo directly
                        # from the plan (never re-resolve) via the existing single-photo path
                        # below. media is always str | BufferedInputFile here in practice (every
                        # item in media_group_items was built by build_rich_media_plan() from
                        # resolve_photo_input()'s own str | BufferedInputFile | None return type,
                        # already filtered to non-None) - aiogram's own InputMediaPhoto.media
                        # field is typed more broadly (str | InputFile) than this codebase's own
                        # narrower photo_input convention, hence the isinstance narrowing.
                        single_media = plan.media_group_items[0].media
                        photo_input = single_media if isinstance(single_media, (str, BufferedInputFile)) else None
                elif eligible_candidates:
                    # Legacy (V4/V6/V7) router-mode output - byte-identical to this branch's own
                    # pre-Phase-23.1Q behavior (never used by any real canary; V8-family output is
                    # the only shape any live send has ever produced), untouched by this phase.
                    photo_input = resolve_photo_input(eligible_candidates[0])
            else:
                include_url = True

            if html is None:
                try:
                    html = render_editorial_card(card, include_url=include_url)
                except CardTooLongError:
                    logger.error(
                        "content_notification_render_failed", extra={"draft_id": str(outcome.content_draft.id)},
                    )
                    result.notification_failed += 1
                    html = None

            if html is not None:
                # Phase 23.1H caption-length safety: a photo is only ever sent with the exact same
                # full, untruncated `html` this branch would otherwise send as plain text - never a
                # separately-squeezed/truncated caption. If that full text does not fit Telegram's
                # much smaller photo-caption limit (1024 UTF-16 code units vs. 4096 for a plain
                # message), the safest existing-architecture fallback is used: send it as the
                # ordinary full-text message instead (this exact same `send_to_editorial_
                # destination()` call, already used below for the no-image case) rather than force
                # a mid-sentence/word-boundary squeeze onto a MAJOR-tier post. This guarantees
                # zero blind truncation of treatment-selected text, at the cost of the image being
                # dropped for that one post - a disclosed, deliberate tradeoff (report
                # §"known limitations"), not a bug.
                # Phase 23.1Q: a media group is only ever sent within the exact same caption
                # budget as a single photo (Telegram's caption limit applies identically to the
                # first item of a media group) - the existing "drop media, fall back to plain
                # text" precedent above governs this case too, never a new truncation mechanism.
                fits_caption_budget = _telegram_utf16_length(html) <= CAPTION_SAFE_LIMIT
                send_as_media_group = len(media_group_items) >= 2 and fits_caption_budget
                send_as_photo = not send_as_media_group and photo_input is not None and fits_caption_budget
                logger.info(
                    "router_image_decision",
                    extra={
                        "draft_id": str(outcome.content_draft.id), "image_candidate_count": image_candidate_count,
                        "has_resolvable_photo": photo_input is not None, "send_as_photo": send_as_photo,
                        "media_group_item_count": len(media_group_items), "send_as_media_group": send_as_media_group,
                    },
                )
                if send_as_media_group:
                    routing_outcome = await send_media_group_to_editorial_destination(
                        bot, EditorialDestination.NEWS, media_group_items,
                        dry_run=effective_dry_run, reply_to_message_id=reply_to_message_id,
                        reply_markup=keyboard,
                    )
                elif send_as_photo:
                    assert photo_input is not None  # narrows for mypy; already checked above
                    routing_outcome = await send_photo_to_editorial_destination(
                        bot, EditorialDestination.NEWS, photo_input, html,
                        dry_run=effective_dry_run, reply_markup=keyboard,
                        reply_to_message_id=reply_to_message_id,
                    )
                else:
                    routing_outcome = await send_to_editorial_destination(
                        bot, EditorialDestination.NEWS, html, dry_run=effective_dry_run, reply_markup=keyboard,
                        reply_to_message_id=reply_to_message_id,
                    )
                if effective_dry_run:
                    result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
                elif routing_outcome.sent:
                    result.notified += 1
                    sent_message_id = routing_outcome.message_id
                    sent_chat_id = routing_outcome.chat_id
                    if send_as_media_group:
                        result.router_media_group_sent += 1
                    elif send_as_photo:
                        result.router_image_sent += 1
                else:
                    result.notification_failed += 1
        elif settings.image_editorial_preview_enabled and settings.image_candidate_persistence_mode != "off":
            try:
                async with session_factory() as preview_session:
                    combined_outcome = await send_news_with_image_preview(
                        bot, settings.editorial_chat_id, preview_session,
                        draft=outcome.content_draft, event=event, dry_run=effective_dry_run,
                        reply_to_message_id=reply_to_message_id,
                        quote_text=quote_text, quote_speaker=quote_speaker,
                    )
                if effective_dry_run:
                    result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
                elif combined_outcome.sent:
                    result.notified += 1
                    sent_message_id = combined_outcome.message_id
                    sent_chat_id = settings.editorial_chat_id
                    if combined_outcome.has_image:
                        result.image_preview_sent += 1
                else:
                    result.notification_failed += 1
            except Exception:
                logger.exception(
                    "image_preview_cycle_stage_unexpected_error",
                    extra={"event_id": str(event_id), "draft_id": str(outcome.content_draft.id)},
                )
                result.notification_failed += 1
        else:
            notification = await send_editorial_card(
                bot, settings.editorial_chat_id, outcome.content_draft, event,
                dry_run=effective_dry_run, reply_to_message_id=reply_to_message_id,
                quote_text=quote_text, quote_speaker=quote_speaker,
            )  # never raises - always returns a NotificationOutcome, dry-run or live
            if effective_dry_run:
                result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
            elif notification.sent:
                result.notified += 1
                sent_message_id = notification.message_id
                sent_chat_id = settings.editorial_chat_id
            else:
                result.notification_failed += 1
                # ContentDraft already committed - a failed notification is never rolled back and
                # never actively retried (no duplicate-notification protection for MVP; /news
                # remains the durable fallback for a lost push notification).

        # Phase 18.10 M3: durably record this send for a story-linked draft - "a send is not
        # successful unless telegram_message_id is persisted" (explicit requirement). Only
        # attempted for a real, non-dry-run send that actually returned a message_id; a dry-run
        # or failed send has nothing to record here (dry_run_rendered/notification_failed above
        # already account for those). The persistence attempt itself failing after a real,
        # physically-sent message is a distinct, honestly-logged case - never silently dropped,
        # never allowed to crash the cycle.
        if story_link is not None and sent_message_id is not None:
            try:
                async with session_factory() as delivery_session:
                    await record_delivery(
                        delivery_session,
                        story_id=story_link.story_id,
                        content_draft_id=outcome.content_draft.id,
                        telegram_chat_id=sent_chat_id,
                        telegram_message_id=sent_message_id,
                        reply_to_message_id=reply_to_message_id,
                        delivery_type=DeliveryType.REPLY if reply_to_message_id is not None else DeliveryType.ROOT,
                        delivery_status=DeliveryStatus.SENT,
                        sent_at=datetime.now(timezone.utc),
                    )
                    await delivery_session.commit()
            except Exception:
                result.story_delivery_persistence_failed += 1
                logger.critical(
                    "story_telegram_delivery_persistence_failed_after_real_send",
                    extra={
                        "event_id": str(event_id), "draft_id": str(outcome.content_draft.id),
                        "story_id": str(story_link.story_id), "telegram_message_id": sent_message_id,
                        "telegram_chat_id": sent_chat_id,
                    },
                )

    logger.info(
        "content_cycle_finished",
        extra={
            "eligible_found": result.eligible_found,
            "completed": result.completed,
            "failed": result.failed,
            "notified": result.notified,
            "notification_failed": result.notification_failed,
            "dry_run_rendered": result.dry_run_rendered,
            "fact_safety_suppressed": result.fact_safety_suppressed,
            "image_preview_sent": result.image_preview_sent,
            "story_fail_closed_review": result.story_fail_closed_review,
            "story_delivery_persistence_failed": result.story_delivery_persistence_failed,
        },
    )
    return result
