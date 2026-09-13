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
    OrchestratorVerdict,
    Platform,
    PresentationFormat,
    QuoteCandidate as PipelineQuoteCandidate,
    RecoveryReasonCode,
)
from services.editorial_pipeline.evidence import build_evidence_pack
from services.editorial_pipeline.orchestrator import run_editorial_production_pipeline
from services.editorial_pipeline.recovery_service import RecoveryService
from services.image_persistence import (
    EditorialImageCandidate,
    get_editorial_image_candidates,
    get_recently_attached_image_source_urls,
    read_candidate_bytes,
    sanitize_url,
)
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
    schemas/media_subject_match.py's own `DiscoveryTier` docstring). `subject_match` is left unset
    (`None`) - deliberately: this module injects no `subject_match_classifier` into
    `MediaResearchService.research()` (no real vision-LLM call is added by this phase), so the
    candidate is scored via `services/media_candidate_scoring.py`'s own conservative unclassified
    default, never assumed EXACT_SUBJECT."""
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
    *, resolved_candidate: EditorialImageCandidate | None, photo_bytes: bytes | None,
    copywriting_output: dict, treatment: str, quote_text: str | None, quote_speaker: str | None,
    category: str, editorial_code: str,
):
    """The real Telegram `RenderCallable` (`services.editorial_pipeline.orchestrator.RenderCallable`)
    - wraps the EXISTING, Founder-approved, V8-frozen renderers unchanged
    (`render_v81_news_card_html()` for the caption HTML, always; `apply_master_news_branding()` for
    NEWS's own photo overlay; `render_branded_media()` for BREAKING/DATA/QUOTE cards). Never draws a
    pixel itself - S17's own "renderer does only layout/typography/crop/brand treatment/drawing"
    boundary, delegated entirely to these three real functions.

    A branding/card-render failure here returns `None` (RENDER_FAILED, a real bounded recovery) -
    a deliberate, disclosed departure from the legacy path's own silent "demote to NEWS" fail-safe
    for DATA/QUOTE/BREAKING (`worker/content_cycle.py`'s own spec-S29 comment): the unified path
    treats a genuine render failure as a real, reason-coded, recoverable event, never a silent
    format downgrade the worker itself would otherwise have to notice and re-decide (which is
    exactly the kind of post-hoc editorial re-decision S5 forbids the worker from making)."""

    async def _render(composition_plan, structured_content):
        fmt = composition_plan.presentation_format
        html = render_v81_news_card_html(
            copywriting_output, treatment=treatment, quote_text=quote_text, quote_speaker=quote_speaker,
            include_ninja_pulse_footer=True,
        )

        if fmt == PresentationFormat.NEWS:
            if photo_bytes is None:
                return None, html  # legitimate text-appropriate NEWS (only reachable if the
                # caller did not set require_media=True - kept for defensiveness/reuse elsewhere)
            try:
                branded_bytes, _decision = apply_master_news_branding(photo_bytes, disable_lower_signature=False)
            except Exception:  # noqa: BLE001 - a render failure must become a real recovery, never a crash
                logger.warning("unified_news_branding_failed", exc_info=True)
                return None
            return BufferedInputFile(branded_bytes, filename="pulse.jpg"), html

        data_candidate = _build_data_candidate(structured_content) if fmt == PresentationFormat.DATA and structured_content is not None else None
        quote_candidate = _build_quote_candidate_for_render(structured_content) if fmt == PresentationFormat.QUOTE and structured_content is not None else None
        data_presentation_mode = select_data_presentation_mode(
            classify_source_presentation(resolved_candidate.warnings if resolved_candidate is not None else None)
        )
        render_result = render_branded_media(
            presentation_type=fmt.value, source_image_bytes=photo_bytes, category=category,
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


async def _resolve_single_photo_candidate(
    session_factory: async_sessionmaker[AsyncSession], *, content_draft_id: UUID, news_event_id: UUID,
) -> EditorialImageCandidate | None:
    """Single-photo only (disclosed scope limitation - see module docstring): reuses the EXISTING,
    real candidate retrieval/ranking/duplicate-guard the legacy path already relies on
    (`get_editorial_image_candidates()`, `get_recently_attached_image_source_urls()`) - no second
    discovery/ranking pipeline. Local import of `worker.content_cycle._select_top_ranked_image_
    candidates` (module-private, matching `services.editorial_pipeline.recovery.
    apply_telegram_recovery()`'s own established lazy-import precedent for exactly this reason:
    avoiding a hard import-time dependency from this platform-neutral package onto
    `worker.content_cycle`, which itself imports this module)."""
    from worker.content_cycle import _select_top_ranked_image_candidates

    async with session_factory() as session:
        candidates = await get_editorial_image_candidates(session, content_draft_id=content_draft_id)
        recently_used_urls = await get_recently_attached_image_source_urls(session, exclude_news_event_id=news_event_id)
    eligible = [
        c for c in candidates
        if not c.is_expired and not (c.source_url and sanitize_url(c.source_url) in recently_used_urls)
    ]
    top = _select_top_ranked_image_candidates(eligible, limit=1)
    return top[0] if top else None


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
) -> UnifiedTelegramDeliveryOutcome:
    """The one call site (S25 for the cutover) - `worker/content_cycle.py`'s router-mode V8-family
    branch calls this INSTEAD OF its own legacy decision tree (never alongside it - S2). Owns
    format selection through delivery/recovery; the worker only reads back the result."""
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

    resolved_candidate = await _resolve_single_photo_candidate(
        session_factory, content_draft_id=content_draft_id, news_event_id=event.id,
    )
    photo_bytes = read_candidate_bytes(resolved_candidate) if resolved_candidate is not None else None
    tier1_candidates = [_wrap_legacy_candidate_as_tier1(resolved_candidate)] if resolved_candidate is not None else []

    quote_candidate_for_orchestrator = (
        PipelineQuoteCandidate(text=quote_text, speaker=quote_speaker, role=None)
        if presentation_format == PresentationFormat.QUOTE and quote_text else None
    )

    render = _make_render_callback(
        resolved_candidate=resolved_candidate, photo_bytes=photo_bytes, copywriting_output=copywriting_output,
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
