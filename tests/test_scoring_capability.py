"""Tests for capabilities.scoring_capability.ScoringCapability (Phase 8 M3, Golden Path).

Uses the real M1 mechanism (capabilities.gateway_call.call_generate, exercised indirectly
through execute()) - the Gateway and the PromptRepository are both fakes (tests.fakes.
fake_gateway.FakeLLMGateway, tests.fakes.fake_prompt_repository.FakePromptRepository),
per the Phase 8 M6 testing convention (contract §15.1-§15.4: a unit test that resolves a
prompt MUST use a fake PromptRepository, never a real, published prompt store). The real M2
FilePromptRepository against real prompts/ content is exercised separately, in
tests/test_capability_boot_wiring_e2e.py's end-to-end tier (§15.6).
"""
import inspect
import logging
from uuid import uuid4

import pytest

from capabilities.errors import (
    CapabilityConfigurationError,
    CapabilityError,
    PermanentCapabilityError,
    ValidationCapabilityError,
)
from capabilities.scoring_capability import CAPABILITY_NAME, ScoringCapability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import (
    AllProvidersFailedError,
    NoRoutableCandidateError,
    ProviderModerationBlockedError,
)
from integrations.llm_gateway.protocol import GenerateResponse, UnsupportedGatewayCapabilityError
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
from tests.fakes.fake_prompt_repository import FakePromptRepository

_SCORING_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"score": {"type": "integer"}, "rationale": {"type": "string"}},
    "required": ["score", "rationale"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="2",
            system="You are a fake scoring assistant for tests.",
            rules=["Do not invent facts."],
            output_schema=_SCORING_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(*, title: str = "Example headline", category: str = "technology") -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title=title,
                summary="A short summary of the event.",
                content=None,
                url=None,
                category=category,
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


def _valid_response(score: int = 72, rationale: str = "Broad relevance and timely coverage.") -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output={"score": score, "rationale": rationale},
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=20, output_tokens=8),
    )


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response(score=80, rationale="High impact story."))
    capability = ScoringCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == {"score": 80, "rationale": "High impact story."}
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"
    assert result.calls[0].gateway_method == "generate"
    assert result.calls[0].model_used == "fake-model-v1"
    assert result.started_at <= result.finished_at


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error_not_silent_success() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None,
            structured_output={"score": 80},  # missing required "rationale"
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = ScoringCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    """§4.2/§4.3/§4.4: no BudgetGuard, no CostTracker in the constructor signature."""
    params = list(inspect.signature(ScoringCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response(score=10, rationale="Low impact."))
    capability = ScoringCapability(gateway, _prompt_repository())

    first = await capability.execute(_context(title="Story A"))
    second = await capability.execute(_context(title="Story B"))

    assert first.calls[0].call_id != second.calls[0].call_id
    assert len(first.calls) == 1
    assert len(second.calls) == 1  # not accumulated across calls - no shared mutable state


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("gateway_error", "expected_capability_error"),
    [
        (NoRoutableCandidateError("no candidates"), CapabilityConfigurationError),
        (UnsupportedGatewayCapabilityError("unsupported"), CapabilityConfigurationError),
        (ProviderModerationBlockedError("blocked"), PermanentCapabilityError),
        (AllProvidersFailedError("exhausted", reason="all_candidates_failed"), PermanentCapabilityError),
    ],
)
async def test_gateway_errors_are_translated_never_escape_raw(
    gateway_error: Exception, expected_capability_error: type[CapabilityError]
) -> None:
    """Task #1 requirement: no GatewayError may escape Capability.execute() - only the
    classified CapabilityError subtype, raised before the execute() boundary."""
    gateway = FakeLLMGateway(generate_error=gateway_error)
    capability = ScoringCapability(gateway, _prompt_repository())

    with pytest.raises(expected_capability_error):
        await capability.execute(_context())

    # the raw GatewayError type itself must never be what's observed crossing the boundary
    with pytest.raises(expected_capability_error) as exc_info:
        await capability.execute(_context())
    assert not isinstance(exc_info.value, type(gateway_error))


@pytest.mark.asyncio
async def test_failed_capability_call_is_preserved_via_logging_before_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Task #1 requirement: the generated CapabilityCall must be preserved on failure too -
    since execute() raises rather than returning a CapabilityResult on this path (§11.1),
    preservation happens via a structured log record emitted before the raise."""
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability = ScoringCapability(gateway, _prompt_repository())

    with caplog.at_level(logging.INFO):
        with pytest.raises(CapabilityConfigurationError):
            await capability.execute(_context())

    failure_records = [r for r in caplog.records if r.message == "capability_call_failed"]
    assert len(failure_records) == 1
    assert getattr(failure_records[0], "status") == "FAILED"  # noqa: B009 - dynamic `extra=` field
    assert getattr(failure_records[0], "gateway_method") == "generate"  # noqa: B009
