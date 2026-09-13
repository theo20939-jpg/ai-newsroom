"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S25) / UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1
(S5/S9/S13): the one shared orchestrator.

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
own `max_attempts` (S23, now really enforced by `services.editorial_pipeline.recovery_service.
RecoveryService` - see below) governs whether the ORCHESTRATOR'S CALLER tries again on a later
cycle, never a loop inside this function itself.

CUTOVER-1 additions, all backward-compatible (every parameter below is optional, defaulting to the
exact pre-cutover behavior - the pre-existing shadow-mode call site and this module's own
pre-existing test suite pass none of them and are completely unaffected):

- `session`/`recovery_service` (S9/S20): when both are supplied, every recovery path below persists
  a real, durable row via `RecoveryService.create_or_retry()` instead of the old in-process-only
  `create_recovery_job()` - real runtime callers, real state transitions, real `next_retry_at`,
  exactly what the Founder review found missing. When either is `None` (the default), the old
  in-process-only path runs unchanged - this is the ONE place that in-process fallback still
  matters, so a caller that has not been updated to pass a session keeps working exactly as before.
- `require_media` (S13): when `True`, a NEWS/BREAKING/QUOTE post with no truthful media candidate
  becomes a `NO_SUITABLE_MEDIA` recovery BEFORE render is ever attempted, rather than reaching
  render and possibly producing a text-appropriate READY package - this mirrors the real,
  currently-deployed worker product invariant (`worker/content_cycle.py`'s own "an ordinary
  router-mode NEWS/BREAKING/DATA/QUOTE post must never silently complete as a normal finished
  text-only send merely because no valid final visual could be resolved"), applied here as an
  explicit, opt-in orchestrator policy rather than the worker re-deciding it after the fact. `False`
  (the default) preserves this module's own pre-existing, more general "a renderer may honestly
  choose a text-appropriate composition" contract (`test_no_suitable_media_still_produces_a_
  ready_text_appropriate_package_when_render_allows_it`). DATA never needs this flag: its own
  `DataCompositionStrategy.DATA_TYPOGRAPHIC` strategy (composition.py) is already a legitimate,
  non-media outcome, chosen only when no real graph/source image exists - there is no "photo
  required but missing" state for DATA to begin with.
- `media_research_timeout_seconds` (S13): bounds `MediaResearchService.research()` in
  `asyncio.wait_for()` - a real network-bound external discovery call must never hang the whole
  cycle. A timeout becomes `MEDIA_RESEARCH_TIMEOUT`, never a silent hang or an uncaught exception.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Awaitable, Protocol
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from services.editorial_pipeline.recovery_service import RecoveryService

from schemas.media_intent import MediaIntent
from schemas.media_subject_match import MediaSelectionResult, ResolvedMediaCandidate
from services.editorial_pipeline.composition import build_composition_plan
from services.editorial_pipeline.content import build_structured_data_content, build_structured_quote_content
from services.editorial_pipeline.contracts import (
    CompositionPlan,
    DeliveryPackage,
    EvidencePack,
    OrchestratorVerdict,
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

DEFAULT_MEDIA_RESEARCH_TIMEOUT_SECONDS = 8.0
"""S13: a bounded ceiling on `MediaResearchService.research()` - generous enough for the default,
zero-network `NullWebDiscoveryClient` path (effectively instant) while still genuinely bounding a
real `WebDiscoveryClient` in a future phase that wires one in."""

_TERMINAL_ONLY_REASON_CODES = frozenset({RecoveryReasonCode.QUALITY_GATE_FAILED})
"""S5/S21: a quality/safety verdict does not change on a blind retry of unchanged content - these
reason codes always get `max_attempts=1` (terminal on first failure, via the SAME real state
machine, never a special-cased second code path) and always map to `OrchestratorVerdict.BLOCK`,
never `RETRY`."""


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
    verdict: OrchestratorVerdict = OrchestratorVerdict.READY
    persisted_recovery_job_id: UUID | None = None
    """Set only when `session`/`recovery_service` were supplied and a recovery path fired - the
    durable `recovery_jobs.id` a future cycle/human can look up. `None` for READY, and `None` for
    the in-process-only fallback (no session supplied)."""
    next_retry_at: datetime | None = None

    @property
    def is_ready(self) -> bool:
        return self.delivery_package is not None


async def _recover(
    *, content_draft_id: UUID, platform: Platform, reason_code: RecoveryReasonCode, failed_stage: str,
    last_error: str | None = None, candidate_diagnostics: tuple[str, ...] = (),
    session: "AsyncSession | None" = None, recovery_service: "RecoveryService | None" = None,
) -> PipelineResult:
    """The one place every failure path below routes through - decides, once, whether this is the
    durable (S9/S20) or in-process-only (pre-cutover, back-compat) path, and what `OrchestratorVerdict`
    the caller sees. `QUALITY_GATE_FAILED` is always terminal-on-first-failure (`max_attempts=1`) and
    always `BLOCK`; every other reason code here is bounded-retryable (`RecoveryService.
    DEFAULT_MAX_ATTEMPTS`) and maps to `RETRY` while still open, `HOLD` once `TERMINAL_HOLD`."""
    is_terminal_only = reason_code in _TERMINAL_ONLY_REASON_CODES

    if session is not None and recovery_service is not None:
        from services.editorial_pipeline.recovery_service import DEFAULT_MAX_ATTEMPTS

        row = await recovery_service.create_or_retry(
            session, content_draft_id=content_draft_id, platform=platform, reason_code=reason_code,
            failed_stage=failed_stage, last_error=last_error, candidate_diagnostics=list(candidate_diagnostics),
            max_attempts=1 if is_terminal_only else DEFAULT_MAX_ATTEMPTS,
        )
        job = RecoveryJob(
            content_draft_id=content_draft_id, reason_code=reason_code, failed_stage=failed_stage,
            attempt_count=row.attempt_count, max_attempts=row.max_attempts, last_error=last_error,
            candidate_diagnostics=candidate_diagnostics,
        )
        if is_terminal_only:
            verdict = OrchestratorVerdict.BLOCK
        elif row.state.value == "TERMINAL_HOLD":
            verdict = OrchestratorVerdict.HOLD
        else:
            verdict = OrchestratorVerdict.RETRY
        logger.info(
            "pipeline_finished",
            extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": reason_code.value, "verdict": verdict.value},
        )
        logger.info(
            "unified_orchestrator_finished",
            extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": reason_code.value, "verdict": verdict.value},
        )
        return PipelineResult(
            delivery_package=None, recovery_job=job, verdict=verdict,
            persisted_recovery_job_id=row.id, next_retry_at=row.next_retry_at,
        )

    # In-process-only fallback (no durable session supplied) - byte-identical to pre-cutover
    # behavior for every caller that has not been updated (shadow.py, this module's own
    # pre-existing test suite).
    job = create_recovery_job(
        content_draft_id=content_draft_id, reason_code=reason_code, failed_stage=failed_stage,
        last_error=last_error, candidate_diagnostics=candidate_diagnostics,
    )
    verdict = OrchestratorVerdict.BLOCK if is_terminal_only else OrchestratorVerdict.HOLD
    logger.info(
        "pipeline_finished",
        extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": job.reason_code.value, "verdict": verdict.value},
    )
    logger.info(
        "unified_orchestrator_finished",
        extra={"content_draft_id": str(content_draft_id), "outcome": "recovery", "reason": job.reason_code.value, "verdict": verdict.value},
    )
    return PipelineResult(delivery_package=None, recovery_job=job, verdict=verdict)


async def run_editorial_production_pipeline(
    *, content_draft_id: UUID, presentation_format: PresentationFormat, title: str, main_body: str | None,
    evidence: EvidencePack, platform: Platform, render: RenderCallable,
    quote_candidate: QuoteCandidate | None = None,
    visual_intent: MediaIntent | None = None, tier1_candidates: list[ResolvedMediaCandidate] | None = None,
    web_discovery_client: WebDiscoveryClient | None = None,
    subject_match_classifier: SubjectMatchClassifier | None = None,
    fallback_candidate: ResolvedMediaCandidate | None = None,
    media_research_service: MediaResearchService | None = None,
    session: "AsyncSession | None" = None,
    recovery_service: "RecoveryService | None" = None,
    require_media: bool = False,
    media_research_timeout_seconds: float = DEFAULT_MEDIA_RESEARCH_TIMEOUT_SECONDS,
) -> PipelineResult:
    """The one call site a thin worker entrypoint needs (S25). Every stage below logs its own
    named diagnostic event (S32) with `content_draft_id` as the stable correlating id."""
    logger.info("unified_orchestrator_started", extra={"content_draft_id": str(content_draft_id), "presentation_format": presentation_format.value})
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
    try:
        media_selection: MediaSelectionResult = await asyncio.wait_for(
            service.research(
                intent, tier1_candidates=tier1_candidates, web_discovery_client=web_discovery_client,
                subject_match_classifier=subject_match_classifier, fallback_candidate=fallback_candidate,
            ),
            timeout=media_research_timeout_seconds,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "media_research_timed_out",
            extra={"content_draft_id": str(content_draft_id), "timeout_seconds": media_research_timeout_seconds},
        )
        return await _recover(
            content_draft_id=content_draft_id, platform=platform, reason_code=RecoveryReasonCode.MEDIA_RESEARCH_TIMEOUT,
            failed_stage="media_research", last_error=f"media research exceeded {media_research_timeout_seconds}s",
            session=session, recovery_service=recovery_service,
        )
    for reason in media_selection.rejection_reasons:
        logger.info("media_candidate_rejected", extra={"content_draft_id": str(content_draft_id), "reason": reason})
    if media_selection.selected is not None:
        logger.info(
            "media_selected",
            extra={"content_draft_id": str(content_draft_id), "candidate_id": media_selection.selected.candidate_id, "score": media_selection.selected_score},
        )

    # --- S13: require_media - a NEWS/BREAKING/QUOTE post structurally requires a truthful photo
    # (mirrors the real, currently-deployed worker invariant - see this function's own module
    # docstring). DATA never reaches this check: DATA_TYPOGRAPHIC (composition.py) is its own
    # legitimate no-media outcome, decided by build_composition_plan() below, not here - so this
    # check runs BEFORE composition only for the three formats that have no such escape hatch.
    if require_media and presentation_format != PresentationFormat.DATA and media_selection.selected is None:
        logger.info(
            "no_suitable_media",
            extra={"content_draft_id": str(content_draft_id), "presentation_format": presentation_format.value},
        )
        return await _recover(
            content_draft_id=content_draft_id, platform=platform, reason_code=RecoveryReasonCode.NO_SUITABLE_MEDIA,
            failed_stage="media_research", candidate_diagnostics=tuple(media_selection.rejection_reasons),
            session=session, recovery_service=recovery_service,
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
        return await _recover(
            content_draft_id=content_draft_id, platform=platform, reason_code=RecoveryReasonCode.RENDER_FAILED,
            failed_stage="render", session=session, recovery_service=recovery_service,
        )
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
            return await _recover(
                content_draft_id=content_draft_id, platform=platform, reason_code=RecoveryReasonCode.CAPTION_BUDGET_FAILED,
                failed_stage="caption_budget", session=session, recovery_service=recovery_service,
            )
        caption_or_copy = caption_plan.caption or caption_or_copy

    # --- quality gate (S21) ---
    gate_result = run_quality_gate(
        content=structured_content, evidence=evidence, media_selection=media_selection,
        caption_or_copy=caption_or_copy, platform=platform,
    )
    logger.info("quality_gate_result", extra={"content_draft_id": str(content_draft_id), "verdict": gate_result.verdict.value})

    if gate_result.verdict.value != "READY":
        return await _recover(
            content_draft_id=content_draft_id, platform=platform, reason_code=RecoveryReasonCode.QUALITY_GATE_FAILED,
            failed_stage="quality_gate", candidate_diagnostics=tuple(c.reason for c in gate_result.failed_checks),
            session=session, recovery_service=recovery_service,
        )

    package = DeliveryPackage(
        platform=platform, presentation_format=presentation_format, composition_plan=composition_plan,
        quality_gate_result=gate_result, caption_or_copy=caption_or_copy,
    )
    logger.info("delivery_package_ready", extra={"content_draft_id": str(content_draft_id)})
    logger.info("pipeline_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "ready"})
    logger.info("unified_orchestrator_finished", extra={"content_draft_id": str(content_draft_id), "outcome": "ready", "verdict": OrchestratorVerdict.READY.value})
    return PipelineResult(delivery_package=package, recovery_job=None, verdict=OrchestratorVerdict.READY)
