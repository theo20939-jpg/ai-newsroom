"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1 (S1-S16): the real, worker-reachable Telegram
integration - the ONE call site `worker/content_cycle.py` invokes when the unified pipeline is
authoritative for an event (`settings.unified_editorial_pipeline_enabled` AND a real V8-family
copywriting output - see `worker/content_cycle.py`'s own cutover branch for the exact gate).

This module OWNS, for the scope it handles (see below): presentation-format selection (reusing
`decide_presentation()` for FORMAT/category/BREAKING-rate-limiting only - its own `.data_candidate`/
`.quote_candidate` outputs are discarded, never used, exactly closing Founder review gap #1),
structured-content extraction (`build_structured_data_content()`/`build_structured_quote_content()`
via the orchestrator), media research/selection, composition planning, caption-budget compression,
the quality gate, and the recovery decision. `worker/content_cycle.py` after this call does nothing
but read back `UnifiedTelegramDeliveryOutcome` and update its own cycle bookkeeping (counters,
`sent_message_id`/`sent_chat_id` for the shared `record_delivery()` call) - it never re-inspects
low-level media/content fields or makes a second editorial decision (Founder review gap #1's fix).

Disclosed scope limitation (deliberate, not an oversight - "Do NOT redesign anything else" plus
this phase's own effort/risk bound): this module delivers SINGLE-PHOTO-OR-TEXT only. Multi-photo
media groups, native hosted video, and the Gemini-based editorial-recomposition step are NOT
reimplemented here - they remain exactly where they already are, in the legacy path, and this
module's own caller only ever routes here when it would otherwise be a single-photo/text send
(`rich_media_mode` is "off"/"shadow" in every real deployed environment today - confirmed in
`docs/unified_editorial_production_pipeline_cutover_1_report.md` S17 "remaining legacy debt"). A
future phase can extend this module's own render callback to cover media groups/video without
touching `worker/content_cycle.py`'s own cutover gate again.

Real recovery integration (Founder review gap #2's fix - S9/S20): every reason code below is
produced by a REAL call site and persisted via `RecoveryService`, never a decorative enum value.
`AMBIGUOUS_TRANSPORT_RESULT` is never auto-resent (S11's own explicit rule) - it becomes a durable
row and this cycle's delivery simply ends without a second send attempt.

RUNTIME-CLOSURE-1 (S2/S6/S8): the Founder audit's gap A ("selected media and rendered media can
diverge") and gap D ("candidate pool prematurely reduced") both traced to this module specifically:
`_resolve_single_photo_candidate()` reduced the eligible pool to exactly ONE candidate via legacy
ranking BEFORE `MediaResearchService`/subject verification ever ran, and the render callback used
that ONE candidate's pre-captured bytes unconditionally - regardless of what `MediaSelectionResult.
selected` actually decided. Fixed here by:

- `_resolve_photo_candidate_pool()` (renamed, bounded to `MAX_CANDIDATE_POOL_SIZE`) now hands
  MediaResearchService a real, bounded MULTI-candidate pool - subject verification and MISMATCH/
  EDITORIAL_REVIEW_REQUIRED exclusion happen BEFORE any single candidate is picked, never after.
- The render callback no longer closes over a pre-selected candidate's bytes. It receives
  `media_selection` directly (the orchestrator's own new `RenderCallable` contract - see
  `services.editorial_pipeline.orchestrator`) and resolves EXACTLY `media_selection.selected` via
  `services.editorial_pipeline.media_asset_resolver.resolve_selected_media_asset()` - the same
  object every other stage (composition, quality gate) already inspected. There is no candidate
  reference in this module's own closure state for the render callback to use by mistake.
- A resolution failure for a real, selected candidate (Case A/B: local bytes gone, no cached
  file_id) returns a `MediaResolutionFailure` sentinel - the orchestrator maps this to a real,
  reason-coded `MEDIA_RESOLUTION_FAILED` recovery, never an ordinary text send (S17/S18).
- A valid cached Telegram file_id resolves and delivers safely even when local bytes are gone
  (Case B/S16) - reusing `bot/image_preview_media.py`'s own proven "file_id first" policy via the
  resolver, never HELD merely because a local temp file expired.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING
from uuid import UUID

from aiogram import Bot
from aiogram.types import BufferedInputFile, InlineKeyboardMarkup
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from schemas.editorial_route import EditorialDestination
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
)
from services.brand_renderer import render_branded_media
from services.data_source_classification import classify_source_presentation, select_data_presentation_mode
from services.editorial_pipeline.contracts import (
    DataCompositionStrategy,
    MediaResolutionFailure,
    MediaSelectionResult,
    OrchestratorVerdict,
    Platform,
    PresentationFormat,
    QuoteCandidate as PipelineQuoteCandidate,
    RecoveryReasonCode,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.media_asset_resolver import resolve_selected_media_asset
from services.editorial_pipeline.orchestrator import run_editorial_production_pipeline
from services.editorial_pipeline.recovery_service import RecoveryService
from services.editorial_pipeline.subject_match import classify_subject_match
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    get_recently_attached_image_source_urls,
    sanitize_url,
)
from services.media_web_discovery import WebDiscoveryClient
from services.nnj_master_news_overlay import apply_master_news_branding
from services.presentation_director import (
    DataCandidate,
    QuoteCandidate,
    build_editorial_code,
    decide_presentation,
)
from services.news_telegram_presentation import is_v8_family_output, render_v81_news_card_html
from services.telegram_routing import (
    RoutingOutcome,
    send_photo_to_editorial_destination,
    send_to_editorial_destination,
)

if TYPE_CHECKING:
    from database.models.news_event import NewsEvent

logger = logging.getLogger(__name__)

_FORMAT_BY_LEGACY_STRING = {
    "NEWS": PresentationFormat.NEWS, "BREAKING": PresentationFormat.BREAKING,
    "DATA": PresentationFormat.DATA, "QUOTE": PresentationFormat.QUOTE,
}

MAX_CANDIDATE_POOL_SIZE = 10
"""RUNTIME-CLOSURE-1 (S8): the bounded ceiling on how many eligible legacy candidates are wrapped
and handed to `MediaResearchService` for real subject verification. Chosen from this codebase's own
existing characteristics: `MediaResearchService.max_web_candidates_to_classify` already defaults to
8 (services/editorial_pipeline/media.py) for the SAME per-candidate classification cost (one
`subject_match_classifier` call each); 10 keeps the Tier-1 legacy pool in the same order of
magnitude rather than inventing an unrelated second bound. Not unlimited (S8's own explicit
instruction) - a NewsEvent's `image_candidates` table can accumulate far more than 10 rows over
time, and classifying all of them would scale badly with zero truthfulness benefit past the
legacy ranking's own top handful."""


def is_unified_router_eligible(copywriting_output: dict | None) -> bool:
    """The exact, narrow gate `worker/content_cycle.py` checks alongside
    `settings.unified_editorial_pipeline_enabled` (S2 - "the flag must select between LEGACY or
    UNIFIED, not legacy + shadow"). `False` for `None` or a non-V8-family shape - both route to the
    completely unmodified legacy branch, exactly as they always have (V8-family is the only shape
    any real production send has ever produced - see this phase's own report)."""
    return copywriting_output is not None and is_v8_family_output(copywriting_output)


@dataclass(frozen=True)
class UnifiedTelegramDeliveryOutcome:
    """Everything `worker/content_cycle.py` needs to finish its own cycle bookkeeping - never a
    raw `DeliveryPackage`/`MediaSelectionResult`/etc. (the worker must not inspect those - S5)."""

    verdict: OrchestratorVerdict
    presentation_type: str
    """"NEWS"/"BREAKING"/"DATA"/"QUOTE" - for the worker's own `presentation_breaking_sent`
    counter and diagnostic logging, mirroring the legacy field of the same name."""
    sent: bool
    dry_run: bool
    sent_message_id: int | None
    sent_chat_id: int | None
    had_photo: bool
    held: bool
    """True when this cycle produced no send at all (RETRY/HOLD/BLOCK, or a transport
    failure/ambiguity) - the worker's own `visual_required_held`-equivalent counter."""
    recovery_reason: str | None
    recovery_job_id: UUID | None


def _wrap_legacy_candidate_as_tier1(candidate: EditorialImageCandidate) -> ResolvedMediaCandidate:
    """Bridges the EXISTING, already-vetted Phase 16 `image_candidates` pool into the S10-S16
    `ResolvedMediaCandidate` shape `MediaResearchService` expects - reusing the real candidate
    discovery/ranking this codebase already has (`get_editorial_image_candidates()` +
    `_select_top_ranked_image_candidates()`, both called by this module's own caller before this
    function runs), never a second, competing discovery mechanism. `usage_classification=
    APPROVED_SOURCE_MEDIA`/`discovery_tier=TIER1_CURRENT_SOURCE` matches this candidate's own real
    provenance (it came from the NewsEvent's own already-vetted source, exactly what Tier 1 means -
    schemas/media_subject_match.py's own `DiscoveryTier` docstring).

    FINAL-HARDENING-1: `subject_match` is still left unset (`None`) here, and `provenance.
    caption_or_alt` is still `None` - both HONESTLY, not as an oversight: `EditorialImageCandidate`
    (the legacy Phase 16 record this wraps) carries no subject-descriptive text field of any kind
    (`relevance_reason` describes WHY the image was judged relevant to the article, never WHAT it
    depicts) - there is no real text evidence to give the classifier for this specific candidate
    shape today. `run_unified_telegram_delivery()` DOES now inject a real `subject_match_classifier`
    (`services.editorial_pipeline.subject_match.classify_subject_match`) into `MediaResearchService.
    research()` - closing the Founder review's own HIGH finding (no central authority was ever
    invoked at all) - but for THIS candidate shape specifically, that classifier will correctly
    return `GENERIC_CONTEXT` (its own explicit "no evidence" branch), never a fabricated
    `EXACT_SUBJECT`. This is the safe, honest behavior for missing evidence (Founder review §6), and
    is unrelated to whether the classifier itself runs - it runs, and will correctly produce
    `EXACT_SUBJECT`/`STRONG_CONTEXT`/`MISMATCH` the moment a candidate DOES carry real descriptive
    text (already true today for any real Tier 2-5 web-discovered candidate via
    `services/media_web_discovery.py`'s own `caption_or_alt` field - not exercised by this specific
    wrapper, which only ever builds a Tier-1 candidate)."""
    return ResolvedMediaCandidate(
        candidate_id=str(candidate.id),
        provenance=MediaProvenance(
            origin_url=(candidate.article_url or candidate.source_url or "")[:2000] or "unknown:origin",
            asset_url=(candidate.source_url or candidate.article_url or "")[:2000] or "unknown:asset",
            discovered_at=datetime.now(timezone.utc),
            discovery_tier=DiscoveryTier.TIER1_CURRENT_SOURCE,
            caption_or_alt=None,
        ),
        width=candidate.width, height=candidate.height,
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
        image_candidate_record_id=str(candidate.id),
        existing_relevance_score=candidate.relevance_score, existing_quality_score=candidate.quality_score,
    )


def _build_data_candidate(structured) -> DataCandidate:
    """The real fix for Founder review gap #1 - `StructuredDataContent` (built by
    `services.editorial_pipeline.content.build_structured_data_content()`, never by the OLD
    `presentation_director._find_data_candidate()` regex extractor) converted into the SAME
    `DataCandidate` shape the frozen, Founder-approved V8 renderer (`render_branded_media()`)
    already expects - the renderer itself is not modified by one byte; only what feeds it is real
    now. `label`/`value`/`unit` come from the new, structured fields - never a mangled prose
    remainder (the exact "начинается с юаней" defect class)."""
    return DataCandidate(
        value=structured.metric_value, unit=structured.metric_unit, label=structured.metric_label,
        evidence_fact=structured.source_fact, series=structured.series, delta=structured.delta,
    )


def _build_quote_candidate_for_render(structured) -> QuoteCandidate:
    return QuoteCandidate(text=structured.quote, speaker=structured.speaker, role=structured.role)


def _make_render_callback(
    *, legacy_candidates_by_id: dict[str, EditorialImageCandidate],
    copywriting_output: dict, treatment: str, quote_text: str | None, quote_speaker: str | None,
    category: str, editorial_code: str,
):
    """The real Telegram `RenderCallable` (`services.editorial_pipeline.orchestrator.RenderCallable`)
    - wraps the EXISTING, Founder-approved, V8-frozen renderers unchanged
    (`render_v81_news_card_html()` for the caption HTML, always; `apply_master_news_branding()` for
    NEWS's own photo overlay; `render_branded_media()` for BREAKING/DATA/QUOTE cards). Never draws a
    pixel itself - S17's own "renderer does only layout/typography/crop/brand treatment/drawing"
    boundary, delegated entirely to these three real functions.

    RUNTIME-CLOSURE-1 (S3.1/S6/S7): resolves the EXACT candidate `media_selection.selected` names,
    at render time, via `resolve_selected_media_asset()` - never a candidate/bytes closed over
    before `MediaResearchService` ran. `legacy_candidates_by_id` is the SAME dict the caller built
    from the SAME bounded pool that was wrapped into `tier1_candidates`, so this function can never
    resolve a candidate the orchestrator's own `media_selection` did not actually select.

    A branding/card-render failure here returns `None` (RENDER_FAILED, a real bounded recovery); a
    resolution failure for a real selected candidate returns `MediaResolutionFailure`
    (MEDIA_RESOLUTION_FAILED) - two distinguishable, never-silently-downgraded outcomes (S17/S18).
    Both are a deliberate, disclosed departure from the legacy path's own silent "demote to NEWS"/
    "demote to text" fail-safes (`worker/content_cycle.py`'s own spec-S29 comment): the unified path
    treats every such failure as a real, reason-coded, recoverable event, never a silent downgrade
    the worker would otherwise have to notice and re-decide (exactly the post-hoc editorial
    re-decision S5 forbids the worker from making)."""

    async def _render(composition_plan, structured_content, media_selection: MediaSelectionResult):
        fmt = composition_plan.presentation_format
        html = render_v81_news_card_html(
            copywriting_output, treatment=treatment, quote_text=quote_text, quote_speaker=quote_speaker,
            include_ninja_pulse_footer=True,
        )

        resolution = await resolve_selected_media_asset(media_selection, legacy_candidates_by_id=legacy_candidates_by_id)
        if resolution.failed:
            return MediaResolutionFailure(
                candidate_id=media_selection.selected.candidate_id if media_selection.selected else None,
                detail=resolution.failure_detail or "media resolution failed",
            )
        asset = resolution.asset  # None exactly when nothing was selected (a legitimate,
        # text-appropriate/no-media outcome the orchestrator's own require_media/DATA_TYPOGRAPHIC
        # logic already approved before this callback was ever invoked).

        if fmt == PresentationFormat.NEWS:
            if asset is None:
                return None, html  # legitimate text-appropriate NEWS (only reachable if the
                # caller did not set require_media=True - kept for defensiveness/reuse elsewhere)
            if asset.resolved_bytes is not None:
                try:
                    branded_bytes, _decision = apply_master_news_branding(asset.resolved_bytes, disable_lower_signature=False)
                except Exception:  # noqa: BLE001 - a render failure must become a real recovery, never a crash
                    logger.warning("unified_news_branding_failed", exc_info=True)
                    return None
                return BufferedInputFile(branded_bytes, filename="pulse.jpg"), html
            if asset.telegram_file_id is not None:
                # S16/Case B: a valid, already-cached Telegram asset for THIS SAME selected
                # candidate - delivered directly. Disclosed, bounded trade-off: the master-news
                # corner-mark overlay cannot be freshly re-applied without raw pixels, so this
                # specific fallback path reuses the cached asset as-is rather than re-branding it -
                # preferring a truthful, correct-subject delivery over branding-freshness, exactly
                # Case B's own explicit priority ("do not HOLD merely because a local temporary
                # file disappeared if a valid Telegram-native reusable media reference exists").
                return asset.telegram_file_id, html
            return MediaResolutionFailure(candidate_id=asset.candidate_id, detail="asset resolved with neither bytes nor file_id")

        data_candidate = _build_data_candidate(structured_content) if fmt == PresentationFormat.DATA and structured_content is not None else None
        quote_candidate = _build_quote_candidate_for_render(structured_content) if fmt == PresentationFormat.QUOTE and structured_content is not None else None

        if asset is not None and asset.resolved_bytes is None:
            # BREAKING/DATA/QUOTE render an entirely new branded CARD from the source image
            # (never just an overlay) - render_branded_media() has no way to compose one without
            # real pixels. A cached file_id alone cannot produce a truthful card here, unlike
            # NEWS's lightweight overlay above. DATA has its own legitimate no-photo strategies
            # (DATA_TYPOGRAPHIC/DATA_WITH_GRAPH, decided upstream in composition.py) that never
            # needed this image in the first place; only genuinely reaching for
            # DATA_WITH_SOURCE_IMAGE/BREAKING/QUOTE with an unresolvable photo is a real failure.
            if fmt != PresentationFormat.DATA or composition_plan.data_strategy == DataCompositionStrategy.DATA_WITH_SOURCE_IMAGE:
                return MediaResolutionFailure(
                    candidate_id=asset.candidate_id,
                    detail="only a cached file_id was resolved; this format's card render requires real source bytes",
                )

        source_bytes = asset.resolved_bytes if asset is not None else None
        legacy_record = (
            legacy_candidates_by_id.get(asset.candidate_id)
            if asset is not None and asset.candidate_id is not None else None
        )
        # `image_candidate_record_id` (not `candidate_id`) is the actual key `legacy_candidates_by_id`
        # is built from - see `_wrap_legacy_candidate_as_tier1()`; for a Tier-1 candidate these are
        # equal (str(row.id) is used for both), so this lookup is correct for every candidate this
        # module's own pool can currently produce (web-discovered Tier 2-5 candidates are not in
        # this dict at all, and `legacy_record` correctly stays None for them).
        data_presentation_mode = select_data_presentation_mode(
            classify_source_presentation(legacy_record.warnings if legacy_record is not None else None)
        )
        render_result = render_branded_media(
            presentation_type=fmt.value, source_image_bytes=source_bytes, category=category,
            editorial_code=editorial_code, branding_strength="STANDARD",
            data_candidate=data_candidate, quote_candidate=quote_candidate,
            data_presentation_mode=data_presentation_mode,
        )
        if not render_result.success or render_result.image_bytes is None:
            logger.warning(
                "unified_branded_media_render_failed",
                extra={"presentation_type": fmt.value, "fallback_reason": render_result.fallback_reason},
            )
            return None
        return BufferedInputFile(render_result.image_bytes, filename="pulse.jpg"), html

    return _render


async def _resolve_photo_candidate_pool(
    session_factory: async_sessionmaker[AsyncSession], *, content_draft_id: UUID, news_event_id: UUID,
    limit: int = MAX_CANDIDATE_POOL_SIZE,
) -> list[EditorialImageCandidate]:
    """RUNTIME-CLOSURE-1 (S8): renamed from `_resolve_single_photo_candidate` - returns a real,
    BOUNDED multi-candidate pool (never reduced to one before subject verification runs), reusing
    the EXISTING, real candidate retrieval/duplicate-guard the legacy path already relies on
    (`get_editorial_image_candidates()`, `get_recently_attached_image_source_urls()`) - no second
    discovery/ranking pipeline. Local import of `worker.content_cycle._select_top_ranked_image_
    candidates` (module-private, matching `services.editorial_pipeline.recovery.
    apply_telegram_recovery()`'s own established lazy-import precedent for exactly this reason:
    avoiding a hard import-time dependency from this platform-neutral package onto
    `worker.content_cycle`, which itself imports this module). The legacy ranking still orders the
    pool (best-legacy-rank first) - only the `limit=1` truncation is removed; `MediaResearchService`
    itself decides the final winner from real subject-match/rights evidence, never merely inheriting
    whatever this legacy rank happened to put first."""
    from worker.content_cycle import _select_top_ranked_image_candidates

    async with session_factory() as session:
        candidates = await get_editorial_image_candidates(session, content_draft_id=content_draft_id)
        recently_used_urls = await get_recently_attached_image_source_urls(session, exclude_news_event_id=news_event_id)
    eligible = [
        c for c in candidates
        if not c.is_expired and not (c.source_url and sanitize_url(c.source_url) in recently_used_urls)
    ]
    return _select_top_ranked_image_candidates(eligible, limit=limit)


async def run_unified_telegram_delivery(
    *,
    session_factory: async_sessionmaker[AsyncSession],
    bot: Bot,
    event: "NewsEvent",
    content_draft_id: UUID,
    task_id: UUID,
    copywriting_output: dict,
    treatment: str,
    research_facts: list[str],
    presentation_score: int | None,
    quote_text: str | None,
    quote_speaker: str | None,
    keyboard: InlineKeyboardMarkup | None,
    reply_to_message_id: int | None,
    effective_dry_run: bool,
    breaking_count_this_cycle: int,
    breaking_max_per_cycle: int,
    breaking_enabled: bool,
    story_id: UUID | None = None,
    web_discovery_client: WebDiscoveryClient | None = None,
) -> UnifiedTelegramDeliveryOutcome:
    """The one call site (S25 for the cutover) - `worker/content_cycle.py`'s router-mode V8-family
    branch calls this INSTEAD OF its own legacy decision tree (never alongside it - S2). Owns
    format selection through delivery/recovery; the worker only reads back the result.

    RUNTIME-CLOSURE-1 (S12): `web_discovery_client` defaults to `None` (-> `MediaResearchService`'s
    own `NullWebDiscoveryClient`, zero network calls, unchanged from every previous phase) -
    genuinely no automated search-API/press-kit/stock-photo client exists anywhere in this codebase
    today (confirmed by direct audit; see `services/media_web_discovery.py`'s own module
    docstring), so there is nothing production-safe to default this to instead. The parameter
    exists purely as the structural wiring point: the day a real client IS built, injecting it here
    is a one-line change at this ONE call site, never a second call site or an architecture change."""
    recovery_service = RecoveryService()

    # --- format selection (S1: `decide_presentation()` reused for FORMAT/category/BREAKING-rate-
    # limiting only - its `.data_candidate`/`.quote_candidate` are discarded below, never read). ---
    presentation_decision = decide_presentation(
        title=event.title, content=event.content, copywriting_output=copywriting_output,
        treatment=treatment, scoring_score=presentation_score, research_facts=research_facts,
        quote_text=quote_text, quote_speaker=quote_speaker, fallback_category=event.category,
        breaking_count_this_cycle=breaking_count_this_cycle, breaking_max_per_cycle=breaking_max_per_cycle,
        breaking_enabled=breaking_enabled,
    )
    presentation_format = _FORMAT_BY_LEGACY_STRING.get(presentation_decision.presentation_type, PresentationFormat.NEWS)

    logger.info(
        "unified_pipeline_selected",
        extra={
            "draft_id": str(content_draft_id), "event_id": str(event.id),
            "presentation_type": presentation_decision.presentation_type,
        },
    )

    evidence = build_evidence_pack(
        news_event_id=event.id, story_id=story_id, source_url=event.url, research_facts=research_facts,
    )

    # RUNTIME-CLOSURE-1 (S8): a real, BOUNDED multi-candidate pool - never reduced to one before
    # MediaResearchService's own subject verification/rights exclusion runs (Founder audit gap D).
    candidate_pool = await _resolve_photo_candidate_pool(
        session_factory, content_draft_id=content_draft_id, news_event_id=event.id,
    )
    tier1_candidates = [_wrap_legacy_candidate_as_tier1(c) for c in candidate_pool]
    legacy_candidates_by_id = {str(c.id): c for c in candidate_pool}

    quote_candidate_for_orchestrator = (
        PipelineQuoteCandidate(text=quote_text, speaker=quote_speaker, role=None)
        if presentation_format == PresentationFormat.QUOTE and quote_text else None
    )

    # RUNTIME-CLOSURE-1 (S3.1/S6): no candidate/bytes closed over here - the render callback
    # resolves EXACTLY whatever `media_selection.selected` ends up being, at render time, via
    # `legacy_candidates_by_id` (the same pool `tier1_candidates` above was built from).
    render = _make_render_callback(
        legacy_candidates_by_id=legacy_candidates_by_id, copywriting_output=copywriting_output,
        treatment=treatment, quote_text=quote_text, quote_speaker=quote_speaker,
        category=presentation_decision.category, editorial_code=build_editorial_code(task_id),
    )

    async with session_factory() as session:
        result = await run_editorial_production_pipeline(
            content_draft_id=content_draft_id, presentation_format=presentation_format,
            title=event.title, main_body=copywriting_output.get("main_body"), evidence=evidence,
            platform=Platform.TELEGRAM, render=render, quote_candidate=quote_candidate_for_orchestrator,
            tier1_candidates=tier1_candidates, session=session, recovery_service=recovery_service,
            require_media=True,
            # FINAL-HARDENING-1 (Founder review HIGH finding): the real, central subject-match
            # authority - see services/editorial_pipeline/subject_match.py's own module docstring.
            # This is the ONE classifier MediaResearchService.research() ever receives from this
            # call site; it is never duplicated or re-decided anywhere else in this pipeline.
            subject_match_classifier=classify_subject_match,
            # RUNTIME-CLOSURE-1 (S12): structural wiring only - see this function's own docstring;
            # `None` here (the only value any real caller passes today) is identical to every
            # previous phase's behavior.
            web_discovery_client=web_discovery_client,
        )
        await session.commit()

    if result.verdict != OrchestratorVerdict.READY:
        reason = result.recovery_job.reason_code.value if result.recovery_job else None
        logger.warning(
            "unified_pipeline_held",
            extra={
                "draft_id": str(content_draft_id), "verdict": result.verdict.value, "reason": reason,
                "recovery_job_id": str(result.persisted_recovery_job_id) if result.persisted_recovery_job_id else None,
            },
        )
        return UnifiedTelegramDeliveryOutcome(
            verdict=result.verdict, presentation_type=presentation_decision.presentation_type,
            sent=False, dry_run=effective_dry_run, sent_message_id=None, sent_chat_id=None,
            had_photo=False, held=True, recovery_reason=reason,
            recovery_job_id=result.persisted_recovery_job_id,
        )

    package = result.delivery_package
    assert package is not None  # guaranteed by verdict == READY
    photo_input = package.composition_plan.photo_input
    # `CompositionPlan.photo_input` is typed `object | None` (platform-neutral contract - see its
    # own docstring); this module's own render callback (`_make_render_callback()` above) only
    # ever returns `str | BufferedInputFile | None` for it, so this narrowing is always correct.
    assert photo_input is None or isinstance(photo_input, (str, BufferedInputFile))

    # --- S18: final pre-transport visual assertion - the last safety net even if every upstream
    # gate somehow agreed to a READY package with no visual for a format that structurally needs
    # one. NEWS/BREAKING/QUOTE always require a photo here (require_media=True already enforced
    # this before render ever ran); DATA only requires one when its own composition strategy chose
    # DATA_WITH_SOURCE_IMAGE (DATA_TYPOGRAPHIC/DATA_WITH_GRAPH are legitimately photo-less). If this
    # ever fires, it means a real defect exists upstream - it must NEVER be silently routed to an
    # ordinary text send; instead this becomes a real, reason-coded, durable recovery.
    visual_required_for_send = (
        presentation_format != PresentationFormat.DATA
        or package.composition_plan.data_strategy == DataCompositionStrategy.DATA_WITH_SOURCE_IMAGE
    )
    if visual_required_for_send and photo_input is None:
        logger.warning(
            "unified_pretransport_visual_assertion_failed",
            extra={"draft_id": str(content_draft_id), "presentation_format": presentation_format.value},
        )
        async with session_factory() as session:
            row = await recovery_service.create_or_retry(
                session, content_draft_id=content_draft_id, platform=Platform.TELEGRAM,
                reason_code=RecoveryReasonCode.MEDIA_RESOLUTION_FAILED, failed_stage="pretransport_visual_assertion",
                last_error="a visual-required READY package reached transport with no photo_input",
            )
            await session.commit()
            recovery_job_id = row.id
        return UnifiedTelegramDeliveryOutcome(
            verdict=OrchestratorVerdict.HOLD, presentation_type=presentation_decision.presentation_type,
            sent=False, dry_run=False, sent_message_id=None, sent_chat_id=None,
            had_photo=False, held=True, recovery_reason=RecoveryReasonCode.MEDIA_RESOLUTION_FAILED.value,
            recovery_job_id=recovery_job_id,
        )

    if photo_input is not None:
        routing_outcome: RoutingOutcome = await send_photo_to_editorial_destination(
            bot, EditorialDestination.NEWS, photo_input, package.caption_or_copy,
            dry_run=effective_dry_run, reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
        )
    else:
        routing_outcome = await send_to_editorial_destination(
            bot, EditorialDestination.NEWS, package.caption_or_copy,
            dry_run=effective_dry_run, reply_markup=keyboard, reply_to_message_id=reply_to_message_id,
        )

    logger.info(
        "transport_result",
        extra={
            "draft_id": str(content_draft_id), "sent": routing_outcome.sent, "reason": routing_outcome.reason,
            "ambiguous": routing_outcome.ambiguous, "had_photo": photo_input is not None,
        },
    )

    if routing_outcome.sent:
        return UnifiedTelegramDeliveryOutcome(
            verdict=OrchestratorVerdict.READY, presentation_type=presentation_decision.presentation_type,
            sent=True, dry_run=False, sent_message_id=routing_outcome.message_id, sent_chat_id=routing_outcome.chat_id,
            had_photo=photo_input is not None, held=False, recovery_reason=None, recovery_job_id=None,
        )

    if routing_outcome.reason == "dry_run":
        return UnifiedTelegramDeliveryOutcome(
            verdict=OrchestratorVerdict.READY, presentation_type=presentation_decision.presentation_type,
            sent=False, dry_run=True, sent_message_id=None, sent_chat_id=None,
            had_photo=photo_input is not None, held=False, recovery_reason=None, recovery_job_id=None,
        )

    # A real transport failure/ambiguity for an already-READY package - S11/S20: map to a real,
    # durable recovery, never a blind resend (AMBIGUOUS) and never a silent text fallback (FAILED).
    reason_code = "AMBIGUOUS_TRANSPORT_RESULT" if routing_outcome.ambiguous else "MEDIA_SEND_FAILED"

    async with session_factory() as session:
        row = await recovery_service.create_or_retry(
            session, content_draft_id=content_draft_id, platform=Platform.TELEGRAM,
            reason_code=RecoveryReasonCode(reason_code), failed_stage="telegram_transport",
            last_error=routing_outcome.reason,
        )
        await session.commit()
        recovery_job_id = row.id

    logger.warning(
        "unified_transport_failure_recovery",
        extra={"draft_id": str(content_draft_id), "reason_code": reason_code, "recovery_job_id": str(recovery_job_id)},
    )
    return UnifiedTelegramDeliveryOutcome(
        verdict=OrchestratorVerdict.HOLD, presentation_type=presentation_decision.presentation_type,
        sent=False, dry_run=False, sent_message_id=None, sent_chat_id=None,
        had_photo=photo_input is not None, held=True, recovery_reason=reason_code, recovery_job_id=recovery_job_id,
    )
