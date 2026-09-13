"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S25): the one shared orchestrator.

`run_editorial_production_pipeline()` is the target S25 describes for `worker/content_cycle.py`:
"lease/select eligible task -> invoke EditorialProductionOrchestrator -> persist orchestrator
result -> ack/bounded retry." This module IS that orchestrator - a plain async function (not a
class; nothing here holds cross-call state that would justify one) walking exactly the pipeline
named in the phase brief's own target architecture (S5):

    EvidencePack -> StructuredContent -> VisualIntent -> MediaResearch -> MediaSelection
    -> CompositionPlan -> QualityGate -> DeliveryPackage | RecoveryJob

Rendering itself (`render: RenderCallable`) is injected, never performed here - S17's own
"renderer does only layout/typography/crop/brand treatment/drawing" boundary means this
orchestrator's job stops at handing the renderer a `CompositionPlan` plus the structured content it
needs to draw truthfully, and reading back whatever caption/copy text and photo input the renderer
(or, for the no-render-needed NEWS case, the caller) produced. This keeps the orchestrator itself
completely renderer-agnostic and trivially testable without Pillow/real image bytes - the real
Founder-approved V8 renderers (`services/brand_renderer.py`, `services/news_telegram_presentation.py`)
are what a real Telegram caller injects here; a test injects a deterministic fake.

Bounded by construction (S4-E/S9's own "no generation loop"): this function calls
`build_structured_data_content()`/`build_structured_quote_content()`, `MediaResearchService.
research()`, and `render` each exactly once per call - never retried internally. A RecoveryJob's
own `max_attempts` (S23) governs whether the ORCHESTRATOR'S CALLER tries again on a later cycle,
never a loop inside this function itself.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Awaitable, Protocol
from uuid import UUID

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import MediaSelectionResult, ResolvedMediaCandidate
from services.editorial_pipeline.composition import build_composition_plan
from services.editorial_pipeline.content import build_structured_data_content, build_structured_quote_content
from services.editorial_pipeline.contracts import (
    CompositionPlan,
    DeliveryPackage,
    EvidencePack,
    Platform,
    PresentationFormat,
    QuoteCandidate,
    RecoveryJob,
    RecoveryReasonCode,
    StructuredContent,
    StructuredNewsContent,
)
from services.editorial_pipeline.media import MediaResearchService
from services.editorial_pipeline.platforms.telegram import plan_telegram_caption_budget
from services.editorial_pipeline.quality import run_quality_gate
from services.editorial_pipeline.recovery import create_recovery_job
from services.media_research_selection import SubjectMatchClassifier
from services.media_web_discovery import WebDiscoveryClient

logger = logging.getLogger(__name__)


class RenderCallable(Protocol):
    """`(composition_plan, structured_content) -> (rendered_photo_input, rendered_caption_html) |
    None`. Returns None exactly when rendering could not honestly produce a valid visual (S4-E:
    RENDER_FAILED) - never a placeholder image, never fabricated content. `rendered_photo_input`
    stays `None` for a text-appropriate composition (S4-C's own carve-out) or when `composition_
    plan.data_strategy == DATA_TYPOGRAPHIC` and the caller's own renderer produces a typographic
    card as the photo input itself (both are legitimate - this Protocol does not prescribe which)."""

    def __call__(
        self, composition_plan: CompositionPlan, structured_content: StructuredContent | None,
    ) -> Awaitable[tuple[object | None, str]]: ...


@dataclass(frozen=True)
class PipelineResult:
    delivery_package: DeliveryPackage | None
    recovery_job: RecoveryJob | None

    @property
    def is_ready(self) -> bool:
        return self.delivery_package is not None


async def run_editorial_production_pipeline(
    *, content_draft_id: UUID, presentation_format: PresentationFormat, title: str, main_body: str | None,
    evidence: EvidencePack, platform: Platform, render: RenderCallable,
    quote_candidate: QuoteCandidate | None = None,
    visual_intent: MediaIntent | None = None, tier1_candidates: list[ResolvedMediaCandidate] | None = None,
    web_discovery_client: WebDiscoveryClient | None = None,
    subject_match_classifier: SubjectMatchClassifier | None = None,
    fallback_candidate: ResolvedMediaCandidate | None = None,
    media_research_service: MediaResearchService | None = None,
) -> PipelineResult:
    """The one call site a thin worker entrypoint needs (S25). Every stage below logs its own
    named diagnostic event (S32) with `content_draft_id` as the stable correlating id."""
    logger.info("pipeline_started", extra={"content_draft_id": str(content_draft_id), "presentation_format": presentation_format.value})

    # --- structured content (S8) ---
    structured_content: StructuredContent | None
    if presentation_format == PresentationFormat.DATA:
        structured_content = build_structured_data_content(title=title, main_body=main_body, evidence=evidence)
    elif presentation_format == PresentationFormat.QUOTE and quote_candidate is not None:
        structured_content = build_structured_quote_content(quote_candidate=quote_candidate, evidence=evidence)
    else:
        structured_content = StructuredNewsContent(
            headline=title, body=main_body or "", ending=None,
            evidence_claim_ids=tuple(c.claim_id for c in evidence.claims),
        )
    logger.info(
        "structured_content_ready",
        extra={"content_draft_id": str(content_draft_id), "content_type": type(structured_content).__name__ if structured_content else None},
    )

    # --- media research + selection (S10-S16) ---
    intent = visual_intent
    if intent is None:
        from services.editorial_pipeline.media import build_visual_intent_from_evidence

        intent = build_visual_intent_from_evidence(title=title, category=None, evidence=evidence, platform=platform.value)
    logger.info("media_research_started", extra={"content_draft_id": str(content_draft_id), "primary_entity": intent.primary_entity})

    service = media_research_service or MediaResearchService()
    media_selection: MediaSelectionResult = await service.research(
        intent, tier1_candidates=tier1_candidates, web_discovery_client=web_discovery_client,
        subject_match_classifier=subject_match_classifier, fallback_candidate=fallback_candidate,
    )
    for reason in media_selection.rejection_reasons:
        logger.info("media_candidate_rejected", extra={"content_draft_id": str(content_draft_id), "reason": reason})
    if media_selection.selected is not None:
        logger.info(
            "media_selected",
            extra={"content_draft_id": str(content_draft_id), "candidate_id": media_selection.selected.candidate_id, "score": media_selection.selected_score},
        )

    # --- composition (S9/S17) ---
    data_content = structured_content if presentation_format == PresentationFormat.DATA else None
    composition_plan = build_composition_plan(
        presentation_format=presentation_format, structured_data=data_content,  # type: ignore[arg-type]
        media_selection=media_selection,
    )

    # --- render (S17 - delegated, never performed here) ---
    render_outcome = await render(composition_plan, structured_content)
    if render_outcome is None:
        job = create_recovery_job(
            content_draft_id=content_draft_id, reason_code=RecoveryReasonCode.RENDER_FAILED, failed_stage="render",
        )
        logger.info("pipeline_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": job.reason_code.value})
        return PipelineResult(delivery_package=None, recovery_job=job)
    photo_input, caption_or_copy = render_outcome
    composition_plan = CompositionPlan(
        presentation_format=composition_plan.presentation_format, data_strategy=composition_plan.data_strategy,
        photo_input=photo_input, media_group_items=composition_plan.media_group_items,
        caption_position=composition_plan.caption_position, branding_strength=composition_plan.branding_strength,
    )
    logger.info("composition_ready", extra={"content_draft_id": str(content_draft_id), "data_strategy": composition_plan.data_strategy.value if composition_plan.data_strategy else None})

    # --- Telegram caption budget (S19) - platform-specific, run before the gate, never inside transport ---
    if platform == Platform.TELEGRAM:
        caption_plan = plan_telegram_caption_budget(caption_or_copy, has_visual=photo_input is not None)
        if not caption_plan.fits:
            job = create_recovery_job(
                content_draft_id=content_draft_id, reason_code=RecoveryReasonCode.CAPTION_BUDGET_FAILED, failed_stage="caption_budget",
            )
            logger.info("pipeline_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": job.reason_code.value})
            return PipelineResult(delivery_package=None, recovery_job=job)
        caption_or_copy = caption_plan.caption or caption_or_copy

    # --- quality gate (S21) ---
    gate_result = run_quality_gate(
        content=structured_content, evidence=evidence, media_selection=media_selection,
        caption_or_copy=caption_or_copy, platform=platform,
    )
    logger.info("quality_gate_result", extra={"content_draft_id": str(content_draft_id), "verdict": gate_result.verdict.value})

    if gate_result.verdict.value != "READY":
        job = create_recovery_job(
            content_draft_id=content_draft_id, reason_code=RecoveryReasonCode.QUALITY_GATE_FAILED, failed_stage="quality_gate",
            candidate_diagnostics=tuple(c.reason for c in gate_result.failed_checks),
        )
        logger.info("pipeline_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": job.reason_code.value})
        return PipelineResult(delivery_package=None, recovery_job=job)

    package = DeliveryPackage(
        platform=platform, presentation_format=presentation_format, composition_plan=composition_plan,
        quality_gate_result=gate_result, caption_or_copy=caption_or_copy,
    )
    logger.info("delivery_package_ready", extra={"content_draft_id": str(content_draft_id)})
    logger.info("pipeline_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "ready"})
    return PipelineResult(delivery_package=package, recovery_job=None)
