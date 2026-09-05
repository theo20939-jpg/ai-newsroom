"""MEME PRODUCTION PIPELINE (overnight phase): the ONE convergence seam for both the AUTOMATIC
and MANUAL meme-generation triggers.

Mirrors `services/telegraph_research_processor.py::process_approved_telegraph_proposal()`'s own
established shape almost exactly (claim/create -> run WorkflowRunner -> report an inspectable
outcome), extended with the post-workflow stages Telegraph's own article pipeline doesn't need:
image generation, watermarking, and Telegram delivery.

Pipeline (both triggers converge into this ONE function immediately after the trigger-specific
gating below):

    resolve NewsEvent
    -> debounce check (in-progress MEME_GENERATION task for this event blocks a new one)
    -> automatic-only: meme-worthiness gate (bypassed entirely for a manual trigger)
    -> EditorialTask(MEME_GENERATION) -> WorkflowRunner (research -> intelligence -> meme_concept
       -> meme_copywriting, reusing the exact same Capability Framework every other workflow uses)
    -> MemeCandidateService.create_from_concept()
    -> safety/originality gate (BOTH triggers - a human's explicit request never bypasses safety)
    -> attach_copy()
    -> image generation (services/meme_image_generation.py, unmodified)
    -> render (services/meme_render.py, unmodified) + mandatory NNJ watermark
       (services/meme_watermark.py) - a watermark failure is a hard generation failure, never a
       "deliver anyway" fallback
    -> attach_render_result()
    -> Telegram delivery to EditorialDestination.MEME ONLY (services/meme_preview_notifier.py)

Debounce/idempotency (MEME PRODUCTION PIPELINE §13): deliberately does NOT reuse
`services/workflow_service.py::create_task()`'s own duplicate-active-task guard - that guard
blocks a second task for the same (event_id, workflow_type) regardless of the first one's status
(Phase 15 M1's own explicit "matches any TaskStatus, not only CREATED/RUNNING" fix, correct for
NEWS_ANALYSIS's own "exactly once, ever" semantic but wrong here: a COMPLETED or FAILED prior meme
task must NOT block a later intentional variant). This module implements its OWN, narrower check
(`_find_in_progress_meme_task()`, non-terminal statuses only) and its OWN task-row construction
(`_create_meme_generation_task()`, mirroring `create_task()`'s internals) rather than touching that
shared, foundational function's cross-cutting behavior for every other workflow type in this
codebase.
"""
from __future__ import annotations

import hashlib
import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from aiogram import Bot
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import NewsEvent
from integrations.llm_gateway.image_protocol import ImageGenerationGateway
from integrations.storage.image_storage import ImageStorage, StorageError
from schemas.meme_concept import MemeConcept
from schemas.meme_copy import MemeCopy
from schemas.meme_image import MemeImageStatus
from schemas.meme_preview import MemePreviewCard
from schemas.meme_render import MemeRenderStatus
from schemas.meme_safety import MemeGateDecision
from schemas.workflow import WorkflowExecutionState, WorkflowType
from services.cost_tracker import CostTracker
from services.meme_candidate_service import MemeCandidateService
from services.meme_image_generation import generate_meme_image
from services.meme_opportunity import MemeOpportunityDecision, assess_meme_opportunity
from services.meme_preview_notifier import MemePreviewOutcome, send_meme_preview
from services.meme_preview_summary import build_safety_summary
from services.meme_render import render_meme
from services.meme_safety import assess_meme_safety_and_originality
from services.meme_watermark import MemeWatermarkError, apply_nnj_watermark
from services.pricing_catalog import PricingCatalog
from workflows.registry import registry as default_registry
from workflows.runner import WorkflowRunner

logger = logging.getLogger(__name__)

TriggerSource = Literal["automatic", "manual"]

_NON_TERMINAL_TASK_STATUSES = frozenset({TaskStatus.CREATED, TaskStatus.RUNNING, TaskStatus.WAITING})

MemeGenerationStatus = Literal[
    "event_not_found", "already_in_progress", "not_meme_worthy", "provider_not_configured",
    "concept_generation_failed", "safety_blocked", "copy_validation_failed", "image_generation_failed",
    "render_failed", "watermark_failed", "delivered", "delivery_failed",
]

# MEME-PROD-1B: mirrors schemas/meme_copy.py's own `_ALT_TEXT_MAX_LENGTH` constraint exactly -
# duplicated locally rather than importing that module-private constant, matching this codebase's
# own established per-module-private-constant convention (e.g. services/article_metadata.py's own
# independently-defined `_MAX_ALT_TEXT_LENGTH`, services/cleaning.py's own `_truncate()`).
_ALT_TEXT_MAX_LENGTH = 200
# A stray combining mark, variation selector, or zero-width-joiner half left at the very end of a
# hard truncation would render as a visibly broken glyph - trimmed defensively before falling back
# to a word-boundary cut. `‍` (ZWJ) and `️`/`︎` (variation selectors) are the most
# common offenders in real LLM output (emoji sequences); combining marks are covered generically
# via `unicodedata.combining()`.
_ALT_TEXT_DANGLING_MARKS = frozenset({"‍", "️", "︎"})
# Trailing punctuation that reads as visibly "cut off mid-sentence" once a hard truncation lands on
# it - deliberately NOT including sentence-final punctuation ("." "!" "?" closing quotes/brackets),
# which are legitimate, complete endings a word-boundary cut may land on by coincidence.
_ALT_TEXT_DANGLING_PUNCTUATION = " \t\n,;:–—-("


def _normalize_alt_text(alt_text: str) -> str:
    """§3's own explicit contract: shorten an over-length `alt_text` to `_ALT_TEXT_MAX_LENGTH`
    without ever truncating a UTF-8 byte sequence in half (a Python `str` is already a sequence of
    Unicode codepoints, never raw bytes - plain slicing can never split one apart) and without
    leaving a broken trailing whitespace/punctuation/grapheme fragment where a word-boundary cut
    can reasonably avoid it. Never touches any other `MemeCopy` field - alt_text is the only field
    this production incident implicated, and the brief's own "do not alter meme concept/caption/
    text unless required" instruction forbids normalizing anything else defensively."""
    if len(alt_text) <= _ALT_TEXT_MAX_LENGTH:
        return alt_text
    truncated = alt_text[:_ALT_TEXT_MAX_LENGTH]
    while truncated and (unicodedata.combining(truncated[-1]) or truncated[-1] in _ALT_TEXT_DANGLING_MARKS):
        truncated = truncated[:-1]
    last_space = truncated.rfind(" ")
    if last_space > 0:
        truncated = truncated[:last_space]
    truncated = truncated.rstrip(_ALT_TEXT_DANGLING_PUNCTUATION)
    return truncated or alt_text[:_ALT_TEXT_MAX_LENGTH]  # never collapse to an empty string


# MEME-PROD-2.1: product localization requirement - meme overlay text (top_text/bottom_text,
# rendered directly onto the image by services/meme_render.py) must always be Russian
# (prompts/meme_copywriting/v1.yaml's own rule). The prompt is the primary defense; this is the
# deterministic backstop that actually enforces it, mirroring _normalize_alt_text()'s own
# established "prompt says it, code enforces it" precedent from the MEME-PROD-1B incident. Only
# top_text/bottom_text are checked - telegram_caption, editor_explanation, and every other field
# are explicitly untouched (brief's own scope limit).
_CYRILLIC_PATTERN = re.compile(r"[Ѐ-ӿ]")


def _meme_overlay_text_is_russian(copy: MemeCopy) -> bool:
    """A simple presence check (at least one Cyrillic codepoint), not a full language classifier -
    good enough to catch the actual production incident (fully English captions like "Automation:
    allegedly seamless") without misflagging legitimate Russian text that borrows a Latin-script
    brand name or acronym (e.g. "IP", "NNJ") inline, which real Russian tech-culture meme text
    routinely does per the prompt's own rule.

    MEME-PROD-4: `copy.panel_texts` (the 4-quadrant panel_count==4 shape) is checked entry-by-entry
    when present - `copy.top_text` alone (equal to `panel_texts[0]` for that shape, per prompts/
    meme_copywriting/v2.yaml's own contract) would otherwise leave panels 2-4 completely
    unchecked. `bottom_text` is always null for that shape (same contract) so its own check below
    is simply skipped, same as it already is whenever bottom_text is absent for the classic shape."""
    if not _CYRILLIC_PATTERN.search(copy.top_text):
        return False
    if copy.bottom_text and not _CYRILLIC_PATTERN.search(copy.bottom_text):
        return False
    if copy.panel_texts and not all(_CYRILLIC_PATTERN.search(text) for text in copy.panel_texts):
        return False
    return True


@dataclass(frozen=True)
class MemeGenerationOutcome:
    status: MemeGenerationStatus
    news_event_id: UUID
    task_id: UUID | None = None
    candidate_id: UUID | None = None
    error: str | None = None


def _extract_step_result(task: EditorialTask, step_name: str) -> dict | None:
    """Byte-for-byte the same extraction shape this codebase's own Telegraph/handler modules
    already duplicate independently (bot/handlers/telegraph_article_review.py::
    _extract_article_result(), services/telegraph_publish_orchestrator.py's own identical copy) -
    per this codebase's established per-module-private-helper convention."""
    for step_result in (task.workflow or {}).get("step_results", []):
        if step_result.get("step_name") == step_name and step_result.get("status") == "SUCCESS":
            result = step_result.get("result")
            return result if isinstance(result, dict) else None
    return None


async def _find_in_progress_meme_task(session: AsyncSession, news_event_id: UUID) -> EditorialTask | None:
    """Returns the most-recently-created MEME_GENERATION task for this event IF it is still
    non-terminal (CREATED/RUNNING/WAITING) - `None` otherwise, including when the most recent one
    already reached COMPLETED/FAILED (a later intentional trigger is then free to create a new,
    independent task/variant). See module docstring for why this is deliberately NOT
    `services.workflow_service._find_active_task()`'s own any-status check."""
    result = await session.execute(
        select(EditorialTask)
        .where(EditorialTask.event_id == news_event_id)
        .order_by(EditorialTask.created_at.desc())
    )
    for task in result.scalars().all():
        if task.workflow is not None and task.workflow.get("workflow_name") == WorkflowType.MEME_GENERATION.value:
            return task if task.status in _NON_TERMINAL_TASK_STATUSES else None
    return None


async def _create_meme_generation_task(
    session: AsyncSession, *, news_event_id: UUID, priority: TaskPriority,
) -> EditorialTask:
    """Mirrors `services.workflow_service.create_task()`'s own internal EditorialTask
    construction exactly, MINUS that function's any-status duplicate-task guard (module docstring
    explains why this workflow type needs different semantics) - the caller
    (`trigger_meme_generation()`) has already performed its own, correct in-progress check via
    `_find_in_progress_meme_task()` before ever calling this."""
    definition = default_registry.resolve(WorkflowType.MEME_GENERATION)
    state = WorkflowExecutionState(
        workflow_name=definition.name,
        workflow_version=definition.version,
        current_step=definition.steps[0].name,
        completed_steps=[],
        iteration_count=0,
        step_results=[],
        failure=None,
    )
    task = EditorialTask(
        event_id=news_event_id, priority=priority, workflow=state.model_dump(mode="json"),
        status=TaskStatus.CREATED, retry_count=0,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)
    return task


def _resolve_default_image_gateway() -> ImageGenerationGateway | None:
    """Constructs the `image_gateway` that `trigger_meme_generation()` uses when a caller does not
    inject one explicitly - test injection (every test in tests/test_meme_generation_orchestrator.py
    passes `image_gateway=MockImageAdapter()` explicitly) is completely unaffected by this
    function; it only governs the two real production call sites' own implicit default
    (`worker/content_cycle.py`'s automatic trigger, `bot/handlers/meme_generate.py`'s manual
    trigger), neither of which passes `image_gateway` today.

    mode="off"/"dry_run": always `MockImageAdapter` - zero network, zero cost, matches this
    orchestrator's pre-existing behavior byte-for-byte (`dry_run` means "exercise the real
    generate/store/render/watermark pipeline shape safely," never "call a paid provider").

    mode="enforce": constructs the real `OpenAIImageAdapter` (MEME-PROD-2 - real production
    diagnostics proved `gemini-3.1-flash-image` returns HTTP 400 "Unable to show the generated
    image... blocked for unspecified reasons" for real editorial meme prompts, even though a
    minimal request succeeds; rather than building a growing Gemini-specific prompt-rewrite/
    policy-recovery subsystem, the product decision was to replace the provider). Reuses
    `settings.openai_api_key` - the SAME already-configured credential the real, working text
    LLMGateway calls already use in production (confirmed live via MEME-PROD-1B's own production
    evidence: "OpenAI /v1/responses returned HTTP 200") - never a second, meme-specific secret.
    `settings.openai_api_key` absent -> returns `None` (never `MockImageAdapter`), mirroring
    `services/editorial_recomposition.py::maybe_recompose()`'s own fail-closed-on-missing-key
    pattern exactly, so the caller can fail closed rather than silently downgrading a paid-mode
    request to a placeholder image. `GeminiImageAdapter` remains fully intact and used elsewhere
    (`editorial_recomposition.py`'s own live NEWS photo recomposition path) - this function is the
    ONLY place MEME image generation's own provider choice lives; nothing else changes."""
    from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter

    if settings.meme_image_generation_mode != "enforce":
        return MockImageAdapter()

    api_key = settings.openai_api_key.get_secret_value() if settings.openai_api_key else None
    if not api_key:
        return None

    from integrations.llm_gateway.providers.openai_image_adapter import OpenAIImageAdapter

    return OpenAIImageAdapter(api_key=api_key)


def _card_from_result(
    candidate_id: UUID, event: NewsEvent, copy: MemeCopy, *, image_storage_key: str | None,
    safety_summary: str,
) -> MemePreviewCard:
    return MemePreviewCard(
        candidate_id=candidate_id,
        news_title=event.title,
        news_url=event.url,
        news_category=event.category.value,
        top_text=copy.top_text,
        bottom_text=copy.bottom_text,
        telegram_caption=copy.telegram_caption,
        editor_explanation=copy.editor_explanation,
        alt_text=copy.alt_text,
        image_storage_key=image_storage_key,
        safety_summary=safety_summary,
        # M7's quality gate is not wired into this orchestrator tonight (out of scope for this
        # phase - opportunity + safety gating and delivery were the required stages; see this
        # module's own report for the exact disclosure) - a static, honest label, never a
        # fabricated assessment.
        quality_summary="Quality: not assessed",
    )


async def trigger_meme_generation(
    session: AsyncSession,
    *,
    news_event_id: UUID,
    trigger_source: TriggerSource,
    capability_registry,
    storage: ImageStorage,
    bot: Bot,
    image_gateway: ImageGenerationGateway | None = None,
    cost_tracker: CostTracker | None = None,
    pricing_catalog: PricingCatalog | None = None,
) -> MemeGenerationOutcome:
    """The one entry point both `worker/content_cycle.py` (automatic) and
    `bot/handlers/meme_generate.py` (manual) call. Never raises for an ordinary gating/failure
    outcome (`MemeGenerationOutcome.status` reports it instead) - only a genuine, unexpected
    infrastructure error (a DB error, a programming bug) propagates, exactly like every other
    orchestration function in this codebase (`process_approved_telegraph_proposal()`,
    `publish_approved_telegraph_article()`).

    `image_gateway` defaults to `None`, in which case `_resolve_default_image_gateway()` constructs
    the real gateway HERE (never in a caller) - deliberately so that neither
    `worker/content_cycle.py` nor `bot/handlers/meme_generate.py` ever needs to import anything
    from `integrations.llm_gateway.*` directly. `worker/content_cycle.py` in particular has an
    established structural test (`test_i_content_cycle_module_imports_no_llm_gateway_or_
    capability_execution`) forbidding ANY import referencing `llm_gateway`/`capabilities.executor`
    anywhere in that file, even a local/deferred one - this module is where that boundary is
    respected on the automatic path's behalf.

    "REAL IMAGE PROVIDER FINALIZATION" phase: `_resolve_default_image_gateway()` returns
    `MockImageAdapter` for `settings.meme_image_generation_mode` "off"/"dry_run" (unchanged), and
    the real, production-proven `GeminiImageAdapter` for "enforce" - but only when
    `settings.gemini_api_key` is actually configured. If "enforce" is set with no key, that
    resolver returns `None` and this function FAILS CLOSED (`status="provider_not_configured"`)
    rather than silently falling back to `MockImageAdapter` - a paid-mode request must never
    silently deliver a placeholder image as if it were real."""
    if image_gateway is None:
        image_gateway = _resolve_default_image_gateway()
        if image_gateway is None:
            logger.error(
                "meme_image_provider_not_configured",
                extra={"news_event_id": str(news_event_id), "mode": settings.meme_image_generation_mode},
            )
            return MemeGenerationOutcome(status="provider_not_configured", news_event_id=news_event_id)

    event = await session.get(NewsEvent, news_event_id)
    if event is None:
        return MemeGenerationOutcome(status="event_not_found", news_event_id=news_event_id)

    in_progress = await _find_in_progress_meme_task(session, news_event_id)
    if in_progress is not None:
        logger.info(
            "meme_generation_already_in_progress",
            extra={"news_event_id": str(news_event_id), "task_id": str(in_progress.id), "trigger_source": trigger_source},
        )
        return MemeGenerationOutcome(status="already_in_progress", news_event_id=news_event_id, task_id=in_progress.id)

    if trigger_source == "automatic":
        # MANUAL requests bypass this gate entirely (module docstring, MEME PRODUCTION PIPELINE
        # §14's own explicit requirement) - an editor's explicit request is never second-guessed
        # by the same heuristic that exists to avoid pestering them with low-signal candidates.
        assessment = assess_meme_opportunity(
            event.title, event.content, event.category, event.published_at, research_output={},
        )
        logger.info(
            "meme_auto_candidate_selected" if assessment.decision == MemeOpportunityDecision.MEME_READY
            else "meme_auto_candidate_rejected",
            extra={
                "news_event_id": str(news_event_id), "decision": assessment.decision.value,
                "composite_score": assessment.signals.composite_score, "mode": settings.meme_opportunity_mode,
            },
        )
        if settings.meme_opportunity_mode == "enforce" and assessment.decision != MemeOpportunityDecision.MEME_READY:
            return MemeGenerationOutcome(status="not_meme_worthy", news_event_id=news_event_id)
    else:
        logger.info("meme_manual_requested", extra={"news_event_id": str(news_event_id)})

    task = await _create_meme_generation_task(session, news_event_id=news_event_id, priority=(
        TaskPriority.B if trigger_source == "manual" else TaskPriority.C
    ))
    logger.info(
        "meme_generation_started",
        extra={"news_event_id": str(news_event_id), "task_id": str(task.id), "trigger_source": trigger_source},
    )

    from capabilities.executor import CapabilityExecutor  # local import: avoids a capabilities<->services

    executor = CapabilityExecutor(
        session, task.id, capability_registry, cost_tracker=cost_tracker, pricing_catalog=pricing_catalog,
    )
    runner = WorkflowRunner(executor)
    await runner.run(session, task.id)

    refreshed_task = await session.get(EditorialTask, task.id)
    assert refreshed_task is not None
    task = refreshed_task
    concept_output = _extract_step_result(task, "meme_concept")
    if concept_output is None:
        logger.warning("meme_concept_ready_failed", extra={"news_event_id": str(news_event_id), "task_id": str(task.id)})
        return MemeGenerationOutcome(status="concept_generation_failed", news_event_id=news_event_id, task_id=task.id)

    concept = MemeConcept.model_validate(concept_output)
    logger.info(
        "meme_concept_ready",
        extra={"news_event_id": str(news_event_id), "task_id": str(task.id), "meme_format": concept.meme_format},
    )

    candidate_service = MemeCandidateService(session)
    candidate = await candidate_service.create_from_concept(
        news_event_id=news_event_id, editorial_task_id=task.id, concept=concept,
    )

    gate_result = assess_meme_safety_and_originality(concept, event.title)
    await candidate_service.attach_safety_assessment(candidate.id, gate_result)
    safety_mode = settings.meme_safety_gate_mode
    if safety_mode in ("shadow", "enforce") and gate_result.gate_decision == MemeGateDecision.BLOCK:
        logger.info(
            "meme_safety_blocked" if safety_mode == "enforce" else "meme_safety_blocked_shadow_only",
            extra={"news_event_id": str(news_event_id), "candidate_id": str(candidate.id), "reason_codes": gate_result.safety.reason_codes},
        )
        if safety_mode == "enforce":
            return MemeGenerationOutcome(status="safety_blocked", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id)

    copy_output = _extract_step_result(task, "meme_copywriting")
    if copy_output is None:
        logger.warning("meme_copy_generation_failed", extra={"candidate_id": str(candidate.id)})
        return MemeGenerationOutcome(status="concept_generation_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id)

    # MEME-PROD-1B: production canary evidence - the LLM has emitted alt_text past the schema's
    # own 200-char ceiling despite the (now also schema-constrained, prompts/meme_copywriting/
    # v1.yaml) contract. alt_text is an optional accessibility description, never load-bearing for
    # the meme itself - proactively normalizing it here, before validation, lets a request that
    # would otherwise be a total loss continue exactly as if the LLM had stayed in bounds. Every
    # other field is left completely untouched (brief's own "do not alter... unless required").
    raw_alt_text = copy_output.get("alt_text") if isinstance(copy_output, dict) else None
    if isinstance(raw_alt_text, str) and len(raw_alt_text) > _ALT_TEXT_MAX_LENGTH:
        copy_output = {**copy_output, "alt_text": _normalize_alt_text(raw_alt_text)}
        logger.warning(
            "meme_copy_alt_text_normalized",
            extra={
                "candidate_id": str(candidate.id), "original_length": len(raw_alt_text),
                "normalized_length": len(copy_output["alt_text"]),
            },
        )

    try:
        copy = MemeCopy.model_validate(copy_output)
    except ValidationError as exc:
        # Expected content-validation failure (a malformed LLM output, not an infrastructure/
        # programming error) - handled at this exact seam, per the brief's own instruction, never
        # swallowed broadly. The candidate row simply stays at whatever status attach_safety_
        # assessment() already left it (schemas.meme_candidate has no dedicated "copy invalid"
        # status - adding one would need a migration, out of this fix's scope) - inspectable via
        # its own missing copy_data, never silently lost.
        logger.warning(
            "meme_copy_validation_failed",
            extra={"candidate_id": str(candidate.id), "error_count": exc.error_count()},
        )
        return MemeGenerationOutcome(
            status="copy_validation_failed", news_event_id=news_event_id, task_id=task.id,
            candidate_id=candidate.id, error=f"{exc.error_count()} validation error(s)",
        )

    if not _meme_overlay_text_is_russian(copy):
        # MEME-PROD-2.1: same rejection outcome as a structural ValidationError above - a
        # copywriting response is not usable if it violates the mandatory language rule, and this
        # codebase has no dedicated "wrong language" status (schemas.meme_candidate) to add
        # without a migration, out of this fix's narrow scope.
        logger.warning(
            "meme_copy_text_not_russian",
            extra={"candidate_id": str(candidate.id), "top_text": copy.top_text, "bottom_text": copy.bottom_text},
        )
        return MemeGenerationOutcome(
            status="copy_validation_failed", news_event_id=news_event_id, task_id=task.id,
            candidate_id=candidate.id, error="meme overlay text (top_text/bottom_text) must be Russian",
        )

    updated_candidate = await candidate_service.attach_copy(candidate.id, copy)
    assert updated_candidate is not None
    candidate = updated_candidate

    logger.info("meme_image_generation_started", extra={"candidate_id": str(candidate.id)})
    image_mode: Literal["off", "dry_run"] = "off" if settings.meme_image_generation_mode == "off" else "dry_run"
    image_result = await generate_meme_image(concept, gateway=image_gateway, storage=storage, mode=image_mode)
    updated_candidate = await candidate_service.attach_image_result(candidate.id, image_result)
    assert updated_candidate is not None
    candidate = updated_candidate
    if image_result.status != MemeImageStatus.GENERATED:
        logger.warning(
            "meme_image_generation_failed",
            extra={"candidate_id": str(candidate.id), "error_code": image_result.error_code},
        )
        return MemeGenerationOutcome(status="image_generation_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id, error=image_result.error_code)

    assert image_result.storage_key is not None
    try:
        source_image_bytes = storage.read(image_result.storage_key)
    except (StorageError, OSError) as exc:
        logger.warning("meme_render_failed", extra={"candidate_id": str(candidate.id), "error": repr(exc)})
        return MemeGenerationOutcome(status="render_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id, error=repr(exc))

    render_result = render_meme(source_image_bytes, copy, storage=storage)
    if render_result.status != MemeRenderStatus.RENDERED:
        logger.warning("meme_render_failed", extra={"candidate_id": str(candidate.id), "error_code": render_result.error_code})
        return MemeGenerationOutcome(status="render_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id, error=render_result.error_code)

    assert render_result.storage_key is not None
    try:
        rendered_bytes = storage.read(render_result.storage_key)
        watermarked_bytes = apply_nnj_watermark(rendered_bytes, copy=copy)
        watermarked_sha256 = hashlib.sha256(watermarked_bytes).hexdigest()
        watermarked_stored = storage.store_validated_image(
            watermarked_bytes, sha256=watermarked_sha256, image_format="PNG", max_bytes=settings.meme_image_max_bytes,
        )
    except (MemeWatermarkError, StorageError, OSError) as exc:
        logger.warning("meme_watermark_failed", extra={"candidate_id": str(candidate.id), "error": repr(exc)})
        return MemeGenerationOutcome(status="watermark_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id, error=repr(exc))

    final_render_result = render_result.model_copy(update={"storage_key": watermarked_stored.storage_key})
    updated_candidate = await candidate_service.attach_render_result(candidate.id, final_render_result)
    assert updated_candidate is not None
    candidate = updated_candidate
    logger.info("meme_watermark_applied", extra={"candidate_id": str(candidate.id), "storage_key": watermarked_stored.storage_key})

    card = _card_from_result(
        candidate.id, event, copy, image_storage_key=watermarked_stored.storage_key,
        safety_summary=build_safety_summary(gate_result),
    )
    preview_mode = settings.meme_telegram_preview_mode
    delivery: MemePreviewOutcome = await send_meme_preview(
        bot, storage, card, dry_run=(preview_mode != "enforce"),
    )
    if delivery.sent:
        logger.info("meme_delivery_sent", extra={"candidate_id": str(candidate.id), "chat_id": delivery.chat_id})
        return MemeGenerationOutcome(status="delivered", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id)

    logger.warning("meme_delivery_failed", extra={"candidate_id": str(candidate.id), "reason": delivery.reason})
    return MemeGenerationOutcome(
        status="delivery_failed", news_event_id=news_event_id, task_id=task.id, candidate_id=candidate.id, error=delivery.reason,
    )
