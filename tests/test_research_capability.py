"""Tests for capabilities.research_capability.ResearchCapability (Phase 9 M4).

Unit-tier: `FakeLLMGateway` + `FakePromptRepository` only, mirroring
`tests/test_scoring_capability.py`'s exact convention (Phase 8 contract §15.1-§15.4). The real
M2 `FilePromptRepository` against real `prompts/` content is exercised separately, in Phase 9's
own integration/boot-wiring tests (M6/M7).
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
from capabilities.research_capability import CAPABILITY_NAME, ResearchCapability
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
from tests.fakes.research_output import CANONICAL_RESEARCH_OUTPUT

_RESEARCH_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {"type": "array"},
        "confidence": {"type": "number"},
        "gaps": {"type": "array"},
    },
    "required": ["facts", "confidence", "gaps"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME,
            version="2",
            system="You are a fake research assistant for tests.",
            rules=["Do not invent facts."],
            output_schema=_RESEARCH_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(
    *, title: str = "Example headline", category: str = "technology", content: str | None = "Example body text."
) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(),
                title=title,
                summary=None,
                content=content,
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


def _valid_response(structured_output: dict[str, object] | None = None) -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output if structured_output is not None else CANONICAL_RESEARCH_OUTPUT,
        finish_reason="stop",
        model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=20, output_tokens=8),
    )


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = ResearchCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    # Locks ResearchCapability's real output shape to the one, single, named artifact both
    # this Capability's and IntelligenceCapability's (M5) tests are pinned to.
    assert result.structured_output == CANONICAL_RESEARCH_OUTPUT
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
            structured_output={"facts": []},  # missing required "confidence"/"gaps"
            finish_reason="stop",
            model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=20, output_tokens=8),
        )
    )
    capability = ResearchCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


def test_construction_accepts_only_gateway_and_prompt_repository() -> None:
    """§4.2/§4.3/§4.4: no BudgetGuard, no CostTracker in the constructor signature."""
    params = list(inspect.signature(ResearchCapability.__init__).parameters)

    assert params == ["self", "gateway", "prompt_repository"]


@pytest.mark.asyncio
async def test_repeated_execute_calls_produce_independent_uncontaminated_results() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = ResearchCapability(gateway, _prompt_repository())

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
    """No GatewayError may escape Capability.execute() - only the classified CapabilityError
    subtype, raised before the execute() boundary (mirrors ScoringCapability's own test)."""
    gateway = FakeLLMGateway(generate_error=gateway_error)
    capability = ResearchCapability(gateway, _prompt_repository())

    with pytest.raises(expected_capability_error):
        await capability.execute(_context())

    with pytest.raises(expected_capability_error) as exc_info:
        await capability.execute(_context())
    assert not isinstance(exc_info.value, type(gateway_error))


@pytest.mark.asyncio
async def test_failed_capability_call_is_preserved_via_logging_before_raising(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The generated CapabilityCall must be preserved on failure too - since execute() raises
    rather than returning a CapabilityResult on this path (§11.1), preservation happens via a
    structured log record emitted before the raise."""
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no candidates"))
    capability = ResearchCapability(gateway, _prompt_repository())

    with caplog.at_level(logging.INFO):
        with pytest.raises(CapabilityConfigurationError):
            await capability.execute(_context())

    failure_records = [r for r in caplog.records if r.message == "capability_call_failed"]
    assert len(failure_records) == 1
    assert getattr(failure_records[0], "status") == "FAILED"  # noqa: B009 - dynamic `extra=` field
    assert getattr(failure_records[0], "gateway_method") == "generate"  # noqa: B009


@pytest.mark.asyncio
async def test_scope_honesty_no_external_verification_browsing_or_tool_call() -> None:
    """Contract §8's binding scope clarification: ResearchCapability MUST NOT be documented or
    behave as performing external fact-checking, web browsing, or a tool call it structurally
    cannot perform. A regression guard, not just an implicit property."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = ResearchCapability(gateway, _prompt_repository())

    await capability.execute(_context())

    assert len(gateway.received_requests) == 1
    request = gateway.received_requests[0]
    assert request.tools is None
    assert request.tool_choice is None

    forbidden_terms = ("browse", "web search", "external source", "verify against", "fact-check")
    full_text = "\n".join(
        part.text for message in request.messages for part in message.content if part.text is not None
    ).lower()
    for term in forbidden_terms:
        assert term not in full_text
