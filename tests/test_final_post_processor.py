"""Phase I.1: services.final_post_processor.generate_final_post_for_review() - APPROVED
EventRecapReview -> deterministic authoring source bundle -> idempotent FINAL_POST_AUTHORING task
-> exactly one LLM authoring call -> deterministic fact-safety -> ContentDraft. Mirrors
tests/test_event_recap_processor.py's own established shape/fixtures exactly (real Postgres via
the db_session fixture, FakeLLMGateway, zero network/cost) - no real LLM call anywhere in this file.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.final_post_authoring_capability import (
    FINAL_POST_AUTHORING_CAPABILITY_DEFINITION,
    FinalPostAuthoringCapability,
)
from capabilities.registry import CapabilityRegistry
from core.config import settings
from database.models.content_draft import ContentDraft
from database.models.editorial_task import EditorialTask, TaskStatus
from database.models.event_recap_review import EventRecapReviewStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from schemas.workflow import WorkflowStepResult
from services import image_persistence
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION
from services.event_recap_processor import generate_recap_for_story
from services.event_recap_review_service import create_event_recap_review, set_decision
from services.final_post_processor import find_final_post_authoring_task_id, generate_final_post_for_review
from services.story_memory import NEW_STORY
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository


@pytest.fixture(autouse=True)
def _isolated_image_storage(tmp_path, monkeypatch: pytest.MonkeyPatch):
    """Mirrors tests/test_event_recap_processor.py's own identical fixture - generate_recap_for_story()
    itself may reach Tier 3 branded-fallback rendering during setup."""
    monkeypatch.setattr(settings, "image_storage_root", str(tmp_path))
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)
    yield
    monkeypatch.setattr(image_persistence, "_storage_singleton", None)


_VALID_RECAP_OUTPUT = {
    "recap_title": "Example Recap Title",
    "recap_summary": "Example recap summary sentence.",
    "key_takeaways": ["First takeaway.", "Second takeaway."],
    "uncertainty_notes": [],
}

_VALID_FINAL_POST_OUTPUT = {"title": "A public news title", "body": "A public news body, in prose."}


_FINAL_POST_AUTHORING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"], "additionalProperties": False,
}


def _final_post_authoring_prompt_repository() -> FakePromptRepository:
    """Phase I.1.4: registers BOTH "1" and "2" - settings.final_post_authoring_prompt_version now
    defaults to "2" (the production-promoted version), and several tests explicitly override to
    "1" for rollback/comparison coverage, so both must always resolve regardless of which the
    active settings value happens to be."""
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name="final_post_authoring", version="1", system="You are a fake final-post copywriter V1.",
            rules=["Never invent facts."], output_schema=_FINAL_POST_AUTHORING_OUTPUT_SCHEMA,
        )
    )
    repository.register(
        RenderedPrompt(
            name="final_post_authoring", version="2", system="You are a fake final-post copywriter V2.",
            rules=["Never invent facts."], output_schema=_FINAL_POST_AUTHORING_OUTPUT_SCHEMA,
        )
    )
    return repository


def _event_recap_prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=EVENT_RECAP_PROMPT_NAME, version=EVENT_RECAP_PROMPT_VERSION,
            system="You are a fake recap analyst.", rules=["Never invent facts."],
            output_schema={
                "type": "object",
                "properties": {
                    "recap_title": {"type": "string"}, "recap_summary": {"type": "string"},
                    "key_takeaways": {"type": "array"}, "uncertainty_notes": {"type": "array"},
                },
                "required": ["recap_title", "recap_summary", "key_takeaways", "uncertainty_notes"],
            },
        )
    )
    return repository


def _recap_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, _event_recap_prompt_repository()),
    )
    registry.seal()
    return registry


def _final_post_registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        FINAL_POST_AUTHORING_CAPABILITY_DEFINITION,
        FinalPostAuthoringCapability(gateway, _final_post_authoring_prompt_repository()),
    )
    registry.seal()
    return registry


def _final_post_gateway(output: dict | None = None) -> FakeLLMGateway:
    return FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=output or _VALID_FINAL_POST_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )


_READY_EVENT_TITLES_URLS: tuple[tuple[str, str], ...] = (
    ("Apple unveils iPhone X", "https://techcrunch.com/c1"),
    ("Apple announces iPhone X pricing", "https://theverge.com/c2"),
    ("Apple reveals Watch Ultra 3", "https://engadget.com/c3"),
    ("Apple introduces Apple Intelligence upgrade", "https://arstechnica.com/c4"),
    ("Apple demos iPhone X", "https://9to5mac.com/c5"),
    ("Apple announces iPhone X pricing details", "https://macrumors.com/c6"),
)
_READY_EVENT_MINUTES_AGO_OFFSETS: tuple[int, ...] = (50, 40, 30, 20, 10, 0)


async def _seed_ready_story(session: AsyncSession, *, base_minutes_ago: int = 120) -> tuple[Story, list[NewsEvent]]:
    """Byte-for-byte the same fixture tests/test_event_recap_processor.py::_seed_ready_story() uses
    - a real, DB-backed Story that structurally clears every readiness threshold through the real
    build_event_recap_candidate() pipeline. Reused verbatim (not imported cross-file, since that
    module has autouse fixtures of its own) per this codebase's own established convention."""
    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()

    now = datetime.now(timezone.utc)
    events: list[NewsEvent] = []
    for (title, url), offset in zip(_READY_EVENT_TITLES_URLS, _READY_EVENT_MINUTES_AGO_OFFSETS):
        minutes_ago = base_minutes_ago + offset
        event = NewsEvent(
            source_id=source.id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        session.add(event)
        events.append(event)
    await session.flush()

    story = Story(
        title=events[0].title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=events[0].id, event_count=len(events),
    )
    session.add(story)
    await session.flush()
    for event in events:
        session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0)
        )
    await session.flush()
    return story, events


async def _seed_approved_review(session: AsyncSession):
    """Full, real chain: ready Story -> generate_recap_for_story() (real EVENT_RECAP run, through
    the real processor - so the new "event_recap_source_snapshot" step is really persisted) ->
    EventRecapReview -> APPROVED. Returns (review, recap_task_id, story, events)."""
    story, events = await _seed_ready_story(session)
    recap_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    recap_outcome = await generate_recap_for_story(session, story.id, capability_registry=_recap_registry(recap_gateway))
    assert recap_outcome.status == "generated"

    review = await create_event_recap_review(session, recap_task_id=recap_outcome.task_id)
    review = await set_decision(session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=12345)
    assert review is not None
    return review, recap_outcome.task_id, story, events


async def _seed_legacy_task_and_approved_review(session: AsyncSession):
    """Manually constructs an EditorialTask shaped like a PRE-Phase-I.1 EVENT_RECAP task - only
    "synthesize_recap" (+ "select_recap_media") step_results, deliberately NO
    "event_recap_source_snapshot" entry - mirrors the real, empirically-confirmed Pixel task shape
    (this module's own docstring). Used to exercise the LEGACY APPROVED RECAP POLICY path."""
    from services import workflow_service
    from schemas.editorial_task import EditorialTaskCreate
    from database.models.editorial_task import TaskPriority
    from schemas.workflow import WorkflowType

    source = NewsSource(
        name="Legacy Source", type=SourceType.RSS, url=f"https://example.com/legacy-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()

    event = NewsEvent(
        source_id=source.id, title="Legacy anchor headline", content="Body",
        category=EventCategory.TECH, hash=f"legacy-hash-{uuid4()}",
    )
    session.add(event)
    await session.flush()

    story = Story(
        title=event.title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0))
    await session.flush()

    task_read = await workflow_service.create_task(
        session,
        EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.EVENT_RECAP, priority=TaskPriority.C),
    )
    task = await session.get(EditorialTask, task_read.id)
    now = datetime.now(timezone.utc)
    recap_step = WorkflowStepResult(
        step_name="synthesize_recap", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
        result=_VALID_RECAP_OUTPUT,
    )
    media_step = WorkflowStepResult(
        step_name="select_recap_media", status="SUCCESS", attempt=1, started_at=now, finished_at=now,
        result={
            "tier": "branded_fallback",
            "representative": {
                "candidate_id": None, "originating_event_id": None, "media_type": "image",
                "recommended_role": "hero", "storage_key": "legacy/fallback.jpg",
                "telegram_file_id": None, "sha256": "deadbeef", "remote_url": None,
            },
        },
    )
    workflow = dict(task.workflow or {})
    workflow["step_results"] = [recap_step.model_dump(mode="json"), media_step.model_dump(mode="json")]
    task.workflow = workflow
    task.status = TaskStatus.COMPLETED
    await session.commit()

    review = await create_event_recap_review(session, recap_task_id=task_read.id)
    review = await set_decision(session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=12345)
    return review, task_read.id, story, event


# -------------------------------------------------------------------------------------------
# Approved-only gate
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_review_not_found_returns_early(db_session: AsyncSession) -> None:
    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, uuid4(), capability_registry=_final_post_registry(gateway))

    assert outcome.status == "review_not_found"
    assert outcome.task_id is None
    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_pending_review_never_reaches_authoring(db_session: AsyncSession) -> None:
    story, events = await _seed_ready_story(db_session)
    recap_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    recap_outcome = await generate_recap_for_story(db_session, story.id, capability_registry=_recap_registry(recap_gateway))
    review = await create_event_recap_review(db_session, recap_task_id=recap_outcome.task_id)
    assert review.status == EventRecapReviewStatus.PENDING

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "not_approved"
    assert outcome.task_id is None
    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_needs_revision_review_never_reaches_authoring(db_session: AsyncSession) -> None:
    story, events = await _seed_ready_story(db_session)
    recap_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    recap_outcome = await generate_recap_for_story(db_session, story.id, capability_registry=_recap_registry(recap_gateway))
    review = await create_event_recap_review(db_session, recap_task_id=recap_outcome.task_id)
    review = await set_decision(db_session, review.id, EventRecapReviewStatus.NEEDS_REVISION, decided_by_user_id=1)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "not_approved"
    assert outcome.task_id is None
    assert gateway.received_requests == []


# -------------------------------------------------------------------------------------------
# Happy path (Pixel-like) - real durable source snapshot present
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_approved_review_generates_exactly_one_final_post(db_session: AsyncSession) -> None:
    review, recap_task_id, story, events = await _seed_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    assert outcome.task_id is not None
    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    assert outcome.fact_safety_status in ("pass", "review")
    assert len(gateway.received_requests) == 1
    assert outcome.content_draft is not None
    assert outcome.content_draft.title == _VALID_FINAL_POST_OUTPUT["title"]
    assert outcome.content_draft.body == _VALID_FINAL_POST_OUTPUT["body"]
    assert outcome.content_draft.task_id == outcome.task_id  # linked to the FINAL_POST_AUTHORING task

    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.event_id == events[0].id  # same anchor as the source EVENT_RECAP task
    assert task.workflow["workflow_name"] == "FINAL_POST_AUTHORING"

    source_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_source")
    bundle = source_step["result"]
    assert bundle["source_event_recap_task_id"] == str(recap_task_id)
    assert bundle["source_event_recap_review_id"] == str(review.id)
    assert bundle["story_id"] == str(story.id)
    assert bundle["anchor_event_id"] == str(events[0].id)
    assert bundle["legacy_snapshot_missing"] is False
    assert bundle["approved_recap"]["recap_title"] == _VALID_RECAP_OUTPUT["recap_title"]

    draft_count = (
        await db_session.execute(
            select(func.count()).select_from(ContentDraft).where(ContentDraft.task_id == outcome.task_id)
        )
    ).scalar_one()
    assert draft_count == 1


@pytest.mark.asyncio
async def test_duplicate_invocation_is_idempotent(db_session: AsyncSession) -> None:
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    gateway = _final_post_gateway()
    registry = _final_post_registry(gateway)

    first = await generate_final_post_for_review(db_session, review.id, capability_registry=registry)
    assert first.status == "generated"
    assert len(gateway.received_requests) == 1

    second = await generate_final_post_for_review(db_session, review.id, capability_registry=registry)

    assert second.status == "already_exists"
    assert second.task_id == first.task_id
    assert second.content_draft is None
    assert len(gateway.received_requests) == 1  # no new paid call

    draft_count = (
        await db_session.execute(
            select(func.count()).select_from(ContentDraft).where(ContentDraft.task_id == first.task_id)
        )
    ).scalar_one()
    assert draft_count == 1  # no second ContentDraft


@pytest.mark.asyncio
async def test_find_final_post_authoring_task_id_locates_the_task(db_session: AsyncSession) -> None:
    review, _recap_task_id, _story, events = await _seed_approved_review(db_session)
    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    found = await find_final_post_authoring_task_id(db_session, events[0].id)

    assert found == outcome.task_id


# -------------------------------------------------------------------------------------------
# Fact-safety
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_safety_block_prevents_content_draft(db_session: AsyncSession) -> None:
    """A fabricated, unsupported central entity in the authored title must block ContentDraft
    creation - the LLM call still happened exactly once, but nothing is persisted as a draft."""
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    unsupported_output = {
        "title": "Marcus Fenwick Announces Major Deal",
        "body": "Marcus Fenwick made a major announcement today about new plans.",
    }
    gateway = _final_post_gateway(unsupported_output)
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "fact_safety_blocked"
    assert outcome.fact_safety_status == "block"
    assert outcome.content_draft is None
    assert len(gateway.received_requests) == 1  # no retry on a fact-safety block

    draft_count = (
        await db_session.execute(
            select(func.count()).select_from(ContentDraft).where(ContentDraft.task_id == outcome.task_id)
        )
    ).scalar_one()
    assert draft_count == 0


@pytest.mark.asyncio
async def test_epistemic_strengthening_is_not_detected_disclosed_gap(db_session: AsyncSession) -> None:
    """DISCLOSED GAP (instruction item 15): existing evaluate_fact_safety() only checks entity/
    number support against the evidence text - it has no modality/certainty detector. An authored
    body that keeps every entity/number the approved recap already used, but silently strengthens
    "reportedly considering" into a stated, finished fact, is NOT caught. This test documents that
    gap empirically rather than asserting a blocking behavior this phase does not implement -
    see services/final_post_processor.py's own module docstring and the Phase I.1 report's own
    "Epistemic-strength guard" section."""
    story, events = await _seed_ready_story(db_session)
    recap_output = {
        "recap_title": "Apple weighs a pricing change",
        "recap_summary": "Apple is reportedly considering a change to iPhone X pricing.",
        "key_takeaways": ["Apple is reportedly considering a change to iPhone X pricing."],
        "uncertainty_notes": ["It remains unclear whether the pricing change will be finalized."],
    }
    recap_gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=recap_output, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    recap_outcome = await generate_recap_for_story(db_session, story.id, capability_registry=_recap_registry(recap_gateway))
    review = await create_event_recap_review(db_session, recap_task_id=recap_outcome.task_id)
    review = await set_decision(db_session, review.id, EventRecapReviewStatus.APPROVED, decided_by_user_id=1)

    strengthened_output = {
        "title": "Apple finalizes iPhone X pricing change",
        "body": "Apple finalized the iPhone X pricing change, ending months of speculation.",
    }
    gateway = _final_post_gateway(strengthened_output)
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    # Documents the gap: this SHOULD ideally be flagged, but current fact-safety lets it through.
    assert outcome.status == "generated"
    assert outcome.fact_safety_status == "pass"
    assert outcome.content_draft is not None


# -------------------------------------------------------------------------------------------
# Legacy approved recap policy
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_task_without_source_snapshot_authors_from_recap_text_only(db_session: AsyncSession) -> None:
    review, recap_task_id, story, event = await _seed_legacy_task_and_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    assert len(gateway.received_requests) == 1
    assert outcome.content_draft is not None

    task = await db_session.get(EditorialTask, outcome.task_id)
    source_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_source")
    bundle = source_step["result"]

    assert bundle["legacy_snapshot_missing"] is True
    assert bundle["anchor_event_id"] == str(event.id)  # always available, no lookup needed
    assert bundle["story_id"] == str(story.id)  # resolved via NewsEventStoryLink FK lookup
    assert bundle["verified_facts"] == []  # never reconstructed from the current Story
    assert bundle["source_refs"] == []
    assert bundle["approved_recap"]["recap_title"] == _VALID_RECAP_OUTPUT["recap_title"]

    # The Story itself was never rebuilt/re-queried for facts - only its stable id was resolved.
    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "Legacy anchor headline" not in sent_text  # raw NewsEvent title never reaches the LLM


@pytest.mark.asyncio
async def test_media_plan_is_copied_verbatim_from_the_source_recap_task(db_session: AsyncSession) -> None:
    review, _recap_task_id, _story, _event = await _seed_legacy_task_and_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    task = await db_session.get(EditorialTask, outcome.task_id)
    source_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_source")
    media_plan = source_step["result"]["selected_media_plan"]

    assert media_plan["tier"] == "branded_fallback"
    assert media_plan["representative"]["storage_key"] == "legacy/fallback.jpg"
    assert media_plan["representative"]["sha256"] == "deadbeef"

    # No resolution/sending happened in I.1 - storage_key never touched real storage.
    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "legacy/fallback.jpg" not in sent_text


# -------------------------------------------------------------------------------------------
# Phase I.1.4: durable prompt-version provenance (Part 12)
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_actual_prompt_version_is_persisted_in_final_post_source_default_v2(db_session: AsyncSession) -> None:
    """settings.final_post_authoring_prompt_version defaults to "2" (Phase I.1.4 promotion) - the
    persisted final_post_source bundle must record that exact value, never a hardcoded "2"."""
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)
    assert settings.final_post_authoring_prompt_version == "2"

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    task = await db_session.get(EditorialTask, outcome.task_id)
    source_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_source")
    assert source_step["result"]["authoring_prompt_version"] == "2"

    sent_text = gateway.received_requests[0].messages[0].content[0].text
    assert "copywriter V2" in sent_text


@pytest.mark.asyncio
async def test_actual_prompt_version_is_persisted_in_final_post_source_explicit_v1(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit override to "1" (rollback/comparison) must be reflected exactly, not the
    default "2"."""
    monkeypatch.setattr(settings, "final_post_authoring_prompt_version", "1")
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    task = await db_session.get(EditorialTask, outcome.task_id)
    source_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_source")
    assert source_step["result"]["authoring_prompt_version"] == "1"

    sent_text = gateway.received_requests[0].messages[0].content[0].text
    assert "copywriter V1" in sent_text


# -------------------------------------------------------------------------------------------
# Phase I.1.4: durable fact-safety provenance (Parts 13-15)
# -------------------------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fact_safety_pass_result_is_durably_persisted_and_matches_the_gating_result(
    db_session: AsyncSession,
) -> None:
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    assert outcome.fact_safety_status in ("pass", "review")
    assert outcome.content_draft is not None

    task = await db_session.get(EditorialTask, outcome.task_id)
    step_names = [r["step_name"] for r in task.workflow["step_results"]]
    assert "final_post_fact_safety" in step_names

    fact_safety_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_fact_safety")
    assert fact_safety_step["status"] == "SUCCESS"
    persisted = fact_safety_step["result"]
    assert persisted["status"] == outcome.fact_safety_status
    assert "claims_checked" in persisted
    assert "supported" in persisted
    assert "uncertain" in persisted
    assert "unsupported" in persisted
    assert "findings" in persisted


@pytest.mark.asyncio
async def test_fact_safety_block_result_is_durably_persisted_even_without_a_contentdraft(
    db_session: AsyncSession,
) -> None:
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    unsupported_output = {
        "title": "Marcus Fenwick Announces Major Deal",
        "body": "Marcus Fenwick made a major announcement today about new plans.",
    }
    gateway = _final_post_gateway(unsupported_output)
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "fact_safety_blocked"
    assert outcome.fact_safety_status == "block"
    assert outcome.content_draft is None
    assert len(gateway.received_requests) == 1  # no retry on a fact-safety block

    task = await db_session.get(EditorialTask, outcome.task_id)
    fact_safety_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_fact_safety")
    assert fact_safety_step["status"] == "SUCCESS"
    assert fact_safety_step["result"]["status"] == "block"
    assert fact_safety_step["result"]["findings"]  # non-empty - the actual audit evidence

    draft_count = (
        await db_session.execute(
            select(func.count()).select_from(ContentDraft).where(ContentDraft.task_id == outcome.task_id)
        )
    ).scalar_one()
    assert draft_count == 0


@pytest.mark.asyncio
async def test_contentdraft_invariant_source_authoring_and_passing_fact_safety_all_exist(
    db_session: AsyncSession,
) -> None:
    """Part 15's own invariant, to be consumed by I.2: for a NEW (post-I.1.4) FINAL_POST_AUTHORING
    task, a ContentDraft existing implies final_post_source, final_post_authoring, and
    final_post_fact_safety(status == pass|review, i.e. non-blocking) all exist."""
    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.content_draft is not None
    task = await db_session.get(EditorialTask, outcome.task_id)
    step_names = {r["step_name"] for r in task.workflow["step_results"]}
    assert {"final_post_source", "final_post_authoring", "final_post_fact_safety"} <= step_names

    fact_safety_step = next(r for r in task.workflow["step_results"] if r["step_name"] == "final_post_fact_safety")
    assert fact_safety_step["result"]["status"] != "block"


@pytest.mark.asyncio
async def test_evaluate_fact_safety_runs_exactly_once_per_authoring_run(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Part 7: persistence must reuse the one existing evaluation - never a second call to
    evaluate_fact_safety() purely for persistence purposes."""
    import services.final_post_processor as final_post_processor_module

    call_count = 0
    real_evaluate = final_post_processor_module.evaluate_fact_safety

    def _counting_evaluate(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return real_evaluate(*args, **kwargs)

    monkeypatch.setattr(final_post_processor_module, "evaluate_fact_safety", _counting_evaluate)

    review, _recap_task_id, _story, _events = await _seed_approved_review(db_session)
    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    assert call_count == 1


@pytest.mark.asyncio
async def test_legacy_pre_i114_tasks_are_never_backfilled(db_session: AsyncSession) -> None:
    """Part 9: a task created before this phase (no final_post_fact_safety step at all) must never
    be silently mutated/backfilled by this module - generate_final_post_for_review() never revisits
    an existing task's own step_results after creation."""
    review, recap_task_id, story, event = await _seed_legacy_task_and_approved_review(db_session)

    gateway = _final_post_gateway()
    outcome = await generate_final_post_for_review(db_session, review.id, capability_registry=_final_post_registry(gateway))

    assert outcome.status == "generated"
    task = await db_session.get(EditorialTask, outcome.task_id)
    step_names = {r["step_name"] for r in task.workflow["step_results"]}
    # This IS a fresh, new I.1.4 task (the legacy shape only applies to the SOURCE recap task,
    # never to this new FINAL_POST_AUTHORING task) - final_post_fact_safety is present here.
    assert "final_post_fact_safety" in step_names

    # The SOURCE EVENT_RECAP task itself (legacy, pre-I.1) was never touched.
    recap_task = await db_session.get(EditorialTask, recap_task_id)
    recap_step_names = {r["step_name"] for r in recap_task.workflow["step_results"]}
    assert "final_post_fact_safety" not in recap_step_names
    assert "event_recap_source_snapshot" not in recap_step_names
