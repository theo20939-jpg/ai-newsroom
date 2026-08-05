"""Phase 18 final acceptance - Stage F: complete offline end-to-end pipeline test (docs/
phase18_final_acceptance_offline_e2e_report.md).

Placed flat under `tests/` (not `tests/integration/`) to match this repository's own existing
convention - no `tests/integration/` directory exists anywhere in this codebase; every other test
file, DB-backed or not, lives directly under `tests/`.

Exercises the full brief-specified chain for one candidate, offline (no network, no live LLM/
image-generation/Telegram call anywhere):

    NewsEvent fixture
        -> Meme Opportunity Assessment (M1, pure function)
        -> Meme Concept (M2, MemeConceptCapability + FakeLLMGateway)
        -> MemeCandidate persistence (real Postgres, tests/conftest.py's db_session)
        -> Meme Safety Assessment + Meme Originality Assessment (M3, pure function) + persistence
        -> Meme Copywriting (M4, MemeCopywritingCapability + FakeLLMGateway) + persistence
        -> Meme Visual Specification / MockImageAdapter placeholder generation (M5) + persistence
        -> Deterministic renderer (M6) + persistence
        -> Meme Quality Gate (M7, bounded regeneration) + persistence
        -> Telegram preview payload dry-run (M8, send_meme_preview with a bot double that raises
           on any attribute access)
        -> Human decision persistence (M9, idempotency proven with a duplicate call)
        -> Final candidate reload from DB, asserting the accumulated state

Plus a second, failure-path test: image generation fails -> quality gate can never return
READY_FOR_EDITOR, mirroring the brief's own required failure-path assertions.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.meme_concept_capability import MemeConceptCapability
from capabilities.meme_copywriting_capability import MemeCopywritingCapability
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.meme_candidate import MemeCandidateStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from integrations.llm_gateway.image_protocol import ImageGenerationRequest, ImageGenerationResponse
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.providers.mock_image_adapter import MockImageAdapter
from integrations.storage.image_storage import LocalImageStorage
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from schemas.meme_concept import MemeConcept
from schemas.meme_copy import MemeCopy
from schemas.meme_image import MemeImageStatus
from schemas.meme_preview import MemePreviewCard
from schemas.meme_quality import MemeQualityDecision
from schemas.meme_render import MemeRenderStatus
from schemas.meme_safety import MemeGateDecision
from services.meme_candidate_service import MemeCandidateService
from services.meme_image_generation import generate_meme_image
from services.meme_opportunity import assess_meme_opportunity
from services.meme_preview_notifier import send_meme_preview
from services.meme_quality import apply_regeneration_bounds, assess_meme_quality
from services.meme_render import render_meme
from services.meme_safety import assess_meme_safety_and_originality
from tests.fakes.fake_gateway import FakeLLMGateway

_CONCEPT_OUTPUT = {
    "premise": "An AI company insists AI won't take jobs.",
    "setup": "The CEO reassures workers during a keynote.",
    "punchline": "Meanwhile the CEO's own job is the one AI can't replace.",
    "humor_mechanism": "self_referential_irony",
    "visual_scene": "A CEO on stage pointing at a slide reading 'Jobs are safe'.",
    "characters_objects": ["CEO", "presentation slide"],
    "text_overlay_intent": "Contrast reassurance with public skepticism.",
    "source_fact_links": ["The CEO publicly stated AI is not destroying jobs."],
    "forbidden_interpretations": [],
    "meme_format": "classic_top_bottom",
}

_COPY_OUTPUT = {
    "top_text": "AI WON'T TAKE YOUR JOB",
    "bottom_text": "SAYS GUY WHOSE JOB IS AI",
    "punchline_short": "The one job AI can't replace.",
    "telegram_caption": "From today's keynote - CEO addresses job-loss fears.",
    "editor_explanation": "Plays on the irony of an AI CEO reassuring workers about AI.",
    "alt_text": "A CEO on stage pointing at a slide reading 'Jobs are safe'.",
}


class _NeverCalledBot:
    """Raises on ANY attribute access - the strongest possible proof the dry-run preview path
    never touches Telegram (mirrors tests/test_phase18_m8_meme_telegram_preview.py's identical
    double)."""

    def __getattr__(self, name: str):
        raise AssertionError(f"Bot.{name}() must never be called in this offline pipeline test")


async def _make_event(session: AsyncSession) -> NewsEvent:
    source = NewsSource(name="Pipeline Test Source", type=SourceType.RSS, url="https://example.com/feed.xml", active=True)
    session.add(source)
    await session.flush()
    event = NewsEvent(
        source_id=source.id,
        title="Nvidia CEO insists AI is not destroying jobs",
        content=(
            "The Nvidia chief executive publicly insists that artificial intelligence is not "
            "destroying jobs, addressing growing anxiety among workers during a keynote address."
        ),
        url="https://example.com/article",
        category=EventCategory.AI,
        published_at=datetime.now(timezone.utc),
        hash=f"pipeline-{uuid.uuid4()}",
    )
    session.add(event)
    await session.flush()
    return event


def _real_prompt_repository():
    """Uses the *real*, published prompt files (not hand-rolled fake schemas) - both for realism
    (this offline test proves the real prompt files' own `output_schema` actually round-trips
    through floor-validation with real-shaped structured output) and because a hand-rolled fake
    schema previously used here had a real bug (every field declared `type: string`, including
    the array fields) that only a genuine schema - not a hand-maintained approximation of one -
    reliably avoids."""
    from pathlib import Path

    from integrations.prompts.file_repository import FilePromptRepository

    prompts_root = Path(__file__).resolve().parent.parent / "prompts"
    return FilePromptRepository(prompts_root)


def _capability_context(event: NewsEvent, *, capability_name: str, step_results: dict) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=event.id, title=event.title, summary=None, content=event.content, url=event.url,
                category=event.category.value, published_at=event.published_at,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="meme_generation", workflow_version=1,
                completed_steps=list(step_results.keys()), step_results=step_results,
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid.uuid4(), event_id=event.id, capability_name=capability_name,
            priority=TaskPriority.B, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


@pytest.mark.asyncio
async def test_complete_offline_meme_pipeline_happy_path(db_session: AsyncSession, tmp_path) -> None:
    storage = LocalImageStorage(tmp_path)
    service = MemeCandidateService(db_session)

    # --- NewsEvent fixture ---
    event = await _make_event(db_session)
    task = EditorialTask(event_id=event.id, priority=TaskPriority.B, status=TaskStatus.RUNNING)
    db_session.add(task)
    await db_session.flush()

    # --- M1: Meme Opportunity Assessment ---
    opportunity = assess_meme_opportunity(
        event.title, event.content, event.category, event.published_at, {"facts": [], "gaps": []},
    )
    assert opportunity.decision.value in ("MEME_READY", "REVIEW", "NOT_SUITABLE", "SENSITIVE_BLOCK", "INSUFFICIENT_SOURCE")
    assert opportunity.decision.value != "SENSITIVE_BLOCK"  # this fixture is a clean, safe story

    # --- M2: Meme Concept (real Capability, fake Gateway - no network) ---
    concept_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=dict(_CONCEPT_OUTPUT), finish_reason="stop",
            model_used="fake-concept-model", usage=CapabilityUsage(input_tokens=50, output_tokens=40),
        )
    )
    concept_capability = MemeConceptCapability(concept_gateway, _real_prompt_repository())
    concept_context = _capability_context(event, capability_name="meme_concept", step_results={})
    concept_result = await concept_capability.execute(concept_context)
    assert concept_result.status == "SUCCESS"
    assert len(concept_gateway.received_requests) == 1  # exactly one call, never more
    concept = MemeConcept.model_validate(concept_result.structured_output)
    assert concept.schema_version == "v1"

    # --- MemeCandidate persistence ---
    candidate = await service.create_from_concept(news_event_id=event.id, editorial_task_id=task.id, concept=concept)
    candidate_id = candidate.id
    assert candidate.status == MemeCandidateStatus.CONCEPT_GENERATED

    # --- M3: Safety + Originality Assessment, then persistence ---
    safety_gate = assess_meme_safety_and_originality(concept, event.title)
    assert safety_gate.gate_decision != MemeGateDecision.BLOCK  # this fixture is clean
    candidate = await service.attach_safety_assessment(candidate_id, safety_gate)
    assert candidate is not None
    assert candidate.safety_status == "PASS"

    # --- M4: Meme Copywriting (real Capability, fake Gateway), then persistence ---
    copy_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=dict(_COPY_OUTPUT), finish_reason="stop",
            model_used="fake-copy-model", usage=CapabilityUsage(input_tokens=30, output_tokens=25),
        )
    )
    copywriting_capability = MemeCopywritingCapability(copy_gateway, _real_prompt_repository())
    copy_context = _capability_context(
        event, capability_name="meme_copywriting", step_results={"meme_concept": concept_result.structured_output},
    )
    copy_result = await copywriting_capability.execute(copy_context)
    assert copy_result.status == "SUCCESS"
    assert len(copy_gateway.received_requests) == 1
    copy = MemeCopy.model_validate(copy_result.structured_output)
    candidate = await service.attach_copy(candidate_id, copy)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.COPY_GENERATED

    # --- M5: Image generation via MockImageAdapter (zero network, zero cost), then persistence ---
    image_result = await generate_meme_image(concept, gateway=MockImageAdapter(), storage=storage, mode="dry_run")
    assert image_result.status == MemeImageStatus.GENERATED
    assert image_result.cost_usd == "0"
    candidate = await service.attach_image_result(candidate_id, image_result)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.IMAGE_GENERATED
    await service.add_cost(candidate_id, Decimal(image_result.cost_usd))

    # --- M6: Deterministic renderer, then persistence ---
    image_bytes = storage.read(image_result.storage_key)
    render_result = render_meme(image_bytes, copy, storage=storage)
    assert render_result.status == MemeRenderStatus.RENDERED
    assert render_result.contrast_passed is True
    candidate = await service.attach_render_result(candidate_id, render_result)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.RENDERED

    # --- M7: Quality Gate (bounded regeneration applied even though not needed here) ---
    quality_assessment = assess_meme_quality(
        concept, copy, safety_gate, render_result, image_result, opportunity=opportunity,
    )
    bounded_quality = apply_regeneration_bounds(
        quality_assessment, concept_regeneration_count=candidate.concept_regeneration_count,
        image_regeneration_count=candidate.image_regeneration_count,
    )
    assert bounded_quality.decision == MemeQualityDecision.READY_FOR_EDITOR
    candidate = await service.attach_quality_assessment(candidate_id, bounded_quality)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.PENDING_EDITOR

    # --- M8: Telegram preview payload, dry-run only - proves zero network contact ---
    preview_card = MemePreviewCard(
        candidate_id=candidate_id, news_title=event.title, news_url=event.url,
        news_category=event.category.value, top_text=copy.top_text, bottom_text=copy.bottom_text,
        telegram_caption=copy.telegram_caption, editor_explanation=copy.editor_explanation,
        alt_text=copy.alt_text, image_storage_key=render_result.storage_key,
        safety_summary=f"Safety: {safety_gate.safety.decision.value}",
        quality_summary=f"Quality: {bounded_quality.decision.value}",
    )
    preview_outcome = await send_meme_preview(
        _NeverCalledBot(), 999999, storage, preview_card, dry_run=True,  # type: ignore[arg-type]
    )
    assert preview_outcome.sent is False
    assert preview_outcome.has_image is True
    assert "AI WON'T TAKE YOUR JOB" in preview_outcome.rendered_caption

    # --- M9: Human decision persistence, idempotency proven with a duplicate call ---
    approved = await service.record_editor_decision(candidate_id, "approved")
    assert approved is not None
    assert approved.status == MemeCandidateStatus.APPROVED
    approved_again = await service.record_editor_decision(candidate_id, "approved")
    assert approved_again is not None
    assert approved_again.id == candidate_id  # idempotent, no duplicate row

    # --- Final candidate reload from DB ---
    final = await service.get_by_id(candidate_id)
    assert final is not None
    assert final.news_event_id == event.id  # traceability preserved end to end
    assert final.concept_schema_version == "v1"
    assert final.copy_schema_version == "v1"
    assert final.status == MemeCandidateStatus.APPROVED
    assert final.editor_decision == "approved"
    assert final.published is False  # never auto-published, anywhere in this phase
    assert final.cumulative_cost_usd == Decimal("0.000000")  # mock image cost is real $0, summed exactly once
    assert final.image_storage_key == image_result.storage_key
    assert final.render_storage_key == render_result.storage_key

    summary = await service.build_feedback_summary(candidate_id)
    assert summary is not None
    assert summary.published is False


@pytest.mark.asyncio
async def test_offline_pipeline_sensitive_content_never_reaches_ready_for_editor(
    db_session: AsyncSession, tmp_path,
) -> None:
    """Failure/safety path: a sensitive-content concept must never be quality-gated to
    READY_FOR_EDITOR, regardless of how clean every other signal is."""
    storage = LocalImageStorage(tmp_path)
    service = MemeCandidateService(db_session)
    event = await _make_event(db_session)

    unsafe_concept_output = {
        **_CONCEPT_OUTPUT,
        "punchline": "The victim was shot during the incident, but at least it's funny.",
    }
    concept = MemeConcept.model_validate(unsafe_concept_output)
    candidate = await service.create_from_concept(news_event_id=event.id, editorial_task_id=None, concept=concept)  # type: ignore[arg-type]

    safety_gate = assess_meme_safety_and_originality(concept, event.title)
    assert safety_gate.gate_decision == MemeGateDecision.BLOCK
    candidate = await service.attach_safety_assessment(candidate.id, safety_gate)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.SAFETY_BLOCKED

    copy = MemeCopy.model_validate(_COPY_OUTPUT)
    image_result = await generate_meme_image(concept, gateway=MockImageAdapter(), storage=storage, mode="dry_run")
    image_bytes = storage.read(image_result.storage_key)
    render_result = render_meme(image_bytes, copy, storage=storage)

    quality_assessment = assess_meme_quality(concept, copy, safety_gate, render_result, image_result)
    assert quality_assessment.decision == MemeQualityDecision.REJECT
    bounded = apply_regeneration_bounds(quality_assessment, concept_regeneration_count=0, image_regeneration_count=0)
    assert bounded.decision == MemeQualityDecision.REJECT

    final = await service.attach_quality_assessment(candidate.id, bounded)
    assert final is not None
    assert final.status == MemeCandidateStatus.QUALITY_REJECTED
    assert final.status != MemeCandidateStatus.PENDING_EDITOR  # never reaches editor-ready


@pytest.mark.asyncio
async def test_offline_pipeline_image_generation_failure_blocks_quality_ready(
    db_session: AsyncSession, tmp_path,
) -> None:
    """Failure path: an image-generation failure must route to REGENERATE_IMAGE, never
    READY_FOR_EDITOR, and the bounded-regeneration ceiling must eventually convert repeated
    failures to REJECT rather than looping forever."""
    from services.meme_image_generation import _MAX_GENERATION_ATTEMPTS

    class _AlwaysFailingImageGateway:
        async def generate_image(self, request: ImageGenerationRequest) -> ImageGenerationResponse:
            raise RuntimeError("simulated provider outage")

    storage = LocalImageStorage(tmp_path)
    service = MemeCandidateService(db_session)
    event = await _make_event(db_session)
    concept = MemeConcept.model_validate(_CONCEPT_OUTPUT)
    candidate = await service.create_from_concept(news_event_id=event.id, editorial_task_id=None, concept=concept)  # type: ignore[arg-type]

    safety_gate = assess_meme_safety_and_originality(concept, event.title)
    copy = MemeCopy.model_validate(_COPY_OUTPUT)

    image_result = await generate_meme_image(concept, gateway=_AlwaysFailingImageGateway(), storage=storage, mode="dry_run")
    assert image_result.status == MemeImageStatus.FAILED
    assert image_result.attempt_count == _MAX_GENERATION_ATTEMPTS  # bounded, never unlimited
    candidate = await service.attach_image_result(candidate.id, image_result)
    assert candidate is not None
    assert candidate.status == MemeCandidateStatus.IMAGE_FAILED

    # No render is possible without image bytes - render() is never called; the quality gate
    # sees the FAILED image result directly.
    render_result_placeholder = render_meme(b"", copy, storage=storage)
    assert render_result_placeholder.status == MemeRenderStatus.FAILED

    quality_assessment = assess_meme_quality(concept, copy, safety_gate, render_result_placeholder, image_result)
    assert quality_assessment.decision == MemeQualityDecision.REGENERATE_IMAGE

    # First regeneration attempt: still allowed (count starts at 0).
    first_bound = apply_regeneration_bounds(quality_assessment, concept_regeneration_count=0, image_regeneration_count=0)
    assert first_bound.decision == MemeQualityDecision.REGENERATE_IMAGE

    # Once the bound is already reached, it must convert to REJECT - never an infinite retry loop.
    from services.meme_quality import MAX_IMAGE_REGENERATIONS

    second_bound = apply_regeneration_bounds(
        quality_assessment, concept_regeneration_count=0, image_regeneration_count=MAX_IMAGE_REGENERATIONS,
    )
    assert second_bound.decision == MemeQualityDecision.REJECT

    final = await service.attach_quality_assessment(candidate.id, second_bound)
    assert final is not None
    assert final.status == MemeCandidateStatus.QUALITY_REJECTED
    assert final.status != MemeCandidateStatus.PENDING_EDITOR
