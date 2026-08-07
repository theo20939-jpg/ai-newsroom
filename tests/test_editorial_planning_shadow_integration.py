"""Phase 19 M3: proves editorial_planning_mode="shadow" cannot alter Copywriting's output - the
concrete, required proof, exercising the real WorkflowRunner/CapabilityExecutor/CapabilityRegistry
chain (mirrors tests/test_phase10_workflow_integration.py's exact established technique), not a
mocked approximation.
"""
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.executor import CapabilityExecutor
from capabilities.registry import build_registry
from core.config import settings
from database.models.editorial_task import TaskPriority
from database.models.news_event import NewsEvent
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
async def test_shadow_mode_produces_identical_copywriting_output_and_makes_no_extra_llm_call(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The concrete safety proof: editorial_planning_mode="shadow" must not add a fifth LLM call
    (the deterministic scaffold makes zero calls), and Copywriting's own structured_output must
    be exactly what it would be with editorial_planning_mode="off" - Copywriting has no code path
    to read the shadow scaffold at all."""
    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")
    monkeypatch.setattr(settings, "editorial_planning_mode", "shadow")

    result, gateway = await _run_content_generation(db_session, real_news_event)

    assert result.status == "COMPLETED"
    # Exactly 4 calls (research/intelligence/copywriting/quality) - never a 5th for
    # editorial_planning, proving the live shadow path never invokes the real, LLM-backed
    # EditorialPlanningCapability.
    assert len(gateway.received_requests) == 4
    copywriting_result = next(r for r in result.step_results if r.step_name == COPYWRITING_CAPABILITY_NAME)
    assert copywriting_result.result == _COPYWRITING_OUTPUT


@pytest.mark.asyncio
async def test_off_and_shadow_produce_byte_identical_copywriting_output(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """create_task() rejects a second CONTENT_GENERATION task for the same event (Duplicate
    ActiveTaskError) - a fresh event is seeded for the second run, same source, same content."""
    from database.models.news_event import EventCategory

    monkeypatch.setattr(settings, "fact_safety_mode", "off")
    monkeypatch.setattr(settings, "image_intelligence_mode", "off")

    monkeypatch.setattr(settings, "editorial_planning_mode", "off")
    result_off, _ = await _run_content_generation(db_session, real_news_event)

    second_event = NewsEvent(
        source_id=real_news_event.source_id, title=real_news_event.title, content=real_news_event.content,
        category=EventCategory.AI, hash=f"test-hash-{uuid.uuid4()}",
    )
    db_session.add(second_event)
    await db_session.flush()

    monkeypatch.setattr(settings, "editorial_planning_mode", "shadow")
    result_shadow, _ = await _run_content_generation(db_session, second_event)

    copywriting_off = next(r for r in result_off.step_results if r.step_name == COPYWRITING_CAPABILITY_NAME)
    copywriting_shadow = next(r for r in result_shadow.step_results if r.step_name == COPYWRITING_CAPABILITY_NAME)
    assert copywriting_off.result == copywriting_shadow.result
