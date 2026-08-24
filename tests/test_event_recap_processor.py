"""NINJA PULSE RECAP Phase R2 integration, Phase C.0: services.event_recap_processor.
generate_recap_for_story() - Story lookup -> EVENT_RECAP EditorialTask creation (or duplicate-task
lookup) -> real WorkflowRunner run through CapabilityExecutor -> EventRecapCapability ->
synthesize_event_recap() -> FakeLLMGateway. Mirrors tests/test_telegraph_article_processor.py's
own established shape/fixtures exactly (real Postgres via the db_session fixture, FakeLLMGateway,
zero network/cost) - no real LLM call anywhere in this file.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.event_recap_capability import EVENT_RECAP_CAPABILITY_DEFINITION, EventRecapCapability
from capabilities.registry import CapabilityRegistry
from database.models.editorial_task import EditorialTask
from database.models.news_event import EventCategory, NewsEvent
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


async def _seed_story(session: AsyncSession) -> tuple[Story, NewsEvent]:
    """A real NewsSource + NewsEvent + Story (first_event_id=event.id) + confirmed
    NewsEventStoryLink - just enough for build_event_recap_candidate() to succeed for real
    (single-event Story, force_shadow=True bypasses the readiness-not-ready rejection; Story
    Integrity has nothing to reject with only one member event)."""
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
    story, event = await _seed_story(db_session)
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

    task = await db_session.get(EditorialTask, outcome.task_id)
    assert task is not None
    assert task.event_id == event.id  # anchored to story.first_event_id, exactly like TELEGRAPH_ARTICLE
    assert task.workflow["workflow_name"] == "EVENT_RECAP"

    step_result = next(r for r in task.workflow["step_results"] if r["step_name"] == "synthesize_recap")
    assert step_result["status"] == "SUCCESS"
    assert step_result["result"] == _VALID_RECAP_OUTPUT
    assert len(gateway.received_requests) == 1  # the Gateway was actually reached, exactly once


@pytest.mark.asyncio
async def test_second_attempt_reuses_existing_task_no_new_paid_call(db_session: AsyncSession) -> None:
    story, _event = await _seed_story(db_session)
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
    story, event = await _seed_story(db_session)
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_RECAP_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    registry = _registry(gateway)
    outcome = await generate_recap_for_story(db_session, story.id, capability_registry=registry)

    found = await find_event_recap_task_id(db_session, event.id)

    assert found == outcome.task_id
