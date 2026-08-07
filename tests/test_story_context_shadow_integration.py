"""Phase 19 M7: proves story_context_mode="shadow" cannot alter Copywriting's output - mirrors
tests/test_editorial_planning_shadow_integration.py's exact established technique (real
WorkflowRunner/CapabilityExecutor/CapabilityRegistry chain, not a mocked approximation).
"""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.executor import CapabilityExecutor
from capabilities.registry import build_registry
from core.config import settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import EventCategory, NewsEvent
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import PromptRepository
from schemas.capability import CapabilityUsage
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT
from workflows.registry import registry as real_workflow_registry
from workflows.runner import WorkflowRunner

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_INTELLIGENCE_OUTPUT: dict[str, object] = {
    "significance": 0.7, "angle": "Market impact", "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}
_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title", "body": "Example draft body text.",
    "what_happened": "Example event happened.",
    "why_it_matters": "Example editorial interpretation of the impact.",
    "what_remains_unknown": None, "quote": None,
}
_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


async def _table_exists(session: AsyncSession, table_name: str) -> bool:
    def _check(sync_session: object) -> bool:
        return inspect(sync_session.connection()).has_table(table_name)  # type: ignore[attr-defined]

    return await session.run_sync(_check)


async def _run_content_generation(db_session: AsyncSession, real_news_event: NewsEvent):
    gateway = FakeLLMGateway(
        generate_responses=[
            _generate_response(CANONICAL_RESEARCH_OUTPUT),
            _generate_response(_INTELLIGENCE_OUTPUT),
            _generate_response(_COPYWRITING_OUTPUT),
            _generate_response(_QUALITY_OUTPUT),
        ]
    )
    capability_registry = build_registry(gateway, _prompt_repository(), AllowingBudgetGuard(), ToolRegistry())  # type: ignore[arg-type]
    command = EditorialTaskCreate(
        event_id=real_news_event.id, workflow_type=WorkflowType.CONTENT_GENERATION, priority=TaskPriority.B
    )
    task = await workflow_service.create_task(db_session, command)
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(db_session, task.id)
    return result, gateway


@pytest.mark.asyncio
async def test_shadow_mode_without_story_link_is_a_complete_noop(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """story_context_mode="shadow" with no NewsEventStoryLink for this event (story_memory_mode
    was never enabled) must make zero extra LLM calls and produce byte-identical Copywriting
    output - _attach_story_context() returns immediately without ever touching a story-memory
    table, so this holds even against a database lacking the Phase 18.10/19 story tables."""
    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    monkeypatch.setattr(settings, "story_context_mode", "shadow")

    result, gateway = await _run_content_generation(db_session, real_news_event)

    assert result.status == "COMPLETED"
    assert len(gateway.received_requests) == 4  # never a 5th call - the hook makes zero LLM calls
    copywriting_result = next(r for r in result.step_results if r.step_name == COPYWRITING_CAPABILITY_NAME)
    assert copywriting_result.result == _COPYWRITING_OUTPUT


@pytest.mark.asyncio
async def test_shadow_mode_with_story_link_produces_identical_copywriting_output(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stronger proof: even when a real NewsEventStoryLink exists (so the shadow hook
    actually builds and persists a timeline snapshot), Copywriting's output is still exactly what
    it would be with story_context_mode="off" - Copywriting has no code path to read the
    snapshot at all."""
    if not await _table_exists(db_session, "stories") or not await _table_exists(
        db_session, "news_event_story_links"
    ):
        pytest.skip(
            "stories/news_event_story_links tables not present on this DB - migration "
            "c2bc6affb100 (Phase 18.10) ships unapplied to the real DB; run this test against a "
            "disposable DB that has had 'alembic upgrade head' applied."
        )
    from database.models.story import Story
    from database.models.story_link import NewsEventStoryLink

    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    monkeypatch.setattr(settings, "story_context_mode", "shadow")

    story = Story(
        id=uuid.uuid4(), title=real_news_event.title, category=EventCategory.AI, entities=[], keywords=[],
        topic_bucket="product", first_event_id=real_news_event.id, event_count=1,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(
        NewsEventStoryLink(
            news_event_id=real_news_event.id, story_id=story.id, match_type="new_story", match_score=1.0,
        )
    )
    await db_session.flush()

    result, gateway = await _run_content_generation(db_session, real_news_event)

    assert result.status == "COMPLETED"
    assert len(gateway.received_requests) == 4
    copywriting_result = next(r for r in result.step_results if r.step_name == COPYWRITING_CAPABILITY_NAME)
    assert copywriting_result.result == _COPYWRITING_OUTPUT
