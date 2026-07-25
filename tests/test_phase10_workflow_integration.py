"""Phase 10 M2: CONTENT_GENERATION integration proof.

Proves the real, production `research -> intelligence -> copywriting -> quality` chain
(`workflows/definitions/content_generation.py`, as amended by this milestone) executes in that
exact order through the real, unmodified `WorkflowRunner`/`CapabilityExecutor`/
`CapabilityRegistry`, and reaches `TaskStatus.COMPLETED` - mirrors
`tests/test_phase9_research_intelligence_integration.py`'s established technique, extended to
four steps. Unlike that file, this one uses the *real* `WorkflowType.CONTENT_GENERATION`
definition through the *real* `workflows.registry.registry` singleton - no synthetic
`WorkflowType` is needed, since Phase 10 M2's own production definition already declares the
proof's step order (Contract §12 "Workflow tests").

Phase 9.5 M1 already closed the same-pass `step_results` propagation gap
`test_phase9_research_intelligence_integration.py`'s own module docstring documents in detail:
`WorkflowRunner._execute_steps()` commits `task.workflow` once per successful step, so a later
step in the same pass observes an earlier step's result. This file relies on that fix directly,
without re-deriving it.

Never uses a live external LLM API (`FakeLLMGateway` only) - Contract §12/Phase 7 §15.5's
no-real-network-call discipline, unchanged.
"""
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from capabilities.copywriting_capability import CAPABILITY_NAME as COPYWRITING_CAPABILITY_NAME
from capabilities.executor import CapabilityExecutor
from capabilities.intelligence_capability import CAPABILITY_NAME as INTELLIGENCE_CAPABILITY_NAME
from capabilities.quality_capability import CAPABILITY_NAME as QUALITY_CAPABILITY_NAME
from capabilities.registry import build_registry
from capabilities.research_capability import CAPABILITY_NAME as RESEARCH_CAPABILITY_NAME
from core.config import settings
from database.models.news_event import NewsEvent
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
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
    "significance": 0.7,
    "angle": "Market impact",
    "audience_relevance": "General audience",
    "recommendation": "Publish with standard priority",
}

_COPYWRITING_OUTPUT: dict[str, object] = {
    "title": "Example draft title",
    "body": "Example draft body text.",
    "hashtags": ["#example", "#news"],
}

_QUALITY_OUTPUT: dict[str, object] = {"passed": True, "issues": []}


def _prompt_repository() -> PromptRepository:
    return FilePromptRepository(_PROMPTS_ROOT)


def _generate_response(structured_output: dict[str, object]) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


def _request_text(request: GenerateRequest) -> str:
    return "\n".join(part.text for message in request.messages for part in message.content if part.text)


@pytest.mark.asyncio
async def test_content_generation_reaches_completed_in_exact_step_order(
    db_session: AsyncSession, real_news_event: NewsEvent, monkeypatch: pytest.MonkeyPatch
) -> None:
    """1. Research output is available to Intelligence.
    2. Upstream results are available to Copywriting as defined by its contract.
    3. Copywriting output is available to Quality in the same uninterrupted workflow execution.
    4. Quality actually receives/evaluates the generated Copywriting content.
    5. The workflow reaches COMPLETED when all four capabilities succeed.

    Never claims ContentDraft persistence (M3's own, not-yet-built responsibility).

    Phase 15 M5 isolation: `fact_safety_mode` defaults to "shadow" (unlike
    `editorial_scoring_version`'s own "v1"/off default), so it is explicitly pinned to "off"
    here - this test asserts on QualityCapability's own, unmodified step_results shape, a
    Phase 10 concern predating and unrelated to M5's own cross-cutting "quality"-step hook."""
    monkeypatch.setattr(settings, "fact_safety_mode", "off")
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
    task = await workflow_service.create_task(db_session, command)  # real, default WorkflowRegistry
    executor = CapabilityExecutor(db_session, task.id, capability_registry)
    result = await WorkflowRunner(executor=executor, registry=real_workflow_registry).run(db_session, task.id)

    # 5. Reaches COMPLETED, in the exact declared order.
    assert result.status == "COMPLETED"
    assert [r.step_name for r in result.step_results] == [
        RESEARCH_CAPABILITY_NAME,
        INTELLIGENCE_CAPABILITY_NAME,
        COPYWRITING_CAPABILITY_NAME,
        QUALITY_CAPABILITY_NAME,
    ]
    for step_result in result.step_results:
        assert step_result.status == "SUCCESS"
    assert result.step_results[0].result == CANONICAL_RESEARCH_OUTPUT
    assert result.step_results[1].result == _INTELLIGENCE_OUTPUT
    assert result.step_results[2].result == _COPYWRITING_OUTPUT
    assert result.step_results[3].result == _QUALITY_OUTPUT
    assert len(gateway.received_requests) == 4

    # 1. Research's output is available to Intelligence (received_requests[1] = Intelligence's).
    intelligence_request_text = _request_text(gateway.received_requests[1])
    canonical_facts = CANONICAL_RESEARCH_OUTPUT["facts"]
    assert isinstance(canonical_facts, list)
    for fact in canonical_facts:
        assert fact in intelligence_request_text
    assert "did not run" not in intelligence_request_text.lower()

    # 2. Research's AND Intelligence's output are both available to Copywriting
    #    (received_requests[2] = Copywriting's).
    copywriting_request_text = _request_text(gateway.received_requests[2])
    for fact in canonical_facts:
        assert fact in copywriting_request_text
    assert str(_INTELLIGENCE_OUTPUT["angle"]) in copywriting_request_text
    assert str(_INTELLIGENCE_OUTPUT["recommendation"]) in copywriting_request_text
    assert "did not run" not in copywriting_request_text.lower()

    # 3./4. Copywriting's own generated draft is available to, and actually evaluated by,
    #    Quality (received_requests[3] = Quality's) - the central proof this milestone adds.
    quality_request_text = _request_text(gateway.received_requests[3])
    assert str(_COPYWRITING_OUTPUT["title"]) in quality_request_text
    assert str(_COPYWRITING_OUTPUT["body"]) in quality_request_text
    assert "did not run" not in quality_request_text.lower()
