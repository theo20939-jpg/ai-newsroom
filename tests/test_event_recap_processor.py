"""NINJA PULSE RECAP Phase R2 integration, Phase C.0/G.1: services.event_recap_processor.
generate_recap_for_story() - Story lookup -> existing-task check -> readiness pre-check ->
EVENT_RECAP EditorialTask creation (or duplicate-task lookup) -> real WorkflowRunner run through
CapabilityExecutor -> EventRecapCapability -> synthesize_event_recap() -> FakeLLMGateway. Mirrors
tests/test_telegraph_article_processor.py's own established shape/fixtures exactly (real Postgres
via the db_session fixture, FakeLLMGateway, zero network/cost) - no real LLM call anywhere in this
file.

Phase G.1: `_seed_not_ready_story()` (single-event, the Tether/Vantage/Silver Lake structural
shape) and `_seed_ready_story()` (the same 6-event/4-cluster/6-source fixture already proven READY
in tests/test_recap_event.py::_developing_launch_events(), reused verbatim rather than inventing a
new one) replace the old single `_seed_story()` helper - a single-event Story no longer reaches
synthesis by default now that the readiness gate is real.
"""
from __future__ import annotations

from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.executor import CapabilityExecutor
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import EditorialTask
from database.models.image_candidate_record import ImageCandidateRecord
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION
from services.event_recap_processor import (
    find_event_recap_task_id,
    generate_recap_for_story,
)
from services.story_memory import NEW_STORY
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_VALID_RECAP_OUTPUT = {
    "recap_title": "Example Recap Title",
    "recap_summary": "Example recap summary sentence.",
    "key_takeaways": ["First takeaway.", "Second takeaway."],
    "uncertainty_notes": [],
}


def _prompt_repository() -> FakePromptRepository:
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


def _registry(gateway: FakeLLMGateway) -> CapabilityRegistry:
    registry = CapabilityRegistry()
    registry.register(
        EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability(gateway, _prompt_repository()),
    )
    registry.seal()
    return registry


async def _seed_not_ready_story(session: AsyncSession) -> tuple[Story, NewsEvent]:
    """A real NewsSource + NewsEvent + Story (first_event_id=event.id) + confirmed
    NewsEventStoryLink - single-event, the exact structural shape of the real Tether/Vantage/
    Silver Lake Stories (Phase G.0's own forensic finding): event_count=1, announcement_count=1,
    unique_source_count=1 - fails all three of settings.recap_min_event_count/
    recap_min_announcement_count/recap_min_unique_sources at once. Story Integrity itself trivially
    passes (nothing to be incoherent with) - readiness is what correctly rejects this shape."""
    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    session.add(source)
    await session.flush()

    event = NewsEvent(
        source_id=source.id, title="Example headline for recap processor test", content="Body",
        category=EventCategory.AI, hash=f"test-hash-{uuid4()}",
    )
    session.add(event)
    await session.flush()

    story = Story(
        title=event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="test", first_event_id=event.id, event_count=1,
    )
    session.add(story)
    await session.flush()
    session.add(
        NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0)
    )
    await session.flush()
    return story, event


# Phase G.1: the exact same 6-event, 4-announcement-cluster, 6-unique-source fixture already
# proven structurally READY (event_count>=3, announcement_count>=4, unique_source_count>=2,
# cooling elapsed, story_integrity eligible - ratio 0.60) in
# tests/test_recap_event.py::_developing_launch_events() /
# test_case_d_cooled_with_research_complete_is_ready() - reused verbatim, never reinvented, per
# this codebase's own "single source of truth for a proven fixture" convention.
_READY_EVENT_TITLES_URLS: tuple[tuple[str, str], ...] = (
    ("Apple unveils iPhone X", "https://techcrunch.com/c1"),
    ("Apple announces iPhone X pricing", "https://theverge.com/c2"),
    ("Apple reveals Watch Ultra 3", "https://engadget.com/c3"),
    ("Apple introduces Apple Intelligence upgrade", "https://arstechnica.com/c4"),
    ("Apple demos iPhone X", "https://9to5mac.com/c5"),
    ("Apple announces iPhone X pricing details", "https://macrumors.com/c6"),
)
# Minutes-ago offsets added on top of a 120-minute base (past settings.recap_cooling_window_minutes
# = 90) for the freshest event - mirrors _developing_launch_events(last_minutes_ago=120) exactly.
_READY_EVENT_MINUTES_AGO_OFFSETS: tuple[int, ...] = (50, 40, 30, 20, 10, 0)


async def _seed_ready_story(session: AsyncSession, *, base_minutes_ago: int = 120) -> tuple[Story, list[NewsEvent]]:
    """A real, DB-backed Story that structurally clears every current readiness threshold through
    the REAL build_event_recap_candidate() pipeline (clustering/integrity/source-counting) - never
    a synthetic in-memory EventRecapCandidate. `base_minutes_ago=120` keeps the freshest event past
    the 90-minute cooling window by default."""
    from datetime import datetime, timezone

    from database.models.news_source import NewsSource, SourceType

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


@pytest.mark.asyncio
async def test_story_not_found_returns_early(db_session: AsyncSession) -> None:
    gateway = FakeLLMGateway()
    registry = _registry(gateway)

    outcome = await generate_recap_for_story(db_session, uuid4(), capability_registry=registry)

    assert outcome.status == "story_not_found"
    assert outcome.task_id is None
    assert outcome.run_result is None
    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_creates_event_recap_task_and_completes_synthesis(db_session: AsyncSession) -> None:
    story, events = await _seed_ready_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "generated"
    assert outcome.run_result is not None and outcome.run_result.status == "COMPLETED"
    assert outcome.task_id is not None
    assert outcome.readiness_reasons == ()

    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.event_id == events[0].id  # anchored to story.first_event_id, exactly like TELEGRAPH_ARTICLE
    assert task.workflow["workflow_name"] == "EVENT_RECAP"

    step_result = next(r for r in task.workflow["step_results"] if r["step_name"] == "synthesize_recap")
    assert step_result["status"] == "SUCCESS"
    assert step_result["result"] == _VALID_RECAP_OUTPUT
    assert len(gateway.received_requests) == 1  # the Gateway was actually reached, exactly once


@pytest.mark.asyncio
async def test_second_attempt_reuses_existing_task_no_new_paid_call(db_session: AsyncSession) -> None:
    story, _events = await _seed_ready_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    first = await generate_recap_for_story(db_session, story.id, capability_registry=registry)
    assert first.status == "generated"
    calls_after_first = len(gateway.received_requests)
    assert calls_after_first == 1

    second = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert second.status == "already_exists"
    assert second.task_id == first.task_id
    assert second.run_result is None
    assert len(gateway.received_requests) == calls_after_first  # no new paid call


@pytest.mark.asyncio
async def test_find_event_recap_task_id_locates_the_task(db_session: AsyncSession) -> None:
    story, events = await _seed_ready_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)
    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    found = await find_event_recap_task_id(db_session, events[0].id)

    assert found == outcome.task_id


# ---------------------------------------------------------------------------------------------
# Phase G.1 - readiness gate
# ---------------------------------------------------------------------------------------------


async def _ai_execution_count(session: AsyncSession) -> int:
    from sqlalchemy import func, select

    from database.models.ai_execution import AIExecution

    return (await session.execute(select(func.count()).select_from(AIExecution))).scalar_one()


async def _event_recap_task_count(session: AsyncSession, event_id) -> int:  # noqa: ANN001
    from sqlalchemy import func, select

    return (
        await session.execute(
            select(func.count()).select_from(EditorialTask).where(
                EditorialTask.event_id == event_id,
                EditorialTask.workflow["workflow_name"].as_string() == "EVENT_RECAP",
            )
        )
    ).scalar_one()


@pytest.mark.asyncio
async def test_not_ready_story_returns_early_no_task_no_gateway_call(db_session: AsyncSession) -> None:
    """A single-event Story, structurally identical to the real Tether/Vantage/Silver Lake Stories
    (Phase G.0's own forensic finding) - event_count=1 < 3, announcement_count=1 < 4,
    unique_source_count=1 < 2 - must be rejected BEFORE any EditorialTask/AIExecution exists and
    before the Gateway is ever reached."""
    story, event = await _seed_not_ready_story(db_session)
    gateway = FakeLLMGateway()
    registry = _registry(gateway)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "not_ready"
    assert outcome.task_id is None
    assert outcome.run_result is None
    assert outcome.readiness_reasons != ()
    joined_reasons = " ".join(outcome.readiness_reasons).lower()
    assert "event_count" in joined_reasons

    assert await _event_recap_task_count(db_session, event.id) == 0
    assert await _ai_execution_count(db_session) == 0
    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_not_ready_story_can_later_mature_and_generate(db_session: AsyncSession) -> None:
    """Lifecycle proof (Phase G.0.2's own central invariant): a NOT_READY first attempt must NOT
    permanently block a later attempt once the SAME Story naturally matures into a genuinely READY
    one - the global duplicate-task guard only ever sees a task if one was actually created, and
    Phase G.1's whole point is that a NOT_READY Story never creates one."""
    from datetime import datetime, timezone

    from database.models.news_source import NewsSource, SourceType

    source = NewsSource(
        name="Test Source", type=SourceType.RSS, url=f"https://example.com/feed-{uuid4()}.xml", active=True,
    )
    db_session.add(source)
    await db_session.flush()

    now = datetime.now(timezone.utc)
    title0, url0 = _READY_EVENT_TITLES_URLS[0]
    # T0: only the anchor event exists - single-event Story, NOT_READY.
    anchor = NewsEvent(
        source_id=source.id, title=title0, url=url0, content="Body",
        published_at=now - timedelta(minutes=120 + 50), collected_at=now - timedelta(minutes=120 + 50),
        category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
    )
    db_session.add(anchor)
    await db_session.flush()
    story = Story(
        title=anchor.title, category=EventCategory.TECH, entities=[], keywords=[],
        topic_bucket="test", first_event_id=anchor.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(
        NewsEventStoryLink(news_event_id=anchor.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0)
    )
    await db_session.flush()

    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    t0_outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)
    assert t0_outcome.status == "not_ready"
    assert t0_outcome.task_id is None
    assert await _event_recap_task_count(db_session, anchor.id) == 0

    # T+X: the Story matures - the remaining events of the same proven READY fixture arrive.
    for (title, url), offset in zip(_READY_EVENT_TITLES_URLS[1:], _READY_EVENT_MINUTES_AGO_OFFSETS[1:]):
        minutes_ago = 120 + offset
        event = NewsEvent(
            source_id=source.id, title=title, url=url, content="Body",
            published_at=now - timedelta(minutes=minutes_ago), collected_at=now - timedelta(minutes=minutes_ago),
            category=EventCategory.TECH, hash=f"test-hash-{uuid4()}",
        )
        db_session.add(event)
        await db_session.flush()
        db_session.add(
            NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_type=NEW_STORY, match_score=1.0)
        )
    await db_session.flush()

    t1_outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert t1_outcome.status == "generated"
    assert t1_outcome.task_id is not None
    assert t1_outcome.run_result is not None and t1_outcome.run_result.status == "COMPLETED"
    assert len(gateway.received_requests) == 1  # exactly one paid call, on the READY attempt only


@pytest.mark.asyncio
async def test_ready_story_builds_candidate_exactly_once_and_passes_it_through(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Race-safety proof (Phase G.0.2): for one READY processor run, build_event_recap_candidate()
    is called exactly once, and the SAME object identity that call returned is what reaches
    CapabilityExecutor - never a second, independently-requeried candidate."""
    import services.event_recap_processor as processor_module

    story, _events = await _seed_ready_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    real_build = processor_module.build_event_recap_candidate
    build_call_count = 0
    built_candidates: list[object] = []

    async def _counting_build(*args, **kwargs):
        nonlocal build_call_count
        build_call_count += 1
        result = await real_build(*args, **kwargs)
        built_candidates.append(result.candidate)
        return result

    monkeypatch.setattr(processor_module, "build_event_recap_candidate", _counting_build)

    captured_precomputed_candidates: list[object] = []
    real_executor_init = CapabilityExecutor.__init__

    def _spy_executor_init(self, *args, **kwargs):
        captured_precomputed_candidates.append(kwargs.get("precomputed_event_recap_candidate"))
        real_executor_init(self, *args, **kwargs)

    monkeypatch.setattr(processor_module.CapabilityExecutor, "__init__", _spy_executor_init)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "generated"
    assert build_call_count == 1
    assert len(built_candidates) == 1
    assert len(captured_precomputed_candidates) == 1
    assert captured_precomputed_candidates[0] is built_candidates[0]


# ---------------------------------------------------------------------------------------------
# Phase H.1 - Story media foundation
# ---------------------------------------------------------------------------------------------


async def _seed_image_candidate(
    session: AsyncSession, event_id, *, candidate_id: str, quality_score: int, relevance_score: int,  # noqa: ANN001
    rank: int = 1, width: int = 1200, height: int = 800, image_format: str = "JPEG",
    warnings: list[str] | None = None, sha256: str | None = None,
) -> None:
    """Seeds one real, eligible `ImageCandidateRecord` row for `event_id` - the exact table
    `services.event_recap._collect_media_candidates()` already reads via `get_editorial_image_
    candidates()`, unmodified. Mirrors tests/test_media_ranking_story_reuse.py's own established
    minimal-fields construction pattern."""
    session.add(
        ImageCandidateRecord(
            news_event_id=event_id, candidate_id=candidate_id, source_type=SourceType.RSS,
            discovery_method="open_graph_image", quality_score=quality_score,
            relevance_score=relevance_score, rank=rank, width=width, height=height,
            image_format=image_format, quality_warnings=warnings or [], sha256=sha256,
            source_url=f"https://example.com/{candidate_id}.jpg", eligible_for_editorial=True,
        )
    )
    await session.flush()


def _media_step_result(task: EditorialTask) -> dict:
    return next(r for r in task.workflow["step_results"] if r["step_name"] == "select_recap_media")


@pytest.mark.asyncio
async def test_zero_media_still_generates_with_tier_none(db_session: AsyncSession) -> None:
    """Phase H.1 §12 (zero media test): a READY Story with NO eligible image anywhere in its
    confirmed-membership pool must still synthesize normally - fail-soft, never an exception or a
    FAILED task."""
    story, _events = await _seed_ready_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "generated"
    assert len(gateway.received_requests) == 1
    task = await db_session.get(EditorialTask, outcome.task_id)
    media_result = _media_step_result(task)
    assert media_result["status"] == "SUCCESS"
    assert media_result["result"] == {"tier": "none", "representative": None}


@pytest.mark.asyncio
async def test_media_selection_finds_follow_up_image_when_anchor_has_none(db_session: AsyncSession) -> None:
    """Phase H.1 §10 (Twitch realistic fixture): mirrors the real, DB-confirmed production shape
    (Phase G.2's own forensic finding on the real Twitch/Amazon Story) - the anchor event has ZERO
    image candidates, but a LATER confirmed-membership (`story_update`) event has one strong,
    eligible image. Story-level selection must find it - proving selection is not limited to
    `first_event_id`."""
    story, events = await _seed_ready_story(db_session)
    anchor = events[0]
    follow_up = events[3]  # a later confirmed member, not the anchor

    await _seed_image_candidate(
        db_session, follow_up.id, candidate_id="follow-up-hero", quality_score=98, relevance_score=67,
    )

    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "generated"
    task = await db_session.get(EditorialTask, outcome.task_id)
    media_result = _media_step_result(task)
    assert media_result["result"]["tier"] == "story_pool"
    representative = media_result["result"]["representative"]
    assert representative["candidate_id"] == "follow-up-hero"
    assert representative["originating_event_id"] == str(follow_up.id)
    assert representative["originating_event_id"] != str(anchor.id)


@pytest.mark.asyncio
async def test_build_once_media_selection_persists_exact_top_ranked_candidate(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase H.1 §9 (build-once test): candidate (and its media ranking) is computed exactly once;
    the persisted `selected_media_plan` matches the real top-ranked eligible candidate; synthesis
    still uses the SAME precomputed candidate; exactly one Gateway call."""
    import services.event_recap_processor as processor_module

    story, events = await _seed_ready_story(db_session)
    await _seed_image_candidate(
        db_session, events[1].id, candidate_id="weak-logo", quality_score=45, relevance_score=41,
        width=128, height=128, image_format="GIF", warnings=["possible_branded_screenshot"],
    )
    await _seed_image_candidate(
        db_session, events[2].id, candidate_id="strong-hero", quality_score=98, relevance_score=67,
    )

    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)

    real_build = processor_module.build_event_recap_candidate
    build_call_count = 0

    async def _counting_build(*args, **kwargs):
        nonlocal build_call_count
        build_call_count += 1
        return await real_build(*args, **kwargs)

    monkeypatch.setattr(processor_module, "build_event_recap_candidate", _counting_build)

    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    assert outcome.status == "generated"
    assert build_call_count == 1  # media ranking rides the SAME single build() call
    assert len(gateway.received_requests) == 1

    task = await db_session.get(EditorialTask, outcome.task_id)
    media_result = _media_step_result(task)
    assert media_result["result"]["tier"] == "story_pool"
    assert media_result["result"]["representative"]["candidate_id"] == "strong-hero"

    synth_result = next(r for r in task.workflow["step_results"] if r["step_name"] == "synthesize_recap")
    assert synth_result["status"] == "SUCCESS"
    assert synth_result["result"] == _VALID_RECAP_OUTPUT
