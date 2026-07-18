"""Tests for capabilities.quality_capability.QualityCapability (Phase 8 M7).

Mirrors tests/test_scoring_capability.py's shape exactly, using the M6 testing convention
(FakeLLMGateway + FakePromptRepository) - proves contract §14's zero-change extension
guarantee for real: this file is the only new test file M7 adds, and it never imports or
modifies anything from capabilities/scoring_capability.py.
"""
import inspect
from uuid import uuid4

import pytest

from capabilities.errors import UnknownCapabilityError, ValidationCapabilityError
from capabilities.quality_capability import CAPABILITY_NAME, QualityCapability
from capabilities.registry import build_registry
from capabilities.scoring_capability import CAPABILITY_NAME as SCORING_CAPABILITY_NAME
from capabilities.scoring_capability import ScoringCapability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.llm_gateway.tools.registry import ToolRegistry
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    CapabilityUsage,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_infra import AllowingBudgetGuard
from tests.fakes.fake_prompt_repository import FakePromptRepository

_QUALITY_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"passed": {"type": "boolean"}, "issues": {"type": "array"}},
    "required": ["passed", "issues"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="1",
            system="You are a fake quality-check assistant for tests.",
            rules=["Do not invent issues."],
            output_schema=_QUALITY_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context() -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title="Example headline",
                summary="A short summary.",
                content=None,
                url=None,
                category="technology",
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="daily_digest", workflow_version=1, completed_steps=[]
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(),
            event_id=uuid4(),
            capability_name=CAPABILITY_NAME,
            priority=TaskPriority.B,
            attempt=1,
            iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True, "issues": []},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == {"passed": True, "issues": []}
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error_not_silent_success() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": True},  # missing required "issues"
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    params = list(inspect.signature(QualityCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"passed": False, "issues": ["missing summary"]},
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = QualityCapability(gateway, _prompt_repository())

    first = await capability.execute(_context())
    second = await capability.execute(_context())

    assert first.calls[0].call_id != second.calls[0].call_id
    assert len(first.calls) == 1
    assert len(second.calls) == 1


# ---------------------------------------------------------------------------
# §14 zero-change extension guarantee, proven for real: both capabilities coexist correctly in
# the same sealed CapabilityRegistry, neither shadowing nor interfering with the other.
# ---------------------------------------------------------------------------


def test_scoring_and_quality_coexist_in_the_same_sealed_registry() -> None:
    registry = build_registry(
        gateway=None,  # type: ignore[arg-type] # never called - construction/resolution only
        prompt_repository=_prompt_repository(),
        budget_guard=AllowingBudgetGuard(),  # type: ignore[arg-type]
        tool_registry=ToolRegistry(),
    )

    scoring_definition, scoring_capability = registry.resolve(SCORING_CAPABILITY_NAME)
    quality_definition, quality_capability = registry.resolve(CAPABILITY_NAME)

    assert scoring_definition.name == SCORING_CAPABILITY_NAME
    assert isinstance(scoring_capability, ScoringCapability)
    assert quality_definition.name == CAPABILITY_NAME
    assert isinstance(quality_capability, QualityCapability)
    assert scoring_capability is not quality_capability

    with pytest.raises(UnknownCapabilityError):
        registry.resolve("no_such_capability")
