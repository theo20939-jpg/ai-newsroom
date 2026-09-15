"""One automation-content cycle: query eligible NEWS_ANALYSIS(COMPLETED) events, generate
CONTENT_GENERATION content for each via the existing, unmodified scripts/run_content_generation.py
pipeline, and send a Telegram notification for each resulting ContentDraft. No business logic of
its own - orchestration only (docs/phase14_autonomous_newsroom_implementation_plan.md §4)."""
import html
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from aiogram import Bot
from aiogram.types import BufferedInputFile, MediaUnion
from sqlalchemy import exists, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased

from bot.formatting import CardTooLongError, render_editorial_card
from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from bot.image_preview_media import resolve_photo_input
from bot.keyboards.image_preview import build_editorial_send_keyboard
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.director_editorial_decision import EditorialGateDecision
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
from scripts.run_content_generation import ContentGenerationOutcome, run_content_generation_for_event
from services.cost_tracker import CostTracker
from services.editorial_treatment import SKIP, EditorialTreatmentDecision, treatment_from_intelligence_and_evidence
from services.image_quality import aspect_ratio_band, hamming_distance, resolution_band
from services.image_relevance import PROVENANCE_TABLE
from services.media_ranking import _NEAR_DUPLICATE_MAX_HAMMING_DISTANCE, rank_media_candidates
from services.news_editorial_relevance import OUT_OF_SCOPE, classify_editorial_relevance
from services.brand_renderer import RenderResult, render_branded_media
from services.data_source_classification import classify_source_presentation, select_data_presentation_mode
from services.nnj_master_news_overlay import (
    NEWS_BRANDING_NO_SOURCE_BYTES,
    NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE,
    apply_master_news_branding,
)
from services.presentation_director import (
    BREAKING as PRESENTATION_BREAKING,
    CAPTION_ABOVE,
    DATA as PRESENTATION_DATA,
    NEWS as PRESENTATION_NEWS,
    QUOTE as PRESENTATION_QUOTE,
    build_editorial_code,
    decide_presentation,
)
from services.editorial_recomposition import RecompositionResult, maybe_recompose
from services.story_duplicate_guard import check_duplicate_story_delivery, check_update_would_fail_closed
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    get_recently_attached_image_source_urls,
    read_candidate_bytes,
    sanitize_url,
)
from services.image_preview_notifier import build_rich_media_plan, send_news_with_image_preview
from services.hosted_video_download import download_hosted_video
from services.video_discovery_persistence import (
    get_video_candidates_for_event,
    select_best_video_candidate,
    to_native_video_hint,
)
from services.video_quality_gate import VideoContentClassification, assess_video_text_signals
from schemas.video_candidate import VideoPlatform
from services.news_telegram_presentation import (
    build_compact_news_body,
    is_v8_family_output,
    render_compact_news_card_html,
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
from services.editorial_pipeline.telegram_integration import (
    is_unified_router_eligible,
    run_unified_telegram_delivery,
)
from services.director_editorial_gate_shadow import (
    STAGE2_BUDGET_EXHAUSTED as GATE_STAGE2_BUDGET_EXHAUSTED,
    STAGE2_FAILED_FELL_BACK as GATE_STAGE2_FAILED_FELL_BACK,
    STAGE2_USED as GATE_STAGE2_USED,
    reaches_editor_queue,
    run_pre_generation_gate,
)
from services.telegram_channel_director_shadow import run_channel_director_shadow
from services.telegram_notifier import send_editorial_card, to_editorial_card
from services.telegram_routing import (
    send_media_group_to_editorial_destination,
    send_photo_to_editorial_destination,
    send_to_editorial_destination,
    send_video_to_editorial_destination,
)
from services.instagram_automatic_trigger import (
    InstagramTriggerCycleReport,
    evaluate_and_submit_instagram_candidate,
    evaluate_and_submit_instagram_opportunity,
)
from services.director_execution_service import run_instagram_growth_strategist
from services.instagram_news_digest import (
    build_digest_opportunity,
    is_digest_due,
    mark_digest_run,
    select_digest_stories,
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

# iXBT production forensic (event d5b8d887-3176-4876-8640-4572ca3bcbe2): a second, more general
# "CDN wrapper embeds the original asset's identity" pattern than the Jetpack/Photon one above -
# here the wrapper embeds a full, scheme-qualified absolute URL (not just a bare host+path) after
# a resize/crop path segment, e.g. "media.ixbt.com/1200x900/smart/https://www.ixbt.com/img/n1/
# news/2026/7/1/MINISFORUM-NAS-N5-MAX-HERO_large.jpg" - four real candidates for the same source
# photo (1600x900, 1200x900, 1200x1200, fit-in/1729x900 crops) each normalized to a DIFFERENT
# string under the old logic (which never looked past the outer host), so
# _compute_within_event_duplicate_flags() marked all four as distinct and the selector put three
# of them in the same album. Deliberately generic (not an ixbt.com-specific substring rule): finds
# the first literal "http://"/"https://" occurrence anywhere in the OUTER url's path and treats
# everything from there onward as the real embedded source URL, ignoring whatever resize/crop
# wrapper segment precedes it - works for any CDN using this "wrapper-prefix + embedded absolute
# URL" convention, not just ixbt.com's.
_EMBEDDED_ABSOLUTE_URL_RE = re.compile(r"https?://.+", re.IGNORECASE)


def _embedded_source_origin(path: str) -> str | None:
    """Returns the embedded source URL's own "<host><path>" (query stripped, WordPress dimension
    suffix stripped - same semantics as the rest of `_normalize_image_origin()`) if `path`
    contains a literal embedded http(s):// URL, else None (the caller then falls back to today's
    existing normalization unchanged). Never guesses from a filename/basename alone - the full
    embedded path is used verbatim, so two different source files (even with the same basename,
    e.g. two different articles' own "hero.jpg") never collapse to the same origin; only the
    literal embedded URL string matters."""
    match = _EMBEDDED_ABSOLUTE_URL_RE.search(path)
    if match is None:
        return None
    try:
        embedded = urlsplit(match.group(0))
    except ValueError:
        return None
    embedded_host = (embedded.hostname or "").lower()
    if not embedded_host:
        return None
    embedded_path = _WORDPRESS_DIMENSION_SUFFIX_RE.sub("", embedded.path)
    return f"{embedded_host}{embedded_path}"


# Second iXBT production forensic (2026-08-17 canary, real post-fix album on event using
# ixbt-data asset ids 1289200/1289117): a DIFFERENT iXBT CDN convention from the embedded-
# absolute-URL one above - here the wrapper embeds no scheme at all, just a bare, stable
# "ixbt-data/<id>/<filename>" asset path after a variable-length resize/crop prefix, e.g.
# "media.ixbt.com/1200x1200/smart/ixbt-data/1289200/media-....jpg" vs "media.ixbt.com/1600x900/
# smart/jpeg/ixbt-data/1289200/media-....jpg" - both the SAME asset, but the transform-prefix
# segment count varies (2 segments vs 3), so it cannot be stripped by fixed path position. The
# sibling host media.ixbt.video uses the identical "ixbt-data/<id>/<filename>" convention
# (confirmed on a separate real event, asset id 1289117) - both hosts share the same underlying
# asset-storage naming, so both are included. Host-scoped (not a global "ixbt-data" substring
# rule): the marker string is specific enough on its own, but scoping to the two confirmed hosts
# is a free, zero-cost extra guard against an unrelated CDN coincidentally using the same path
# segment name.
_IXBT_ORIGIN_HOSTS = frozenset({"media.ixbt.com", "media.ixbt.video"})
_IXBT_STABLE_ASSET_MARKER = "ixbt-data/"

# MacRumors production forensic (2026-08-17 canary, real post-fix album, Siri animation asset):
# images.macrumors.com's own signed image-resize proxy embeds a stable "article-new/<yyyy>/<mm>/
# <filename>" asset path after a "/t/<signature>=/<variable transform>/" prefix, e.g.
# ".../t/5VqGjtmjIjCfOM8Sv0v-nzPfg54=/1600x/article-new/2026/03/ios-27-siri-animation.jpg" vs
# ".../t/K3APdjcvztsHADZNjOYSvOm3kEI=/1600x1200/smart/article-new/2026/03/ios-27-siri-
# animation.jpg" - same asset, different signature AND different transform-segment count (1 vs 2).
# A third, independent real sample (a different article, local dev DB) confirms the same
# "article-new/<yyyy>/<mm>/<filename>" shape recurs, not a one-off. Host-scoped to
# images.macrumors.com only - "article-new" reads as a CMS content-type folder name, plausible
# (if unconfirmed) on unrelated sites, so this marker is deliberately never applied globally.
_MACRUMORS_ORIGIN_HOSTS = frozenset({"images.macrumors.com"})
_MACRUMORS_STABLE_ASSET_MARKER = "article-new/"


def _marker_anchored_origin(host: str, path: str, *, allowed_hosts: frozenset[str], marker: str) -> str | None:
    """Generic helper behind both host-scoped marker rules above (never a new dedup subsystem -
    just a second and third application of the same "find a dataset-confirmed literal anchor,
    keep everything after it verbatim" principle `_embedded_source_origin()` already established).
    Returns None (caller falls through to existing normalization) unless `host` is one of
    `allowed_hosts` AND `marker` is literally present in `path` - never guesses, never reduces to
    a basename. The marker itself is kept as part of the returned path (not stripped), so the
    origin is unambiguously anchored at the same point for every transform variant."""
    if host not in allowed_hosts:
        return None
    index = path.find(marker)
    if index == -1:
        return None
    stable_path = _WORDPRESS_DIMENSION_SUFFIX_RE.sub("", path[index:])
    return f"{host}/{stable_path}"


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

    Also tries, in order, before falling through to the Jetpack/Photon and plain host+path logic
    below (never replacing them - a URL matching none of these falls through to the exact same
    behavior as before any of these additions):
    1. `_embedded_source_origin()` (iXBT forensic, embedded absolute URL - see its own docstring).
    2. iXBT `ixbt-data/` marker (`_IXBT_ORIGIN_HOSTS`/`_IXBT_STABLE_ASSET_MARKER` - see
       `_marker_anchored_origin()`'s own docstring and the constants' own forensic trail).
    3. MacRumors `article-new/` marker (`_MACRUMORS_ORIGIN_HOSTS`/`_MACRUMORS_STABLE_ASSET_MARKER`,
       same mechanism).

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

    embedded_origin = _embedded_source_origin(path)
    if embedded_origin is not None:
        return embedded_origin

    ixbt_origin = _marker_anchored_origin(
        host, path, allowed_hosts=_IXBT_ORIGIN_HOSTS, marker=_IXBT_STABLE_ASSET_MARKER,
    )
    if ixbt_origin is not None:
        return ixbt_origin

    macrumors_origin = _marker_anchored_origin(
        host, path, allowed_hosts=_MACRUMORS_ORIGIN_HOSTS, marker=_MACRUMORS_STABLE_ASSET_MARKER,
    )
    if macrumors_origin is not None:
        return macrumors_origin

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


def _meets_primary_image_bar(candidate: EditorialImageCandidate) -> bool:
    """2026-08-16 production forensic (Telegram NEWS image quality): the primary/rank-1 image
    used to inherit only the generic `eligible_for_delivery` bar - confirmed real production
    rank=1 candidates included 124x83 WEAK screenshots (quality=65) and a 328x328 Techmeme logo
    (possible_logo=True, possible_branded_screenshot=True, quality=51). The strict quality bar
    (`_meets_additional_album_image_bar()`) was only ever applied to SECOND/THIRD album slots, so
    a weak/logo image could still become the one photo actually sent to Telegram.

    Reuses the same already-calibrated `resolution_band()` (services/image_quality.py) this
    module's own album bar already relies on - no new classifier, no arbitrary pixel constant.
    `possible_logo` is read directly from the candidate's own persisted `warnings` (the same
    field `_build_media_ranking_input()` already reads it from) rather than from `branding_risk`:
    `branding_risk` is an aggregate of five separate possible_* signals, and the phase brief is
    explicit that `possible_branded_screenshot`/`possible_tv_lower_third`/`possible_watermark`/
    `possible_banner` must NOT become automatic primary-image failures this checkpoint (those
    classifiers are confirmed to produce false positives on real high-resolution images, e.g. the
    real 1600x899 Engadget candidate flagged possible_branded_screenshot + possible_tv_lower_
    third) - only the narrower, specific `possible_logo` signal is a hard primary-image failure.
    """
    if candidate.width is None or candidate.height is None:
        return False  # unknown dimensions - never assumed good enough to be the one sent photo
    band = resolution_band(candidate.width, candidate.height)
    if band not in (ResolutionBand.ADEQUATE, ResolutionBand.GOOD):
        return False
    return "possible_logo" not in (candidate.warnings or [])


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
    "at most one survives" guarantee is enforced at this selection layer.

    2026-08-16 production forensic: the single best-ranked candidate no longer automatically
    becomes the primary image - it must additionally clear `_meets_primary_image_bar()`. Ranked
    order is walked once; the first candidate clearing the primary bar becomes the primary image,
    and every OTHER candidate (both ones ranked above it that failed the primary bar, and ones
    ranked below it) is still evaluated for a SECOND/THIRD album slot via the pre-existing,
    unchanged `_meets_additional_album_image_bar()` - relative rank order is preserved throughout
    (deterministic, never reshuffled). If no candidate clears the primary bar at all, this
    returns `[]` - the caller (worker/content_cycle.py's own router branch) already degrades to
    its existing text-only send in that case; a known-bad image is never sent merely to avoid a
    text-only post."""
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

    primary: EditorialImageCandidate | None = None
    album_candidates: list[tuple[MediaRankingResult, EditorialImageCandidate]] = []
    for result, candidate in eligible:
        if primary is None and _meets_primary_image_bar(candidate):
            primary = candidate
        else:
            album_candidates.append((result, candidate))

    if primary is None:
        return []

    selected = [primary]
    for result, candidate in album_candidates:
        if len(selected) >= limit:
            break
        if _meets_additional_album_image_bar(result, candidate):
            selected.append(candidate)
    return selected


def resolve_recomposition_source_bytes(
    photo_input: str | BufferedInputFile | None, candidate: EditorialImageCandidate | None,
) -> bytes | None:
    """Phase V2.5 §7 - the fix for the real, previously-silent gap this phase set out to close:
    `photo_input` becoming a cached Telegram `file_id` (a plain `str`, whenever
    `resolve_photo_input()` finds one) meant `worker/content_cycle.py` could only ever extract
    `source_bytes` via `isinstance(photo_input, BufferedInputFile)` - so a candidate that had
    ALREADY been sent once (and so already had a cached file_id) could never reach recomposition
    again, even though its real bytes remained fully readable via `read_candidate_bytes()`.

    Telegram delivery representation and recomposition source bytes are separate concerns: this
    function resolves the latter independently, using the SAME already-selected `candidate` row -
    never a new discovery/ranking/fetch of any kind. `photo_input` already being real bytes
    (`BufferedInputFile`) is used directly (no redundant storage re-read); only when it is a
    cached file_id (or nothing was resolved at all) does this fall back to
    `services.image_persistence.read_candidate_bytes(candidate)`, which itself already returns
    `None` safely (never raises) for any unavailable/missing/unreadable case."""
    if isinstance(photo_input, BufferedInputFile):
        return photo_input.data
    if candidate is None:
        return None
    return read_candidate_bytes(candidate)


# Phase V2.7 §8 - the exact same deterministic warning flags services/media_ranking.py's own
# MediaRankingInput already derives from EditorialImageCandidate.warnings (Phase 16 M3/M4's
# quality_warnings signal) - never a new ML model, never a new signal invented for this phase.
_RECOMPOSITION_RISK_WARNINGS = frozenset({
    "possible_logo", "possible_banner", "possible_watermark",
    "possible_tv_lower_third", "possible_branded_screenshot",
})


def assess_recomposition_source_risk(candidate: EditorialImageCandidate | None) -> str | None:
    """Phase V2.7 §8 - the deterministic RECOMPOSE-vs-ORIGINAL_SOURCE risk gate: ORIGINAL_SOURCE
    is a first-class successful outcome, never merely an error fallback, whenever this already-
    computed signal flags elevated factual-preservation risk. Returns the first matching risk
    warning (a disclosed reason string, e.g. `"possible_branded_screenshot"`) when the candidate's
    own persisted `warnings` list contains one of the signals this project's own image pipeline
    already treats as reduced delivery trust; recomposition inherits the same caution rather than
    attempting to edit content already known to carry a logo/banner/watermark/lower-third/
    branded-screenshot risk. Returns `None` (no elevated risk detected from this signal) when
    `candidate` is `None` or carries no matching warning - NOT a claim the source is risk-free,
    only that this one deterministic, already-computed signal found nothing."""
    if candidate is None or not candidate.warnings:
        return None
    for warning in candidate.warnings:
        if warning in _RECOMPOSITION_RISK_WARNINGS:
            return warning
    return None


# Phase 23.1E: the label this codebase's Telegram NEWS presentation uses for the inline source
# button - matches the Russian-language editorial card it accompanies (docs/
# phase23_1e_telegram_news_compact_profile_report.md §10). bot/keyboards/image_preview.py::
# build_source_only_keyboard()'s own default ("🔗 Open source") is untouched and still used by
# every pre-existing caller (services/image_preview_notifier.py).
_NEWS_SOURCE_BUTTON_LABEL = "🔗 Источник"

# MEME PRODUCTION PIPELINE (overnight phase): module-scoped ImageStorage singleton for the
# automatic meme-generation trigger below - mirrors services/image_persistence.py::
# _get_storage()'s own identical private singleton pattern (duplicated, not imported - see that
# call site's own comment). Only ever constructed when settings.meme_opportunity_mode ==
# "enforce" (default "off") actually reaches the automatic-trigger block.
_meme_auto_storage_singleton = None

logger = logging.getLogger(__name__)

# TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 (Founder product invariant): an ordinary
# router-mode NEWS/BREAKING/DATA/QUOTE post must never silently complete as a normal finished
# text-only send merely because no valid final visual could be resolved/delivered. `content_
# drafts.status` is an existing, unconstrained varchar column that (before this phase) only ever
# received the literal "draft" at creation and was never read anywhere else - reused here rather
# than adding a new DB status/migration, per the phase's own "do not invent a new DB status
# unless necessary" instruction.
HOLD_FOR_VISUAL_STATUS = "hold_for_visual"

# Distinct root-cause strings persisted on the hold (structured audit, never free text) - mirrors
# this file's own established "one stable string per outcome" convention (e.g.
# NEWS_BRANDING_NO_SOURCE_BYTES below).
HOLD_REASON_NO_VISUAL_RESOLVED = "no_visual_resolved"
HOLD_REASON_MEDIA_SEND_FAILED = "media_send_failed"


async def _hold_for_visual_recovery(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, *,
    draft_id: UUID, event: NewsEvent, presentation_type: str, reason: str, dry_run: bool,
) -> None:
    """Founder invariant: HOLD instead of a normal finished text-only send (spec §9-D/§12/§13).

    Two, and only two, call sites use this (both already gated to the exact cases where a
    router-mode V8-family NEWS/BREAKING/DATA/QUOTE post is about to complete via the plain-text
    `send_to_editorial_destination()` path with no valid visual behind it):
    1. no visual was ever resolved at all (no source media, no renderable fallback);
    2. a visual WAS resolved and rendered, but the live Telegram photo/media-group/video send
       itself failed (the pre-existing one-shot text-fallback site).

    Does NOT touch the separate, pre-existing, disclosed caption-too-long-degrades-to-text
    tradeoff (Phase 23.1H/23.1Q) - that path keeps sending its real photo-bearing text exactly as
    before; a caption that does not fit a photo caption is a text-budget decision, not a missing
    visual, and is out of this phase's scope.

    Persists the failure (never loses the editorial content - `content_drafts.status` +
    `content_drafts.body`/`title` remain fully intact, only `status` changes) and sends one
    short, clearly non-editorial recovery notice to the same newsroom chat this draft would
    otherwise have posted to - deliberately NO inline keyboard (no Source/Meme buttons) and a
    distinct "⚠️" prefix, so it can never be mistaken for a real finished post. Reuses the
    existing `send_to_editorial_destination()` transport - no new Telegram integration, no new
    send path. Fully respects `dry_run` (never sends the recovery notice in dry-run, exactly
    like every other send in this file) and is itself a single, bounded, one-shot notice - never
    retried, never a loop.
    """
    async with session_factory() as session:
        await session.execute(
            update(ContentDraft).where(ContentDraft.id == draft_id).values(status=HOLD_FOR_VISUAL_STATUS)
        )
        await session.commit()
    logger.warning(
        "visual_required_hold",
        extra={
            "draft_id": str(draft_id), "event_id": str(event.id),
            "presentation_type": presentation_type, "hold_reason": reason,
        },
    )
    if dry_run:
        return
    notice_html = (
        "⚠️ <b>Требуется визуал — материал удержан для восстановления</b>\n"
        f"{html.escape(event.title or '', quote=False)}\n"
        f"Тип: {html.escape(presentation_type, quote=False)} · Причина: {html.escape(reason, quote=False)}"
    )
    await send_to_editorial_destination(
        bot, EditorialDestination.NEWS, notice_html, dry_run=False, reply_markup=None,
    )


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
    # INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1: additive, default None. INSTAGRAM-CONTENT-
    # STRATEGY-V2 Phase 4: `_run_instagram_automatic_trigger()` (the function this field's own
    # report comes from) is NO LONGER CALLED from run_content_cycle() below - replaced by
    # `instagram_news_digest_report` (see that field's own comment) - this field now always stays
    # None in real cycles, kept only so the function/its own dedicated 14+3-test suite remains a
    # valid, independently-testable unit (never deleted, just no longer wired into the live path).
    instagram_trigger_report: InstagramTriggerCycleReport | None = None
    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: the PRODUCT lane's own report - a completely separate
    # counter from `instagram_trigger_report` above (the NEWS lane), never merged into it, so each
    # lane's real production behavior stays independently observable. Additive, default None -
    # same "every pre-existing caller/test unaffected" convention as the field above.
    instagram_product_lane_report: InstagramTriggerCycleReport | None = None
    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: the NEWS_DIGEST lane's own report - REPLACES the old
    # per-story MAJOR-treatment NEWS trigger in the live cycle (see run_content_cycle()'s own call
    # site comment) - "do NOT leave both paths live" is enforced by this being the only NEWS-
    # sourced Instagram report the live cycle produces now.
    instagram_news_digest_report: InstagramTriggerCycleReport | None = None
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
    # Phase V2.27 §6: a strict subset of `notified`, disjoint from router_image_sent/router_
    # media_group_sent - counts a router-mode NEWS send delivered as a single native Telegram
    # video (send_video) with zero images attached at all (send_video_to_editorial_destination()).
    router_video_only_sent: int = 0
    # Delivery-gap fix (2026-08-16 production forensic - a completed draft's photo send timed
    # out and the whole post was silently dropped, notification_failed only): a strict subset of
    # `notified`, disjoint from router_image_sent/router_media_group_sent - counts a router-mode
    # NEWS send that only succeeded because the photo/media-group attempt returned sent=False and
    # the single plain-text fallback (send_to_editorial_destination(), same html/keyboard/
    # destination/reply_to_message_id) then succeeded. Mirrors router_image_sent/router_media_
    # group_sent's own established "strict subset of notified, named after the shape actually
    # delivered" counting convention.
    router_text_fallback_sent: int = 0
    # TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: counts a router-mode V8-family NEWS/BREAKING/
    # DATA/QUOTE post that would previously have completed as a normal finished text-only send
    # (either "no visual was ever resolved" or "a resolved visual's live Telegram send failed")
    # and was instead held for editor-visible recovery (see `_hold_for_visual_recovery()`).
    # Disjoint from `notified`/`notification_failed` - a held draft is neither a successful send
    # nor a bare failure, it is a deliberate, audited non-send. Never counted in `notified`.
    visual_required_held: int = 0
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
    # NINJA PULSE Visual System v1: counts every event this cycle whose PresentationDecision
    # resolved to BREAKING (services/presentation_director.py) - in both "shadow" and "enforce"
    # presentation_director_mode, purely as an in-memory, per-cycle count (no persistent 24h
    # frequency store - a disclosed, deliberate follow-up limitation, report §"known
    # limitations"). Threaded back into decide_presentation()'s own `breaking_count_this_cycle`
    # guard for every subsequent event in the same cycle, so a single cycle can never propose more
    # than `settings.presentation_breaking_max_per_cycle` BREAKING presentations. Always 0 when
    # presentation_director_mode == "off" (the default).
    presentation_breaking_sent: int = 0

    # DIRECTOR-CONTROL-PLANE-1A §8: Editorial Gate shadow comparison counters. All always 0 unless
    # gate_input assembly actually succeeds (services/director_editorial_gate_context.py returns
    # None only if the event row itself is already gone). `gate_would_have_reached_editor_before`
    # counts every event that reached this point in the loop at all (i.e. what the queue already
    # looked like with no gate); `gate_would_reach_editor_with_gate` counts only SEND_TO_EDITOR/
    # PRIORITY/BREAKING decisions - the real "what would change if this were ON" comparison spec
    # §8 asks for, computed and persisted regardless of whether telegram_editorial_gate_enabled is
    # True (shadow) - only the SUPPRESSION below (skipping generation) is flag-gated.
    gate_total_stories: int = 0
    gate_cheap_prefilter_passed: int = 0
    gate_director_reviewed: int = 0
    gate_drop: int = 0
    gate_hold: int = 0
    gate_send_to_editor: int = 0
    gate_priority: int = 0
    gate_breaking: int = 0
    gate_would_have_reached_editor_before: int = 0
    gate_would_reach_editor_with_gate: int = 0
    # Strict subset of the above - counts an event whose generation was actually SKIPPED because
    # telegram_editorial_gate_enabled was True and the gate decided DROP/HOLD. Always 0 while the
    # flag is False (spec §7's own "OFF -> normal Founder NEWS queue remains unchanged" contract).
    gate_generation_suppressed: int = 0
    # DIRECTOR-CONTROL-PLANE-1B §2-4/§22: bounded Stage 2 (real Director LLM) observability.
    # gate_stage2_llm_used counts escalation-worthy candidates that got a real Gateway-backed
    # judgment; gate_stage2_fell_back counts ones where the provider failed and the Stage 1
    # deterministic outcome was kept (fail-soft); gate_stage2_budget_exhausted counts ones the
    # daily director_editorial_gate_max_llm_reviews_per_day bound turned away. All 0 unless a real
    # gateway was threaded through (worker/content_main.py's live call site).
    gate_stage2_llm_used: int = 0
    gate_stage2_fell_back: int = 0
    gate_stage2_budget_exhausted: int = 0


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


def _extract_research_facts(workflow: dict[str, Any] | None) -> list[str]:
    """Mirrors `_extract_scoring_result()`/`_extract_intelligence_result()`'s own exact shape -
    the "research" step's `result["facts"]`, `[]` if the step never ran/failed or `facts` isn't a
    list of strings. Used only by `services/presentation_director.py`'s DATA grounding (never a
    new signal for selection/scoring/treatment - those remain completely unchanged)."""
    if not workflow:
        return []
    for step_result in workflow.get("step_results", []):
        if step_result.get("step_name") == "research" and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            if isinstance(result, dict):
                facts = result.get("facts")
                if isinstance(facts, list):
                    return [f for f in facts if isinstance(f, str)]
    return []


async def _fetch_router_presentation_signals(session: AsyncSession, event_id: UUID) -> tuple[list[str], int | None]:
    """NINJA PULSE Visual System v1: a second, deliberately separate, bounded per-event query for
    the same NEWS_ANALYSIS task `_classify_event_for_router_treatment()` above already reads -
    duplicated rather than threading a wider return type through that heavily-depended-on function
    (44+ existing mocked call sites across tests/scripts - see report §"scope decisions"). Exactly
    as bounded as the image-candidate/quote/video lookups this same loop already performs once per
    event; never a query over more than one task."""
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
    return _extract_research_facts(workflow), _extract_scoring_result(workflow)


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
    score-threshold-and-ranking step below - the worker never loads an unbounded number of
    NEWS_ANALYSIS tasks (Plan §3's own scan-limit guarantee).

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

    2026-08-15 forensic recalibration: this SQL ordering still establishes the bounded fresh scan
    window exactly as before, but is no longer the final selection order - see the score-ranking
    step below, which reuses this same (anchor DESC, id ASC) order as the freshness/stable
    tie-break for its own score-DESC ranking.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.content_generation_freshness_cutoff_hours)
    ContentGenTask = aliased(EditorialTask)
    anchor = func.coalesce(NewsEvent.published_at, NewsEvent.collected_at)

    stmt = (
        select(EditorialTask.id, EditorialTask.event_id, EditorialTask.workflow, NewsEvent.title, NewsEvent.content)
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
    #
    # 2026-08-15 forensic recalibration: this used to take the first `content_generation_
    # batch_size` score-eligible rows in freshness order (i.e. "newest eligible stories first"),
    # never comparing scores against each other - on a weak news day that fills the batch with
    # whatever cleared 70 first, even when a materially stronger story was sitting a few rows
    # further down the same bounded scan window. Quality now determines rank *within* that same
    # bounded fresh window: every score-eligible row in `rows` (still capped by scan_limit, still
    # only rows inside the freshness cutoff - no wider query) is collected first, then ranked by
    # score DESC. `rows` is already ordered (anchor DESC, EditorialTask.id ASC) by the SQL ORDER BY
    # above; Python's sort() is guaranteed stable (reverse=True does not disturb tie order - see
    # the stdlib sorted() docs), so a single sort on the composite key preserves that existing
    # order as the secondary (freshest first) and tertiary (EditorialTask.id ascending) tie-break,
    # exactly the ranking this checkpoint asks for, with no second query and no new tie-break rule
    # to keep in sync with the SQL ORDER BY.
    #
    # Topic-skew fix: `Scoring.score` alone has no topical awareness (a well-evidenced funding
    # story and a well-evidenced product launch score identically). `classify_editorial_relevance()`
    # (services/news_editorial_relevance.py) is a pure, deterministic, LLM-free function of the
    # same title/content already loaded above - it never touches `Scoring.score` itself, only
    # contributes a small `rank_adjustment` used purely for this in-Python ranking. OUT_OF_SCOPE
    # candidates (unambiguous non-tech noise) are hard-excluded here, same as a failed score check.
    eligible: list[tuple[int, UUID]] = []
    for _task_id, event_id, workflow, title, content in rows:
        score = _extract_scoring_result(workflow)
        if score is None or score < settings.content_generation_min_score:
            continue
        relevance = classify_editorial_relevance(title, content)
        if relevance.tier == OUT_OF_SCOPE:
            continue
        eligible.append((score + relevance.rank_adjustment, event_id))

    eligible.sort(key=lambda candidate: candidate[0], reverse=True)

    # Fewer than batch_size eligible candidates is a valid, product-intended outcome (a weak news
    # period must be allowed to produce fewer stories) - never padded with sub-threshold rows.
    return [event_id for _rank, event_id in eligible[: settings.content_generation_batch_size]]


# INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1 §10: a pure rollout-safety throughput cap, deliberately
# NOT an editorial policy - MAJOR-treatment stories beyond this count in one cycle are simply
# picked up on the NEXT cycle (the same event stays eligible until _select_eligible_events()'s own
# existing freshness cutoff excludes it), never dropped/rejected. Separate from and orthogonal to
# `_ELIGIBLE_TREATMENTS` (services/instagram_automatic_trigger.py), which is the actual editorial
# selection criterion. Raise this once real production volume validates it is safe to.
_INSTAGRAM_TRIGGER_MAX_PER_CYCLE = 3


async def _run_instagram_automatic_trigger(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, event_ids: list[UUID], *,
    gate_gateway: object | None, gate_prompt_repository: object | None,
) -> InstagramTriggerCycleReport:
    """§6: a completely separate loop from the main NEWS content-generation loop below - reuses
    the SAME already-computed `event_ids` (bounded, fresh, already-eligible per
    `_select_eligible_events()`), but Instagram submission never depends on and can never affect
    NEWS content generation/delivery (§6's own "do not couple Instagram generation to Telegram
    delivery success"). `gate_gateway`/`gate_prompt_repository` being `None` (every test that does
    not opt in, exactly like the existing Director pre-generation gate above) makes this a
    complete, safe no-op - no second gateway is ever constructed here.

    Per-story failures are caught and logged, never propagated - one story's Creative Director
    error, DB hiccup, or Telegram failure must never abort the scan for the remaining candidates
    or crash the worker cycle (§8 crash safety)."""
    report = InstagramTriggerCycleReport()
    if gate_gateway is None or gate_prompt_repository is None:
        return report

    accepted = 0
    rejected = 0
    ready = 0
    hold = 0
    block = 0
    delivered = 0
    dup_submissions = 0
    dup_deliveries = 0
    candidates: list[Any] = []

    for event_id in event_ids[:_INSTAGRAM_TRIGGER_MAX_PER_CYCLE]:
        try:
            async with session_factory() as session:
                treatment = await _classify_event_for_router_treatment(session, event_id)
                event_row = await session.get(NewsEvent, event_id)
                if event_row is None:
                    continue
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
                facts = _extract_research_facts(na_task.workflow if na_task is not None else None)

                outcome = await evaluate_and_submit_instagram_candidate(
                    session, bot, event_id=str(event_id), event_title=event_row.title or "", treatment=treatment,
                    research_facts=facts, gateway=gate_gateway, prompt_repository=gate_prompt_repository,
                    source_url=event_row.url,
                )
                await session.commit()
        except Exception:
            logger.exception("instagram_automatic_trigger_candidate_failed", extra={"event_id": str(event_id)})
            continue

        candidates.append(outcome)
        if not outcome.accepted:
            rejected += 1
            continue
        accepted += 1
        if outcome.reason == "already_submitted":
            dup_submissions += 1
            continue
        if outcome.gate_decision == "ready_for_editor":
            ready += 1
        elif outcome.gate_decision == "hold":
            hold += 1
        elif outcome.gate_decision == "block":
            block += 1
        if outcome.delivery_sent:
            delivered += 1
        elif outcome.delivery_reason == "duplicate_skipped":
            dup_deliveries += 1

    report = InstagramTriggerCycleReport(
        stories_evaluated=len(candidates), opportunities_accepted=accepted, opportunities_rejected=rejected,
        packages_ready=ready, packages_hold=hold, packages_block=block, packages_delivered=delivered,
        duplicate_submissions_suppressed=dup_submissions, duplicate_deliveries_suppressed=dup_deliveries,
        candidates=candidates,
    )
    if report.stories_evaluated:
        logger.info("instagram_automatic_trigger_cycle_finished", extra=report.as_log_extra())
    return report


# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: a brand-new, never-before-live lane - conservative,
# deliberately smaller than _INSTAGRAM_TRIGGER_MAX_PER_CYCLE (the already-observed NEWS lane).
# Raise once real production volume validates it is safe to, exactly like that constant's own
# established precedent.
_INSTAGRAM_PRODUCT_LANE_MAX_PER_CYCLE = 1


async def _run_instagram_product_lane(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, *,
    gate_gateway: object | None, gate_prompt_repository: object | None,
) -> InstagramTriggerCycleReport:
    """INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: the PRODUCT lane, wired through the EXISTING
    `generate_growth_strategy()` ranking (services/director_execution_service.py::
    run_instagram_growth_strategist(), previously only consumed by the read-only `/plan` command)
    instead of a hand-rolled opportunity - this is the "generalize the existing automatic trigger…
    wire generate_growth_strategy() into the real execution path" requirement. Completely
    independent of the NEWS lane above (§6's own "do not couple" principle applies to every lane,
    not just NEWS) - a failure here can never affect `_run_instagram_automatic_trigger()`, and
    vice versa. A safe no-op whenever `gate_gateway`/`gate_prompt_repository` are `None`, exactly
    like that function's own contract."""
    report = InstagramTriggerCycleReport()
    if gate_gateway is None or gate_prompt_repository is None:
        return report

    try:
        async with session_factory() as session:
            result = await run_instagram_growth_strategist(session, now=datetime.now(timezone.utc))
            await session.commit()
            top_opportunities = result.strategy.priority_opportunities[:_INSTAGRAM_PRODUCT_LANE_MAX_PER_CYCLE]
    except Exception:
        logger.exception("instagram_product_lane_ranking_failed")
        return report

    candidates: list[Any] = []
    accepted = ready = hold = block = delivered = dup_submissions = 0
    for opportunity in top_opportunities:
        try:
            async with session_factory() as session:
                summary = f"NINJA product update (product_id={opportunity.product_id})"
                outcome = await evaluate_and_submit_instagram_opportunity(
                    session, bot, opportunity=opportunity, opportunity_summary=summary,
                    gateway=gate_gateway, prompt_repository=gate_prompt_repository,
                )
                await session.commit()
        except Exception:
            logger.exception("instagram_product_lane_candidate_failed", extra={"opportunity_id": opportunity.id})
            continue

        candidates.append(outcome)
        if not outcome.accepted:
            continue
        accepted += 1
        if outcome.reason == "already_submitted":
            dup_submissions += 1
            continue
        if outcome.gate_decision == "ready_for_editor":
            ready += 1
        elif outcome.gate_decision == "hold":
            hold += 1
        elif outcome.gate_decision == "block":
            block += 1
        if outcome.delivery_sent:
            delivered += 1

    report = InstagramTriggerCycleReport(
        stories_evaluated=len(candidates), opportunities_accepted=accepted, opportunities_rejected=0,
        packages_ready=ready, packages_hold=hold, packages_block=block, packages_delivered=delivered,
        duplicate_submissions_suppressed=dup_submissions, duplicate_deliveries_suppressed=0, candidates=candidates,
    )
    if report.stories_evaluated:
        logger.info("instagram_product_lane_cycle_finished", extra=report.as_log_extra())
    return report


async def _run_instagram_news_digest_lane(
    session_factory: async_sessionmaker[AsyncSession], bot: Bot, *,
    gate_gateway: object | None, gate_prompt_repository: object | None,
) -> InstagramTriggerCycleReport:
    """INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: ONE Instagram carousel every 72h summarizing the
    newsroom's OWN strongest recent stories - REPLACES the old per-story MAJOR-treatment NEWS
    trigger (`_run_instagram_automatic_trigger()` above is no longer called from
    `run_content_cycle()` - see that call site's own comment for why both paths are never live at
    once). A normal individual NEWS story may still reach Instagram, but only through the future
    TREND lane's own independent evidence - never through NEWS treatment alone.

    Cadence: the schedule advances (`mark_digest_run()`) on every DUE check, whether or not the
    window actually had enough strong stories to build a digest from - a weak 72h window is a
    real, honest "no digest this time" outcome, never retried every cycle until the SAME window
    magically improves; the next real check is roughly another 72h later, giving genuinely fresh
    news time to accumulate. Safe no-op whenever gate_gateway/gate_prompt_repository are None,
    same contract as the other two lanes."""
    report = InstagramTriggerCycleReport()
    if gate_gateway is None or gate_prompt_repository is None:
        return report

    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as session:
            due = await is_digest_due(session, now=now)
            if not due:
                return report
            stories = await select_digest_stories(session, now=now)
            await mark_digest_run(session, now=now)
    except Exception:
        logger.exception("instagram_news_digest_scheduling_failed")
        return report

    if not stories:
        logger.info("instagram_news_digest_window_had_no_strong_stories")
        return report

    opportunity = build_digest_opportunity(stories, now=now)
    candidates: list[Any] = []
    ready = hold = block = delivered = dup_submissions = 0
    try:
        async with session_factory() as session:
            summary = "NINJA Newsroom digest: " + "; ".join(s.title for s in stories[:3])
            outcome = await evaluate_and_submit_instagram_opportunity(
                session, bot, opportunity=opportunity, opportunity_summary=summary,
                gateway=gate_gateway, prompt_repository=gate_prompt_repository, has_multi_step_narrative=True,
            )
            await session.commit()
    except Exception:
        logger.exception("instagram_news_digest_candidate_failed", extra={"opportunity_id": opportunity.id})
        return report

    candidates.append(outcome)
    accepted = 1 if outcome.accepted else 0
    if outcome.accepted and outcome.reason != "already_submitted":
        if outcome.gate_decision == "ready_for_editor":
            ready += 1
        elif outcome.gate_decision == "hold":
            hold += 1
        elif outcome.gate_decision == "block":
            block += 1
        if outcome.delivery_sent:
            delivered += 1
    elif outcome.reason == "already_submitted":
        dup_submissions += 1

    report = InstagramTriggerCycleReport(
        stories_evaluated=len(candidates), opportunities_accepted=accepted, opportunities_rejected=0,
        packages_ready=ready, packages_hold=hold, packages_block=block, packages_delivered=delivered,
        duplicate_submissions_suppressed=dup_submissions, duplicate_deliveries_suppressed=0, candidates=candidates,
    )
    logger.info("instagram_news_digest_cycle_finished", extra=report.as_log_extra())
    return report


async def run_content_cycle(
    capability_registry: CapabilityRegistry,
    bot: Bot,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    *,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
    event_ids_override: list[UUID] | None = None,
    precomputed_outcomes: dict[UUID, ContentGenerationOutcome] | None = None,
    # DIRECTOR-CONTROL-PLANE-1B §2: the real LLMGateway + PromptRepository, threaded straight
    # through to services/director_editorial_gate_shadow.py::run_pre_generation_gate() for its
    # bounded Stage 2 Director judgment. Deliberately typed `object | None` here (never the real
    # protocol types) so this module still imports NOTHING from integrations.llm_gateway.* -
    # test_i_content_cycle_module_imports_no_llm_gateway_or_capability_execution's own structural
    # boundary. `None` (every test that does not opt in) -> Stage-1-only gate, unchanged behavior.
    gate_gateway: object | None = None,
    gate_prompt_repository: object | None = None,
) -> ContentCycleResult:
    """`event_ids_override` (Phase V2.6 §3): when provided, replaces the normal
    `_select_eligible_events()` scan entirely - the loop below still runs its exact, unmodified
    per-event body (content generation, delivery, recomposition, branding), just for exactly the
    caller-supplied event ids instead of whatever the normal eligibility/freshness/score scan
    would have found. Every real production caller (`worker/content_main.py`) leaves this `None`,
    the byte-identical, unchanged default behavior. Exists so a bounded, explicit one-story canary
    can exercise the SAME real function - never a second, duplicated copy of this loop's body -
    without risking an unbounded backlog scan or an indefinite service loop."""
    result = ContentCycleResult()

    if event_ids_override is not None:
        event_ids = event_ids_override
    else:
        async with session_factory() as session:
            event_ids = await _select_eligible_events(session)
    result.eligible_found = len(event_ids)
    result.event_ids = event_ids

    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: the old per-story MAJOR-treatment NEWS->Instagram
    # trigger (INSTAGRAM-AUTOMATIC-EDITORIAL-TRIGGER-1, `_run_instagram_automatic_trigger()`
    # above) is DELIBERATELY NO LONGER CALLED HERE - "do NOT leave both paths live". It is
    # REPLACED by the NEWS_DIGEST lane below (ONE carousel every 72h, never one post per story). A
    # normal individual NEWS story may still reach Instagram, but only through the future TREND
    # lane's own independent evidence - never through NEWS treatment alone. The function itself
    # (and its own 14+3-test suite) is kept, unmodified, as a documented, independently-testable
    # unit - it is simply unreachable from this live cycle now (see
    # tests/test_instagram_content_strategy_v2_phase4_news_digest_wiring.py's own structural
    # regression test proving exactly that).
    result.instagram_news_digest_report = await _run_instagram_news_digest_lane(
        session_factory, bot, gate_gateway=gate_gateway, gate_prompt_repository=gate_prompt_repository,
    )

    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2: the PRODUCT lane - independent of and never coupled
    # to the NEWS lane immediately above or the NEWS content-generation loop below (same "do not
    # couple" principle, applied to a second lane). A safe no-op whenever gate_gateway/
    # gate_prompt_repository are None, same contract as the NEWS lane.
    result.instagram_product_lane_report = await _run_instagram_product_lane(
        session_factory, bot, gate_gateway=gate_gateway, gate_prompt_repository=gate_prompt_repository,
    )

    # MEME PRODUCTION PIPELINE (overnight phase): bounded per-cycle cap on automatic meme
    # generation attempts - inert (settings.meme_auto_max_candidates_per_cycle is never even
    # read) unless settings.meme_opportunity_mode == "enforce" (default "off").
    meme_auto_triggered_count = 0

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

        # DIRECTOR-CONTROL-PLANE-1A §2-8: the Director Editorial Gate - BEFORE the paid
        # run_content_generation_for_event() call below, for every delivery mode (unlike the
        # router-only treatment/duplicate gates above). Always computes and persists a real
        # decision (shadow metrics, spec §7/§8); only actually skips generation
        # (`gate_evaluation.suppress_generation`) when telegram_editorial_gate_enabled is True AND
        # the decision is DROP/HOLD. Wrapped in its own try/except - a bug here can never block a
        # real Story from reaching the editor (fails open to "let generation proceed unsuppressed"
        # exactly like Channel Director/Editorial Gate shadow's own established precedent).
        gate_evaluation = None
        try:
            async with session_factory() as gate_session:
                gate_evaluation = await run_pre_generation_gate(
                    gate_session, event_id, now=datetime.now(timezone.utc),
                    # `gate_gateway`/`gate_prompt_repository` are typed `object | None` on this
                    # function so worker/content_cycle.py imports nothing from
                    # integrations.llm_gateway.* (test_i_content_cycle_module_imports_no_llm_
                    # gateway_or_capability_execution). run_pre_generation_gate() itself does the
                    # real typed handoff; a None is a no-op (Stage-1-only gate).
                    gateway=gate_gateway,  # type: ignore[arg-type]
                    prompt_repository=gate_prompt_repository,  # type: ignore[arg-type]
                )
                await gate_session.commit()
        except Exception:
            logger.warning("director_editorial_gate failed (fail-open, generation proceeds)", exc_info=True)

        if gate_evaluation is not None:
            result.gate_total_stories += 1
            result.gate_cheap_prefilter_passed += 1
            if gate_evaluation.escalation_worthy:
                result.gate_director_reviewed += 1
            if gate_evaluation.stage2_status == GATE_STAGE2_USED:
                result.gate_stage2_llm_used += 1
            elif gate_evaluation.stage2_status == GATE_STAGE2_FAILED_FELL_BACK:
                result.gate_stage2_fell_back += 1
            elif gate_evaluation.stage2_status == GATE_STAGE2_BUDGET_EXHAUSTED:
                result.gate_stage2_budget_exhausted += 1
            decision = gate_evaluation.outcome.decision
            if decision == EditorialGateDecision.DROP:
                result.gate_drop += 1
            elif decision == EditorialGateDecision.HOLD:
                result.gate_hold += 1
            elif decision == EditorialGateDecision.SEND_TO_EDITOR:
                result.gate_send_to_editor += 1
            elif decision == EditorialGateDecision.PRIORITY:
                result.gate_priority += 1
            elif decision == EditorialGateDecision.BREAKING:
                result.gate_breaking += 1
            result.gate_would_have_reached_editor_before += 1  # this point in the loop was always reached pre-gate
            if reaches_editor_queue(decision):
                result.gate_would_reach_editor_with_gate += 1
            if gate_evaluation.suppress_generation:
                result.gate_generation_suppressed += 1
                logger.info(
                    "director_editorial_gate_suppressed_generation",
                    extra={"event_id": str(event_id), "decision": decision.value},
                )
                continue

        # Phase V2.6 §5: `precomputed_outcomes` lets a caller supply an already-produced
        # ContentGenerationOutcome for this event_id (from a real, already-run
        # run_content_generation_for_event() call), skipping a second call here entirely - never a
        # duplicated content-generation call, and correctly avoids workflow_service.create_task()'s
        # own DuplicateActiveTaskError (a COMPLETED task still counts as "existing" for the same
        # event+workflow). Exists so a canary can pause between content generation (which persists
        # the real image candidates) and delivery/recomposition for a manual visual safety review of
        # the real selected source image, without ever running content generation twice for the same
        # event. `None` (every real production caller) - byte-identical unchanged behavior.
        if precomputed_outcomes is not None and event_id in precomputed_outcomes:
            outcome = precomputed_outcomes[event_id]
        else:
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

        # MEME PRODUCTION PIPELINE (overnight phase): the AUTOMATIC meme-generation trigger.
        # Byte-identical no-op unless settings.meme_opportunity_mode == "enforce" (default "off",
        # untouched by this phase) - this closest-established-pattern call site (content_worker's
        # own per-event cycle, per that phase's own explicit "find the closest established
        # production pattern, do not invent a scheduler" instruction) is otherwise completely
        # unreachable. Wrapped in its own try/except and never allowed to affect NEWS delivery -
        # a meme-pipeline failure here must never break or delay the real NEWS post for this
        # event (mirrors this file's own established "an optional/best-effort step never blocks
        # the primary deliverable" discipline, e.g. brand_renderer.render_branded_media()'s own
        # fail-open contract).
        if settings.meme_opportunity_mode == "enforce" and meme_auto_triggered_count < settings.meme_auto_max_candidates_per_cycle:
            try:
                from integrations.storage.image_storage import LocalImageStorage
                from services.meme_generation_orchestrator import trigger_meme_generation

                # Mirrors services/image_persistence.py::_get_storage()'s own private, module-
                # scoped singleton pattern - duplicated rather than imported (that function is
                # private there too, matching this codebase's own established per-module-private-
                # helper convention, e.g. _extract_article_result() duplicated across three
                # separate modules this same overnight phase). `image_gateway` is deliberately
                # OMITTED here (defaults to None inside trigger_meme_generation() itself, which
                # lazily constructs MockImageAdapter) - this file must never import anything from
                # integrations.llm_gateway.* directly (test_i_content_cycle_module_imports_no_
                # llm_gateway_or_capability_execution's own established structural boundary).
                global _meme_auto_storage_singleton
                if _meme_auto_storage_singleton is None:
                    _meme_auto_storage_singleton = LocalImageStorage(settings.image_storage_root)

                async with session_factory() as meme_session:
                    meme_outcome = await trigger_meme_generation(
                        meme_session, news_event_id=event.id, trigger_source="automatic",
                        capability_registry=capability_registry,
                        storage=_meme_auto_storage_singleton,
                        bot=bot, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
                    )
                if meme_outcome.status not in ("not_meme_worthy", "already_in_progress"):
                    meme_auto_triggered_count += 1
                logger.info(
                    "meme_auto_cycle_outcome",
                    extra={"event_id": str(event.id), "status": meme_outcome.status, "cycle_count": meme_auto_triggered_count},
                )
            except Exception:  # noqa: BLE001 - fail-safe boundary, must never break NEWS delivery
                logger.exception("meme_auto_cycle_failed", extra={"event_id": str(event.id)})

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
        # target - before any Telegram call. "off" (default): no story_link
        # query at all, reply_to_message_id stays None - byte-identical to pre-18.10 behavior,
        # regardless of story_memory_mode. "shadow": the decision is computed and persisted
        # (services.story_telegram_delivery.persist_reply_routing_proposal) for review, but the
        # real send always proceeds as a standalone post - reply_to_message_id stays None and a
        # fail-closed case is never skipped (only counted, via story_reply_would_fail_closed_
        # shadow). "enforce": applies the decision to the real send, preserving the original
        # fail-closed skip-and-route-to-review guarantee.
        #
        # PHASE STORY-MEMORY-V2-2 Phase 1 (2026-09-02, PHASE STORY-MEMORY-V2-1 design §G Fix 1):
        # the story_link LOOKUP itself is now UNCONDITIONAL - previously nested inside the
        # telegram_story_reply_mode != "off" branch below, which meant durable delivery recording
        # (record_delivery(), further below - keyed on `story_link is not None`) was starved
        # whenever telegram_story_reply_mode == "off" (the confirmed real production value).
        # Reply-threading (presentation) and delivery recording (enforcement/observability state)
        # are independent concerns and must not share one gate. Everything below this lookup -
        # the reply-routing DECISION itself (determine_reply_target/fail-closed skip/
        # reply_to_message_id/persist_reply_routing_proposal) - remains exactly as gated on
        # telegram_story_reply_mode as before; only the lookup both branches need moved out from
        # under that gate. With telegram_story_reply_mode == "off" (unchanged this phase),
        # reply_to_message_id still always stays None and no fail-closed skip ever fires - byte-
        # identical Telegram send content/behavior to before this change. The one observable
        # effect is one additional read query per draft (see the two new session_factory() calls
        # below), always, regardless of mode - the explicit, intended purpose of this fix, and not
        # itself an editorial-output change.
        async with session_factory() as story_session:
            story_link: ContentDraftStoryLink | None = await story_session.get(
                ContentDraftStoryLink, outcome.content_draft.id
            )
        reply_to_message_id: int | None = None
        if settings.telegram_story_reply_mode != "off" and story_link is not None:
            async with session_factory() as story_session:
                root_delivery = await get_root_delivery(story_session, story_link.story_id)
                root_message_id = root_delivery.telegram_message_id if root_delivery is not None else None
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
            # TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: a safe default, always defined - the
            # HOLD gate further below (shared by every path: router-mode AND the legacy
            # `copywriting_output is None` fallback) needs a presentation-type label for its
            # diagnostic log even on paths where `presentation_decision` itself is never computed
            # (copywriting_output is None, not V8-family output, presentation_director_mode ==
            # "off", or the rich-media block's own preconditions aren't met). Overwritten below,
            # only where `presentation_decision` is actually assigned, with the real value
            # captured before any later DATA/QUOTE/BREAKING-render-failure demotion to NEWS.
            original_presentation_type_for_hold: str = "NEWS"
            # Phase 23.1H: resolved below, only inside the `copywriting_output is not None` branch
            # (the disclosed V4/no-structured-output fallback below keeps attaching no image at
            # all - same scope discipline as its own pre-existing "no keyboard either" behavior).
            photo_input: str | BufferedInputFile | None = None
            # Phase V2.5 §7 - tracks which already-selected EditorialImageCandidate row
            # `photo_input` resolved from, independent of whether that resolution produced a
            # cached Telegram file_id (str) or local bytes (BufferedInputFile). Telegram delivery
            # representation and recomposition source bytes are separate concerns: a cached
            # file_id is a valid, optimized way to SEND a photo, but it must never be the only
            # thing recomposition can see - see the recomposition_source_bytes resolution below.
            resolved_photo_candidate: EditorialImageCandidate | None = None
            media_group_items: list[MediaUnion] = []
            # Phase V2.25 Part B: parallel to media_group_items[:len(media_group_photo_candidates)]
            # - the EditorialImageCandidate each of those leading photo items came from, so every
            # image in a real NEWS media group (not just index 0) can independently be re-resolved
            # to its own real bytes and receive its own apply_master_news_branding() call below.
            # Stays empty whenever no >=2-item media group was actually built (single-photo path).
            media_group_photo_candidates: list[EditorialImageCandidate] = []
            # Phase V2.27 §6: set only for a real zero-image, one-video NEWS result (build_rich_
            # media_plan()'s own media_group_items is a single InputMediaVideo with no photo_
            # candidates behind it) - kept completely separate from photo_input/source_bytes so
            # this can never be fed into apply_master_news_branding() (image branding must never
            # touch a video - Phase V2.27 §5's own explicit requirement).
            video_only_input: str | BufferedInputFile | None = None
            image_candidate_count = 0
            # NINJA PULSE Visual System v1 - reassigned only inside the presentation_director_mode
            # != "off" branch below; stays False (today's exact existing behavior) otherwise.
            show_caption_above_media = False
            # Phase 23.1K: pre-rendered directly for V8-family output (§2, docs/
            # phase23_1k_v82_live_canary_report.md) - bypasses card/render_editorial_card()
            # entirely, since V8/V8.1/V8.2's own simplified card shape (headline + one paragraph +
            # optional ending, no "📰 category · date" header row) is a genuinely different
            # template, not a body substitution into the existing one. Stays `None` for V4/V6/V7
            # output, which keep using the exact same `render_editorial_card()` path as always.
            #
            # Phase V2.7 forensic finding: that "as always" fallback is `bot/formatting.py::
            # render_editorial_card()` - the internal `/news` editorial-INBOX-REVIEW template
            # (services/editorial_inbox_service.py's own original consumer), which unconditionally
            # prepends a "\U0001F4F0 category · date" header and the raw, UNTRANSLATED source-
            # language `event.title` before the body. That is a real, reader-facing regression the
            # moment router-mode delivery is actually used with non-V8 copywriting output (as it
            # always is today - production `copywriting_prompt_version` is pinned to "4"). Fixed
            # below: every real copywriting_output shape now gets the same clean, header-free card
            # `render_v81_news_card_html()` already established for V8 - `render_compact_news_card_
            # html()` reuses `outcome.content_draft.title`/the same `compact_body` already computed
            # here, never inventing new copy. `card`/`render_editorial_card()` remain the correct,
            # unchanged fallback for the one case they were always meant for: copywriting_output
            # genuinely absent (the `else: include_url = True` branch below).
            html: str | None = None
            if (
                settings.unified_editorial_pipeline_enabled
                and is_unified_router_eligible(outcome.copywriting_output)
            ):
                # UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1: the orchestrator becomes the
                # AUTHORITATIVE owner of format/structured-content/media/composition/quality-gate/
                # recovery for this event - the legacy decision tree in the `else:` branch below is
                # never also executed for the same event (S2: LEGACY or UNIFIED, never both). The
                # worker's only remaining job here is reading back the result and updating its own
                # cycle bookkeeping - it never re-inspects low-level content/media fields.
                assert treatment_decision is not None  # guaranteed: router mode reaches here only past the SKIP gate
                assert outcome.copywriting_output is not None  # guaranteed by is_unified_router_eligible() above
                async with session_factory() as unified_signals_session:
                    unified_research_facts, unified_presentation_score = await _fetch_router_presentation_signals(
                        unified_signals_session, event.id,
                    )
                unified_outcome = await run_unified_telegram_delivery(
                    session_factory=session_factory, bot=bot, event=event,
                    content_draft_id=outcome.content_draft.id, task_id=outcome.task_id,
                    copywriting_output=outcome.copywriting_output, treatment=treatment_decision.treatment,
                    research_facts=unified_research_facts, presentation_score=unified_presentation_score,
                    quote_text=quote_text, quote_speaker=quote_speaker,
                    keyboard=keyboard, reply_to_message_id=reply_to_message_id,
                    effective_dry_run=effective_dry_run,
                    breaking_count_this_cycle=result.presentation_breaking_sent,
                    breaking_max_per_cycle=settings.presentation_breaking_max_per_cycle,
                    breaking_enabled=settings.presentation_breaking_enabled,
                    story_id=story_link.story_id if story_link is not None else None,
                    # VISION-GATE-CLOSURE-1: the real capability registry this cycle already holds
                    # - passing it through is what makes ACTUAL_IMAGE_VERIFICATION_WIRED genuinely
                    # true (the vision escalation is used only when the registry actually resolves
                    # the capability AND the deterministic classifier's own policy decides
                    # escalation is warranted - see services.editorial_pipeline.telegram_integration
                    # and services.editorial_pipeline.subject_match_vision_gate). Safe regardless of
                    # `unified_editorial_pipeline_enabled`: this whole branch is unreachable unless
                    # that flag is already True (UNIFIED_FLAG_DEFAULT stays False).
                    capability_registry=capability_registry,
                )
                if unified_outcome.presentation_type == PRESENTATION_BREAKING:
                    result.presentation_breaking_sent += 1
                if unified_outcome.held:
                    result.visual_required_held += 1
                elif unified_outcome.dry_run:
                    result.dry_run_rendered += 1
                elif unified_outcome.sent:
                    result.notified += 1
                    sent_message_id = unified_outcome.sent_message_id
                    sent_chat_id = unified_outcome.sent_chat_id
                    if unified_outcome.had_photo:
                        result.router_image_sent += 1
                else:
                    result.notification_failed += 1
            else:
                if outcome.copywriting_output is not None:
                    assert treatment_decision is not None  # guaranteed: router mode reaches here only past the SKIP gate
                    is_v8 = is_v8_family_output(outcome.copywriting_output)
                    if is_v8:
                        # Phase V2.12I: V2.12G's removal of the NINJA PULSE caption footer from real
                        # router-mode NEWS delivery is itself superseded - the current approved NEWS
                        # contract restores Phase 23.1Q's original decision: the footer (text + link)
                        # remains in the final caption/HTML, alongside the unchanged source-only
                        # "🔗 Источник" keyboard (no separate subscription button).
                        html = render_v81_news_card_html(
                            outcome.copywriting_output, treatment=treatment_decision.treatment,
                            quote_text=quote_text, quote_speaker=quote_speaker,
                            include_ninja_pulse_footer=True,
                        )
                    else:
                        compact_body = build_compact_news_body(outcome.copywriting_output, treatment=treatment_decision.treatment)
                        card = card.model_copy(update={"draft_body": compact_body})
                        html = render_compact_news_card_html(
                            outcome.content_draft.title or "", compact_body, quote_text=quote_text, quote_speaker=quote_speaker,
                        )
                    # PRESENTATION RECOVERY (2026-09-02): canonical NEWS-family editorial-send
                    # keyboard (source + meme, never a subscribe/CTA button) - covers text-only,
                    # single-photo, AND media-group sends alike, since every downstream send call
                    # reuses this SAME `keyboard` variable, and (since nothing downstream overwrites
                    # it - see the deleted enforce-branch overwrite this phase removed) also covers
                    # every non-NEWS presentation_type (BREAKING/DATA/QUOTE) reached further below.
                    # The `include_url = True` fallback branch below (copywriting_output is None) has
                    # no keyboard mechanism at all for ANY button - deferred, documented, not touched.
                    keyboard = build_editorial_send_keyboard(event.url, event.id, label=_NEWS_SOURCE_BUTTON_LABEL)
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

                    # Phase V2.27 §6: the real accidental structural gap this phase closes - this
                    # block used to require `eligible_candidates` (>=1 image) as a hard precondition,
                    # so a NewsEvent with a valid video hint but zero usable images could never reach
                    # build_rich_media_plan() at all. Now also entered whenever rich_media_mode is
                    # "enforce" (a video MIGHT exist), even with zero images - `top_candidates` and
                    # `video_hint` below both correctly degrade to "nothing" if neither is real, which
                    # falls through to the exact same pre-existing text-only fallback as before.
                    if is_v8 and html is not None and (eligible_candidates or settings.rich_media_mode == "enforce"):
                        # Phase 23.1Q (Media Roadmap Recovery step 1): rank -> cap at
                        # _MAX_ROUTER_IMAGES -> build_rich_media_plan() (Phase 19 M11/M12, reused
                        # verbatim, never reimplemented). build_rich_media_plan() itself already
                        # skips any candidate whose resolve_photo_input() fails and continues to the
                        # next ranked one - a single broken image never kills the whole media
                        # opportunity. <2 resolved photos degrades to the existing single-photo
                        # variable below; 0 resolved photos leaves both empty (existing text-only
                        # fallback, unchanged).
                        top_candidates = (
                            _select_top_ranked_image_candidates(eligible_candidates, limit=_MAX_ROUTER_IMAGES)
                            if eligible_candidates else []
                        )
                        # Phase 19 M10/M12 production wiring (docs/video_delivery_wiring_checkpoint.md):
                        # video attachment is opt-in via rich_media_mode - "off"/"shadow" (the current
                        # defaults) skip the lookup entirely and stay byte-identical to the pre-wiring
                        # image-only behavior below. "No candidate" and "candidate fails to convert"
                        # both leave video_hint as None, which build_rich_media_plan() (unmodified)
                        # already treats as "no video" - never a crash, never a blocked image send.
                        video_hint = None
                        hosted_video_bytes: bytes | None = None
                        if settings.rich_media_mode == "enforce":
                            async with session_factory() as video_session:
                                # Phase V2.27A: no longer limit=1 - multiple platform tiers may be
                                # persisted for the same event (DIRECT_HOSTED, YOUTUBE/VIMEO,
                                # EMBEDDED_PLAYER), and select_best_video_candidate() below needs to
                                # see all of them to apply the real DIRECT_HOSTED > YOUTUBE/VIMEO >
                                # EMBEDDED_PLAYER resolution order rather than just whichever one was
                                # persisted first.
                                video_candidates = await get_video_candidates_for_event(video_session, event.id)
                            best_video_candidate = select_best_video_candidate(video_candidates)
                            if best_video_candidate is not None:
                                video_hint = to_native_video_hint(best_video_candidate)
                            # Phase V2.27/V2.27A: a YOUTUBE/VIMEO/EMBEDDED_PLAYER hint previously
                            # always became a plain caption link (YOUTUBE/VIMEO) or was discarded
                            # entirely (EMBEDDED_PLAYER did not exist before V2.27A) - see
                            # build_rich_media_plan()'s own hosted_platform_link docstring.
                            # hosted_video_download_mode="enforce" attempts a real, bounded
                            # server-side download instead - on ANY failure the hint is dropped
                            # entirely (video_hint = None) rather than falling back to the
                            # caption-link behavior (Phase V2.27 §4's own explicit instruction: no
                            # raw-link fallback once native delivery is opted into).
                            if (
                                video_hint is not None
                                and video_hint.platform in (
                                    VideoPlatform.YOUTUBE, VideoPlatform.VIMEO, VideoPlatform.EMBEDDED_PLAYER,
                                )
                                and settings.hosted_video_download_mode == "enforce"
                            ):
                                download_result = await download_hosted_video(
                                    video_hint.remote_url, video_hint.platform,
                                    event_id=event.id, draft_id=outcome.content_draft.id,
                                )
                                logger.info(
                                    "hosted_video_download_result",
                                    extra={
                                        "draft_id": str(outcome.content_draft.id),
                                        "outcome": download_result.outcome,
                                        "platform": video_hint.platform.value,
                                        "reason": download_result.reason,
                                        "duration_seconds": download_result.duration_seconds,
                                        "byte_size": download_result.byte_size,
                                        "source_format": download_result.source_format,
                                        "final_format": download_result.final_format,
                                        "remuxed": download_result.remuxed,
                                        "transcoded": download_result.transcoded,
                                    },
                                )
                                if download_result.video_bytes is not None:
                                    hosted_video_bytes = download_result.video_bytes
                                else:
                                    video_hint = None

                            # MEDIA-PROD-1: deterministic advertisement-keyword text gate - see
                            # services/video_quality_gate.py's own module docstring for the full scope
                            # decision (text-only; visual/frame-based detection is a disclosed future
                            # extension, not silently skipped). Applied AFTER selection so a rejected
                            # video degrades exactly like "no video hint resolved" for any other reason
                            # - no new fallback path.
                            if video_hint is not None and settings.video_quality_gate_mode != "off":
                                video_quality_assessment = assess_video_text_signals(
                                    title=event.title, content=event.content,
                                )
                                logger.info(
                                    "video_quality_gate_assessed",
                                    extra={
                                        "draft_id": str(outcome.content_draft.id),
                                        "classification": video_quality_assessment.classification.value,
                                        "matched_keywords": list(video_quality_assessment.matched_keywords),
                                        "mode": settings.video_quality_gate_mode,
                                    },
                                )
                                if (
                                    video_quality_assessment.classification == VideoContentClassification.ADVERTISEMENT
                                    and settings.video_quality_gate_mode == "enforce"
                                ):
                                    video_hint = None
                        plan = build_rich_media_plan(
                            top_candidates, video_hint, caption=html, hosted_video_bytes=hosted_video_bytes,
                        )
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
                            # Phase V2.25 Part B: carried forward so every photo in this real media
                            # group (not only index 0) can later be independently re-resolved to its
                            # own bytes and receive its own apply_master_news_branding() call.
                            media_group_photo_candidates = plan.photo_candidates
                            # R2.10-FINALIZATION-1: this branch never assigned `photo_input` at all -
                            # unlike the single-item branch just below it (`photo_input = single_media
                            # if isinstance(...)`), leaving `photo_input`/`source_bytes` at their
                            # top-of-loop `None` default for every real >=2-item media group. Since
                            # `source_bytes = photo_input.data if isinstance(photo_input, BufferedInputFile)
                            # else None` (below) then always produced `None`, the PRIMARY image
                            # (media_group_items[0], "media_group_index=-1") silently skipped
                            # apply_master_news_branding() entirely (needs_render=False ->
                            # brand_render_skipped) - and because the group's own items[1:] branding
                            # loop further below is itself gated on `was_news_with_source_bytes` (only
                            # ever True when THIS primary branding ran), every OTHER photo in the group
                            # was skipped too, cascading from this one missing assignment. Mirrors the
                            # single-item branch's own exact pattern: the first group item's own real
                            # media/candidate becomes the primary `photo_input`/`resolved_photo_candidate`
                            # this function already threads through unchanged from here on - no new
                            # resolution path, no re-fetch, no behavior change to any other branch.
                            primary_group_media = media_group_items[0].media
                            photo_input = (
                                primary_group_media if isinstance(primary_group_media, (str, BufferedInputFile)) else None
                            )
                            if photo_input is not None and media_group_photo_candidates:
                                resolved_photo_candidate = media_group_photo_candidates[0]
                        elif len(plan.media_group_items) == 1 and not plan.photo_candidates:
                            # Phase V2.27 §6: exactly one media item and it did NOT come from any
                            # image candidate - it can only be the video. Routed as a real single-
                            # video send (send_video_to_editorial_destination(), never send_photo) -
                            # never assigned to photo_input, so it can never reach apply_master_news_
                            # branding() (Phase V2.27 §5's own explicit "video must never pass through
                            # image branding" requirement).
                            video_only_media = plan.media_group_items[0].media
                            video_only_input = video_only_media if isinstance(video_only_media, (str, BufferedInputFile)) else None
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
                            if photo_input is not None:
                                resolved_photo_candidate = plan.fallback_single_photo
                    elif eligible_candidates:
                        # Legacy (V4/V6/V7) router-mode output - byte-identical to this branch's own
                        # pre-Phase-23.1Q behavior (never used by any real canary; V8-family output is
                        # the only shape any live send has ever produced), untouched by this phase.
                        photo_input = resolve_photo_input(eligible_candidates[0])
                        if photo_input is not None:
                            resolved_photo_candidate = eligible_candidates[0]

                    # NINJA PULSE Visual System v1 (services/presentation_director.py,
                    # services/brand_renderer.py). Gated entirely on presentation_director_mode -
                    # "off" (the default) skips this block completely, leaving every line above/below
                    # byte-identical to pre-Visual-System behavior. "shadow" computes and logs the
                    # decision only, never changes what is sent. Only "enforce" changes the keyboard/
                    # image/caption actually delivered - and even then, every rendering step fails
                    # safe to the original keyboard/media/text (spec §29).
                    if settings.presentation_director_mode != "off":
                        async with session_factory() as presentation_session:
                            research_facts, presentation_score = await _fetch_router_presentation_signals(
                                presentation_session, event.id,
                            )
                        presentation_decision = decide_presentation(
                            title=event.title, content=event.content,
                            copywriting_output=outcome.copywriting_output,
                            treatment=treatment_decision.treatment,
                            scoring_score=presentation_score,
                            research_facts=research_facts,
                            quote_text=quote_text, quote_speaker=quote_speaker,
                            fallback_category=event.category,
                            breaking_count_this_cycle=result.presentation_breaking_sent,
                            breaking_max_per_cycle=settings.presentation_breaking_max_per_cycle,
                            breaking_enabled=settings.presentation_breaking_enabled,
                        )
                        # TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1: captured before the
                        # pre-existing "Fail-safe (spec S29)" DATA/QUOTE/BREAKING-render-failure
                        # branch (below) may demote presentation_decision.presentation_type to
                        # "NEWS" - used only as a diagnostic label on the HOLD path so an audit can
                        # still see which presentation format actually failed to render, without
                        # changing the demotion itself (that fail-safe's own send-path behavior is
                        # unmodified by this phase).
                        original_presentation_type_for_hold = presentation_decision.presentation_type
                        logger.info(
                            "presentation_decision",
                            extra={
                                "draft_id": str(outcome.content_draft.id),
                                "presentation_type": presentation_decision.presentation_type,
                                "presentation_category": presentation_decision.category,
                                "presentation_ai_used": outcome.copywriting_output.get("viral_potential") is not None,
                                "branding_strength": presentation_decision.branding_strength,
                                "caption_position": presentation_decision.caption_position,
                                "reason": presentation_decision.reason,
                            },
                        )

                        # NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §9-11:
                        # Channel Director shadow evaluation. Flag-gated (default False,
                        # run_channel_director_shadow() itself no-ops when disabled) and wrapped in its
                        # own try/except - a bug here can never affect the real presentation/publish
                        # decision above, which is already fully computed by this point. Reuses
                        # `presentation_score` already fetched for presentation_decision rather than
                        # issuing a second query; skips entirely when no real score exists rather than
                        # fabricating a news_importance value from nothing.
                        if presentation_score is not None:
                            try:
                                async with session_factory() as channel_director_session:
                                    await run_channel_director_shadow(
                                        channel_director_session,
                                        news_importance=presentation_score / 100.0,
                                        now=datetime.now(timezone.utc),
                                    )
                            except Exception:
                                logger.warning("telegram_channel_director_shadow failed (shadow only, non-fatal)", exc_info=True)

                        if settings.presentation_director_mode == "enforce":
                            # PRESENTATION RECOVERY (2026-09-02): the prior Phase V2.10N behavior here
                            # unconditionally overwrote `keyboard` with the legacy subscribe/CTA
                            # button for every non-NEWS presentation_type, discarding the meme button
                            # in the same step - the confirmed root cause of both the unwanted-
                            # subscribe-button and missing-meme-button production symptoms. Removed
                            # outright (not merely re-gated) so the subscribe button is structurally
                            # unreachable regardless of this flag's value. `keyboard` was already set
                            # to the canonical source+meme build above and needs no per-type branch -
                            # NEWS/BREAKING/DATA/QUOTE now all keep that same keyboard unchanged.

                            if settings.pulse_brand_enabled:
                                editorial_code = build_editorial_code(outcome.task_id)
                                source_bytes = photo_input.data if isinstance(photo_input, BufferedInputFile) else None

                                # Phase V2.3 (services/editorial_recomposition.py) - NEWS presentation
                                # only, per that phase's own explicit scope (never DATA/QUOTE/
                                # BREAKING). A thin consumer of the existing ImageGenerationGateway;
                                # never touches media selection/ranking/Story Memory - it only ever
                                # transforms the already-selected source_bytes in place.
                                # editorial_recomposition_mode defaults to "off", in which case
                                # maybe_recompose() returns source_bytes completely unchanged with
                                # zero gateway calls - byte-identical to pre-V2.3 behavior.
                                #
                                # Phase V2.5 §7: `source_bytes` above is None whenever photo_input
                                # resolved to a cached Telegram file_id (str) rather than local bytes -
                                # a real, previously-silent gap, since resolve_photo_input() prefers
                                # the cached file_id whenever one exists. Telegram delivery
                                # representation and recomposition source bytes are separate concerns
                                # (the cached file_id remains exactly as useful for sending as before -
                                # untouched below); recomposition gets its own independently-resolved
                                # bytes for the exact same already-selected candidate, via the existing
                                # storage abstraction (read_candidate_bytes()), never a new one.
                                # Phase V2.7 §8: ORIGINAL_SOURCE is a first-class successful outcome,
                                # never merely an error fallback - a candidate whose own already-
                                # computed warnings flag logo/banner/watermark/lower-third/branded-
                                # screenshot risk skips the Gemini call entirely (same reused signal
                                # services/media_ranking.py already derives from this exact field).
                                recomposition_source_risk = assess_recomposition_source_risk(resolved_photo_candidate)
                                if recomposition_source_risk is not None:
                                    logger.info(
                                        "recomposition_skipped_source_risk",
                                        extra={
                                            "draft_id": str(outcome.content_draft.id),
                                            "recomposition_source_risk_reason": recomposition_source_risk,
                                        },
                                    )

                                recomposition_result: RecompositionResult | None = None
                                recomposition_source_bytes = resolve_recomposition_source_bytes(
                                    photo_input, resolved_photo_candidate,
                                )
                                if (
                                    presentation_decision.presentation_type == PRESENTATION_NEWS
                                    and recomposition_source_bytes is not None
                                    and recomposition_source_risk is None
                                ):
                                    recomposition_result = await maybe_recompose(source_image_bytes=recomposition_source_bytes)
                                    logger.info(
                                        "editorial_recomposition_evaluated",
                                        extra={
                                            "draft_id": str(outcome.content_draft.id),
                                            "recomposition_mode": recomposition_result.mode,
                                            "recomposition_eligible": recomposition_result.eligibility.eligible,
                                            "recomposition_eligibility_reason": recomposition_result.eligibility.reason,
                                            "recomposition_used": recomposition_result.used_recomposed_image,
                                            "recomposition_provider": recomposition_result.provider,
                                            "recomposition_model": recomposition_result.model,
                                            "recomposition_source_sha256": recomposition_result.source_sha256,
                                            "recomposition_result_sha256": recomposition_result.result_sha256,
                                            "recomposition_fallback_reason": recomposition_result.fallback_reason,
                                            "recomposition_latency_ms": (
                                                round(recomposition_result.latency_ms, 1)
                                                if recomposition_result.latency_ms is not None else None
                                            ),
                                            "recomposition_request_id": recomposition_result.request_id,
                                            "recomposition_input_tokens": recomposition_result.input_tokens,
                                            "recomposition_output_tokens": recomposition_result.output_tokens,
                                            "recomposition_units": recomposition_result.units,
                                            "recomposition_unit_type": recomposition_result.unit_type,
                                            "recomposition_bytes_source": (
                                                "local_buffered_input" if source_bytes is not None
                                                else "read_candidate_bytes_independent_of_cached_file_id"
                                            ),
                                        },
                                    )
                                    # Only overwrite source_bytes when a real recomposition actually
                                    # happened - the pre-existing "no local bytes -> skip branding"
                                    # behavior for a cached-file_id NEWS candidate that recomposition
                                    # did NOT touch (mode off/ineligible/failed) stays byte-identical
                                    # to before this phase; recomposition_source_bytes is a separate,
                                    # local variable never written back into source_bytes on its own.
                                    if recomposition_result.used_recomposed_image:
                                        source_bytes = recomposition_result.image_bytes

                                # Phase V2.16: MASTER NEWS branding must still receive the already-
                                # selected candidate's real original bytes when photo_input resolved to
                                # a cached Telegram file_id and Gemini did not produce a new image
                                # (skipped/ineligible/failed/off, or the source-risk gate above skipped
                                # recomposition entirely) - recomposition_source_bytes already resolved
                                # them above via the exact same storage read, no new fetch/call here.
                                # ORIGINAL_SOURCE remains a first-class result (Phase V2.7 §8/V2.10H) -
                                # it must not be silently demoted to NO_OVERLAY merely because the
                                # cached-file_id path has no BufferedInputFile bytes of its own.
                                if (
                                    presentation_decision.presentation_type == PRESENTATION_NEWS
                                    and source_bytes is None
                                    and recomposition_source_bytes is not None
                                ):
                                    source_bytes = recomposition_source_bytes

                                needs_render = presentation_decision.presentation_type in (
                                    PRESENTATION_DATA, PRESENTATION_QUOTE, PRESENTATION_BREAKING,
                                ) or source_bytes is not None
                                if not needs_render:
                                    # Pre-commit correction ("cached file_id branding - measure, do
                                    # not redesign"): a NEWS presentation with no local image bytes
                                    # (photo_input is a cached Telegram file_id string, or no photo
                                    # was resolved at all) has nothing for the Pillow renderer to
                                    # composite onto - branding is skipped, never blocking the send.
                                    # Previously this path was silent; this is the one observability
                                    # gap the pre-commit review found and closed - no behavior change.
                                    skip_reason = (
                                        "cached_file_id_no_local_bytes" if isinstance(photo_input, str)
                                        else "no_source_media"
                                    )
                                    logger.info(
                                        "brand_render_skipped",
                                        extra={
                                            "draft_id": str(outcome.content_draft.id),
                                            "presentation_type": presentation_decision.presentation_type,
                                            "brand_applied": False,
                                            "brand_skip_reason": skip_reason,
                                            "news_branding_status": (
                                                NEWS_BRANDING_NO_SOURCE_BYTES
                                                if presentation_decision.presentation_type == PRESENTATION_NEWS
                                                else None
                                            ),
                                        },
                                    )
                                if needs_render:
                                    # Phase V2.10H: the locked MASTER NEWS visual contract
                                    # (services.nnj_master_news_overlay) is now the production
                                    # branding path for every NEWS image with real source bytes -
                                    # whether Gemini successfully recomposed it or not. Supersedes
                                    # Phase V2.9's Candidate C path (services.nnj_adaptive_overlay,
                                    # apply_adaptive_nnj_branding) - that module and its locked asset
                                    # remain in the repository as historical/fallback evidence, never
                                    # called from this branch anymore. ORIGINAL_SOURCE is a
                                    # first-class result (Phase V2.7 §8/V2.8 §6/V2.9 §4/V2.10H's own
                                    # explicit product decision) - it must never be silently demoted
                                    # merely because recomposition did not run. Every other case
                                    # (DATA/QUOTE/BREAKING) keeps using render_branded_media()
                                    # completely unchanged - never duplicated, never touched here.
                                    # Phase V2.25 Part B: set True below, before any later DATA/QUOTE/
                                    # BREAKING-render-failure demotion can reassign presentation_decision
                                    # to NEWS - the media-group branding loop further below must only
                                    # ever run for a post that was ALREADY NEWS here (media_group_items[0]
                                    # already went through apply_master_news_branding() above), never
                                    # for a demoted post whose primary image never received it at all.
                                    # (Kept as a separate flag, not re-derived from presentation_decision/
                                    # source_bytes at the loop's own site below, specifically so mypy's
                                    # narrowing of `source_bytes: bytes | None` on the `if` condition
                                    # immediately below is preserved unchanged.)
                                    was_news_with_source_bytes = False
                                    if presentation_decision.presentation_type == PRESENTATION_NEWS and source_bytes is not None:
                                        was_news_with_source_bytes = True
                                        started_adaptive_branding = time.monotonic()
                                        # Phase V2.25 Part B: the one explicit status this NEWS send
                                        # will end up recording - assigned in every branch below
                                        # (success or exception), never left unset, so downstream
                                        # logging always has a real value instead of an ad hoc re-
                                        # derivation of render_result.success/template_version.
                                        news_branding_status: str = NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE
                                        try:
                                            # Phase V2.10I §7: `recomposition_source_risk` (assigned
                                            # above, always set whenever this pulse_brand_enabled
                                            # block runs) is a real, already-computed, WHOLE-IMAGE
                                            # signal (EditorialImageCandidate.warnings via
                                            # assess_recomposition_source_risk()) - it cannot say
                                            # WHERE on the image the risk is, only that the image as a
                                            # whole carries a flagged logo/banner/watermark/lower-
                                            # third/branded-screenshot warning. Rather than pretending
                                            # it supplies coordinates, it vetoes only the LOWER
                                            # SIGNATURE (the larger, harder-to-earn component) - the
                                            # UPPER MARK's own independent, spatial, pixel-based
                                            # evaluation is unaffected.
                                            branded_bytes, master_decision = apply_master_news_branding(
                                                source_bytes, disable_lower_signature=recomposition_source_risk is not None,
                                            )
                                            news_branding_status = master_decision.news_branding_status
                                            render_result = RenderResult(
                                                success=True, image_bytes=branded_bytes,
                                                template_version=f"master_news_v1:{master_decision.degradation_mode}",
                                                fallback_reason=None,
                                                duration_ms=(time.monotonic() - started_adaptive_branding) * 1000,
                                            )
                                            # Phase V2.10H telemetry - never logs raw image bytes,
                                            # only the decision's own structured provenance fields.
                                            # Upper mark and lower signature are logged independently
                                            # (they are independent components - Phase V2.10H §3).
                                            logger.info(
                                                "master_news_branding_applied",
                                                extra={
                                                    "draft_id": str(outcome.content_draft.id),
                                                    "visual_path": (
                                                        "RECOMPOSE"
                                                        if recomposition_result is not None and recomposition_result.used_recomposed_image
                                                        else "ORIGINAL_SOURCE"
                                                    ),
                                                    "degradation_mode": master_decision.degradation_mode,
                                                    "news_branding_status": news_branding_status,
                                                    "upper_mark_placement": master_decision.upper_mark.placement.value,
                                                    "upper_mark_rejected_candidate_count": len(master_decision.upper_mark.attempts),
                                                    "lower_signature_placement": master_decision.lower_signature.placement.value,
                                                    "lower_signature_rejected_candidate_count": len(master_decision.lower_signature.attempts),
                                                    "lower_signature_disabled_reason": master_decision.lower_signature.disabled_reason,
                                                },
                                            )
                                        except Exception as exc:  # noqa: BLE001 - same fail-safe boundary
                                            # render_branded_media() itself establishes (spec §29):
                                            # never let a rendering failure block the send.
                                            news_branding_status = NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE
                                            render_result = RenderResult(
                                                success=False, image_bytes=None, template_version="master_news_v1",
                                                fallback_reason=str(exc),
                                                duration_ms=(time.monotonic() - started_adaptive_branding) * 1000,
                                            )
                                    else:
                                        # DIRECTOR-CONTROL-PLANE-1 §23-26: classify the source before
                                        # DATA renders - the real Kirin 9050 Pro regression fix. Never
                                        # affects BREAKING/QUOTE/NEWS (data_presentation_mode is only
                                        # ever read by render_data_card()'s own DATA branch); a source
                                        # already classified EXISTING_INFOGRAPHIC gets the source-
                                        # preserving treatment instead of a second competing stat card.
                                        data_presentation_mode = select_data_presentation_mode(
                                            classify_source_presentation(
                                                resolved_photo_candidate.warnings if resolved_photo_candidate is not None else None
                                            )
                                        )
                                        render_result = render_branded_media(
                                            presentation_type=presentation_decision.presentation_type,
                                            source_image_bytes=source_bytes,
                                            category=presentation_decision.category,
                                            editorial_code=editorial_code,
                                            branding_strength=presentation_decision.branding_strength,
                                            data_candidate=presentation_decision.data_candidate,
                                            quote_candidate=presentation_decision.quote_candidate,
                                            data_presentation_mode=data_presentation_mode,
                                        )
                                    logger.info(
                                        "brand_render_attempted",
                                        extra={
                                            "draft_id": str(outcome.content_draft.id),
                                            "presentation_type": presentation_decision.presentation_type,
                                            "brand_applied": render_result.success,
                                            "brand_skip_reason": None if render_result.success else render_result.fallback_reason,
                                            "brand_render_success": render_result.success,
                                            "brand_render_duration_ms": round(render_result.duration_ms, 1),
                                            "brand_render_fallback": render_result.fallback_reason,
                                            "brand_template_version": render_result.template_version,
                                            "news_branding_status": (
                                                news_branding_status
                                                if presentation_decision.presentation_type == PRESENTATION_NEWS
                                                else None
                                            ),
                                        },
                                    )
                                    if render_result.success and render_result.image_bytes is not None:
                                        branded_file = BufferedInputFile(render_result.image_bytes, filename="pulse.jpg")
                                        photo_input = branded_file
                                        if media_group_items:
                                            media_group_items = [
                                                media_group_items[0].model_copy(update={"media": branded_file}),
                                                *media_group_items[1:],
                                            ]
                                    elif presentation_decision.presentation_type in (
                                        PRESENTATION_DATA, PRESENTATION_QUOTE, PRESENTATION_BREAKING,
                                    ):
                                        # Fail-safe (spec §29): a DATA/QUOTE/BREAKING card that could
                                        # not be rendered has no other valid visual form - demote to
                                        # ordinary NEWS delivery (whatever photo/text was already
                                        # resolved above), never block the send itself.
                                        presentation_decision = presentation_decision.__class__(
                                            presentation_type="NEWS", category=presentation_decision.category,
                                            caption_position="BELOW", branding_strength="MINIMAL",
                                            brand_media=False, visual_priority=1, data_candidate=None,
                                            quote_candidate=None, reason="brand_render_failed_demoted_to_news",
                                        )

                                    # Phase V2.25 Part B (real accidental bypass fix): the block above
                                    # only ever brands media_group_items[0] - a real NEWS media-group
                                    # (album) send with 2+ resolved photos previously shipped every
                                    # OTHER photo in the group completely untouched by
                                    # apply_master_news_branding(), with no exception, no safety
                                    # rejection, and no diagnostic - a silent unbranded delivery this
                                    # phase's own rule ("if branding is safe, the final image MUST be
                                    # branded") forbids. Independently re-resolves and brands every
                                    # remaining photo using the SAME deterministic function and the
                                    # SAME per-image recomposition-source-risk gate the primary image
                                    # already receives above - never re-running Gemini recomposition
                                    # (out of this phase's scope; only the primary image, already
                                    # resolved earlier, may carry a recomposed image).
                                    if (
                                        was_news_with_source_bytes
                                        and len(media_group_photo_candidates) > 1
                                        and media_group_items
                                    ):
                                        rebuilt_group_items = [media_group_items[0]]
                                        for group_idx in range(1, len(media_group_photo_candidates)):
                                            group_item = media_group_items[group_idx]
                                            group_candidate = media_group_photo_candidates[group_idx]
                                            group_media = group_item.media
                                            group_source_bytes = resolve_recomposition_source_bytes(
                                                group_media if isinstance(group_media, (str, BufferedInputFile)) else None,
                                                group_candidate,
                                            )
                                            if group_source_bytes is None:
                                                logger.info(
                                                    "brand_render_skipped",
                                                    extra={
                                                        "draft_id": str(outcome.content_draft.id),
                                                        "presentation_type": presentation_decision.presentation_type,
                                                        "media_group_index": group_idx,
                                                        "brand_applied": False,
                                                        "brand_skip_reason": "no_source_media",
                                                        "news_branding_status": NEWS_BRANDING_NO_SOURCE_BYTES,
                                                    },
                                                )
                                                rebuilt_group_items.append(group_item)
                                                continue
                                            group_risk = assess_recomposition_source_risk(group_candidate)
                                            try:
                                                group_branded_bytes, group_decision = apply_master_news_branding(
                                                    group_source_bytes, disable_lower_signature=group_risk is not None,
                                                )
                                                group_branded_file = BufferedInputFile(group_branded_bytes, filename="pulse.jpg")
                                                rebuilt_group_items.append(group_item.model_copy(update={"media": group_branded_file}))
                                                logger.info(
                                                    "master_news_branding_applied",
                                                    extra={
                                                        "draft_id": str(outcome.content_draft.id),
                                                        "media_group_index": group_idx,
                                                        "visual_path": "ORIGINAL_SOURCE",
                                                        "degradation_mode": group_decision.degradation_mode,
                                                        "news_branding_status": group_decision.news_branding_status,
                                                        "upper_mark_placement": group_decision.upper_mark.placement.value,
                                                        "lower_signature_placement": group_decision.lower_signature.placement.value,
                                                        "lower_signature_disabled_reason": group_decision.lower_signature.disabled_reason,
                                                    },
                                                )
                                            except Exception as exc:  # noqa: BLE001 - same fail-safe boundary as the primary image
                                                rebuilt_group_items.append(group_item)
                                                logger.info(
                                                    "brand_render_attempted",
                                                    extra={
                                                        "draft_id": str(outcome.content_draft.id),
                                                        "presentation_type": presentation_decision.presentation_type,
                                                        "media_group_index": group_idx,
                                                        "brand_applied": False,
                                                        "brand_skip_reason": str(exc),
                                                        "news_branding_status": NEWS_BRANDING_ORIGINAL_SOURCE_FAILURE,
                                                    },
                                                )
                                        media_group_items = [
                                            *rebuilt_group_items,
                                            *media_group_items[len(media_group_photo_candidates):],
                                        ]

                            if presentation_decision.caption_position == CAPTION_ABOVE:
                                show_caption_above_media = True
                                if media_group_items:
                                    media_group_items = [
                                        media_group_items[0].model_copy(update={"show_caption_above_media": True}),
                                        *media_group_items[1:],
                                    ]

                        if presentation_decision.presentation_type == PRESENTATION_BREAKING:
                            result.presentation_breaking_sent += 1
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
                    # Phase V2.27 §6: a lone video (zero images) is dispatched via send_video_to_
                    # editorial_destination() - never send_photo (video_only_input is never a valid
                    # photo argument) and never the plain-text else branch below (that would silently
                    # drop a successfully-downloaded/validated video).
                    send_as_video_only = not send_as_media_group and video_only_input is not None and fits_caption_budget
                    send_as_photo = (
                        not send_as_media_group and not send_as_video_only
                        and photo_input is not None and fits_caption_budget
                    )
                    logger.info(
                        "router_image_decision",
                        extra={
                            "draft_id": str(outcome.content_draft.id), "image_candidate_count": image_candidate_count,
                            "has_resolvable_photo": photo_input is not None, "send_as_photo": send_as_photo,
                            "media_group_item_count": len(media_group_items), "send_as_media_group": send_as_media_group,
                            "send_as_video_only": send_as_video_only,
                        },
                    )
                    if send_as_media_group:
                        routing_outcome = await send_media_group_to_editorial_destination(
                            bot, EditorialDestination.NEWS, media_group_items,
                            dry_run=effective_dry_run, reply_to_message_id=reply_to_message_id,
                            reply_markup=keyboard,
                        )
                    elif send_as_video_only:
                        assert video_only_input is not None  # narrows for mypy; already checked above
                        routing_outcome = await send_video_to_editorial_destination(
                            bot, EditorialDestination.NEWS, video_only_input, html,
                            dry_run=effective_dry_run, reply_markup=keyboard,
                            reply_to_message_id=reply_to_message_id,
                        )
                        logger.info(
                            "HOSTED_VIDEO_TELEGRAM_SENT" if routing_outcome.sent else "HOSTED_VIDEO_TELEGRAM_FAILED",
                            extra={"draft_id": str(outcome.content_draft.id), "reason": routing_outcome.reason},
                        )
                    elif send_as_photo:
                        assert photo_input is not None  # narrows for mypy; already checked above
                        routing_outcome = await send_photo_to_editorial_destination(
                            bot, EditorialDestination.NEWS, photo_input, html,
                            dry_run=effective_dry_run, reply_markup=keyboard,
                            reply_to_message_id=reply_to_message_id,
                            show_caption_above_media=show_caption_above_media,
                        )
                    else:
                        # TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 (Founder product invariant):
                        # this `else` is reached for two structurally different reasons, and only one
                        # of them may still send plain text. (1) A real visual (photo_input/
                        # media_group_items/video_only_input) WAS resolved, but `fits_caption_budget`
                        # was False - the separate, pre-existing, disclosed Phase 23.1H/23.1Q caption-
                        # length tradeoff (a text-budget decision, not a missing visual) - completely
                        # UNCHANGED by this phase. (2) NO visual was resolved at all - previously
                        # silently sent as an indistinguishable-from-normal finished text post; now
                        # held for editor-visible recovery instead (spec §9-D/§12/§13).
                        had_any_visual = (
                            photo_input is not None or bool(media_group_items) or video_only_input is not None
                        )
                        # `not effective_dry_run` guard mirrors every other real side effect in this
                        # function (dry-run must stay exactly as side-effect-free as before this
                        # phase - no content_drafts.status write, no notice send): a dry-run cycle
                        # keeps falling through to the pre-existing send_to_editorial_destination(...,
                        # dry_run=True) call below, which itself already no-ops safely and is counted
                        # via the unchanged `dry_run_rendered` path further down.
                        if not had_any_visual and not effective_dry_run:
                            await _hold_for_visual_recovery(
                                session_factory, bot,
                                draft_id=outcome.content_draft.id, event=event,
                                presentation_type=original_presentation_type_for_hold,
                                reason=HOLD_REASON_NO_VISUAL_RESOLVED, dry_run=effective_dry_run,
                            )
                            result.visual_required_held += 1
                            routing_outcome = None
                        else:
                            routing_outcome = await send_to_editorial_destination(
                                bot, EditorialDestination.NEWS, html, dry_run=effective_dry_run, reply_markup=keyboard,
                                reply_to_message_id=reply_to_message_id,
                            )

                    # Delivery-gap fix (2026-08-16 production forensic): a real photo/media-group
                    # send timing out (or any other live TelegramAPIError) previously dropped a fully
                    # generated, treatment-approved post entirely - only notification_failed
                    # incremented, no post ever reached NEWS. `not effective_dry_run` guards this so
                    # dry-run stays exactly as side-effect-free as before (a dry-run outcome is always
                    # sent=False by construction, but must never trigger a second fake send here).
                    # `send_as_media_group or send_as_photo` scopes the fallback to exactly the two
                    # media-carrying paths named in the brief - the `else` branch above already IS
                    # the plain-text path (including the existing caption-too-long-degrades-to-text
                    # case, upstream of this block), so it never re-enters its own fallback.
                    #
                    # TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 (Founder product invariant):
                    # `routing_outcome` may be `None` here (the `visual_required_held` branch just
                    # above never attempted a send at all) - guarded first, so the pre-existing
                    # fallback below can keep reading `.sent` unchanged for every other case.
                    #
                    # Residual, disclosed limitation (not fixed, not in scope this checkpoint): a
                    # Telegram network timeout can occur after Telegram has already accepted the
                    # photo/media-group but before this process received the response (exactly the
                    # real production case that motivated this fix) - RoutingOutcome.sent=False is
                    # this codebase's only signal and cannot distinguish "never reached Telegram"
                    # from "Telegram accepted it, response was lost." Previously, this ambiguous case
                    # triggered a one-shot plain-text fallback that could produce a real photo+text
                    # duplicate for the same story. Per the Founder invariant above, a resolved-but-
                    # undeliverable visual must now HOLD instead of silently completing as that
                    # plain-text duplicate - still a single, bounded, one-shot outcome, never a retry
                    # loop, never an unbounded generation attempt (MAX_VISUAL_FALLBACK_ATTEMPTS=0
                    # extra renders - this path never re-renders, it only changes whether the
                    # already-rendered result's failed send becomes a HOLD or a silent text send).
                    used_text_fallback = False

                    if (
                        routing_outcome is not None and not effective_dry_run and not routing_outcome.sent
                        and (send_as_media_group or send_as_photo or send_as_video_only)
                    ):
                        await _hold_for_visual_recovery(
                            session_factory, bot,
                            draft_id=outcome.content_draft.id, event=event,
                            presentation_type=original_presentation_type_for_hold,
                            reason=HOLD_REASON_MEDIA_SEND_FAILED, dry_run=effective_dry_run,
                        )
                        result.visual_required_held += 1
                        routing_outcome = None

                    if routing_outcome is None:
                        pass  # already accounted for in result.visual_required_held above
                    elif effective_dry_run:
                        result.dry_run_rendered += 1  # expected outcome in dry-run mode, not a failure
                    elif routing_outcome.sent:
                        result.notified += 1
                        sent_message_id = routing_outcome.message_id
                        sent_chat_id = routing_outcome.chat_id
                        if used_text_fallback:
                            result.router_text_fallback_sent += 1
                        elif send_as_media_group:
                            result.router_media_group_sent += 1
                        elif send_as_video_only:
                            result.router_video_only_sent += 1
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
