"""Unit tests for capabilities.event_recap_capability.EventRecapCapability - NINJA PULSE RECAP
Phase R2 integration, Phase B.2. Mirrors tests/test_article_generation_capability.py's own
FakeLLMGateway + FakePromptRepository convention (Phase 8 contract §15.1-§15.4). Reuses
tests.test_event_recap._candidate_from_titles() for a real, in-memory EventRecapCandidate -
mirrors tests/test_telegraph_article_processor.py's own established cross-test-file helper-import
precedent (that file imports _seed_claimable_proposal from tests.test_telegraph_research_processor).
No DB, no network, no real LLM call - the FakeLLMGateway is the only "provider" ever reached.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import CapabilityConfigurationError, RetryableCapabilityError
from capabilities.event_recap_capability import (
    CAPABILITY_NAME,
    EVENT_RECAP_CAPABILITY_DEFINITION,
    EventRecapCapability,
)
from database.models.ai_execution import AICapability
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import NoRoutableCandidateError
from integrations.llm_gateway.protocol import GenerateResponse
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
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository
from tests.test_event_recap import _candidate_from_titles

_VALID_SYNTHESIS_OUTPUT = {
    "recap_title": "Example Recap Title",
    "recap_summary": "Example recap summary sentence.",
    "key_takeaways": ["First takeaway.", "Second takeaway."],
    "uncertainty_notes": [],
}


def _real_candidate():
    """A real, in-memory EventRecapCandidate - deterministically built, no DB, no LLM (the exact
    same helper tests/test_event_recap.py's own synthesis tests use)."""
    return _candidate_from_titles(
        ["Apple unveils new Watch Ultra priced at $999"], "Apple unveils new Watch Ultra",
    )


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


def _context(*, candidate=None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Anchor event", summary=None, content="raw content", url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="EVENT_RECAP", workflow_version=1, completed_steps=[],
            ),
            event_recap_candidate=candidate,
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.C, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def test_capability_definition_matches_the_real_recap_synthesis_contract():
    assert EVENT_RECAP_CAPABILITY_DEFINITION.name == "event_recap"
    assert EVENT_RECAP_CAPABILITY_DEFINITION.expected_output_keys == [
        "recap_title", "recap_summary", "key_takeaways", "uncertainty_notes",
    ]


def test_capability_maps_to_an_existing_ai_capability_never_a_new_enum_value():
    assert resolve_ai_capability("event_recap") == AICapability.INTELLIGENCE


@pytest.mark.asyncio
async def test_execute_raises_when_candidate_missing():
    """Fail-fast contract: no context.business.event_recap_candidate -> CapabilityConfigurationError,
    zero Gateway calls."""
    gateway = FakeLLMGateway()
    capability = EventRecapCapability(gateway, _prompt_repository())

    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context())

    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_execute_calls_synthesize_event_recap_with_the_real_candidate_and_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Proves the capability calls services.event_recap.synthesize_event_recap() itself (never a
    reimplementation) with exactly the candidate from context.business.event_recap_candidate, the
    real gateway/prompt_repository this capability holds, context.runtime unchanged, and a
    callable call_observer."""
    import capabilities.event_recap_capability as event_recap_capability_module

    candidate = _real_candidate()
    call_kwargs: dict = {}

    async def _fake_synthesize(candidate_arg, gateway_arg, prompt_repository_arg, *, runtime, call_observer=None):
        call_kwargs["candidate"] = candidate_arg
        call_kwargs["gateway"] = gateway_arg
        call_kwargs["prompt_repository"] = prompt_repository_arg
        call_kwargs["runtime"] = runtime
        call_kwargs["call_observer"] = call_observer
        from dataclasses import replace
        return replace(
            candidate_arg, recap_title="t", recap_summary="s", key_takeaways=[], uncertainty_notes=[],
        )

    monkeypatch.setattr(event_recap_capability_module, "synthesize_event_recap", _fake_synthesize)

    gateway = FakeLLMGateway()
    prompt_repository = _prompt_repository()
    capability = EventRecapCapability(gateway, prompt_repository)
    context = _context(candidate=candidate)

    result = await capability.execute(context)

    assert result.status == "SUCCESS"
    assert call_kwargs["candidate"] is candidate
    assert call_kwargs["gateway"] is gateway
    assert call_kwargs["prompt_repository"] is prompt_repository
    assert call_kwargs["runtime"] is context.runtime
    assert callable(call_kwargs["call_observer"])


@pytest.mark.asyncio
async def test_execute_returns_real_synthesis_output_and_records_the_gateway_call():
    """Full, real chain (no mocking of synthesize_event_recap itself): candidate ->
    synthesize_event_recap() -> call_generate() -> FakeLLMGateway -> structured_output. Proves,
    per the checkpoint's own required assertions:
      - the gateway is actually called (gateway.received_requests);
      - CapabilityResult.calls is populated (cost tracking is not lost);
      - the real recap_title/recap_summary/key_takeaways/uncertainty_notes reach structured_output."""
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_SYNTHESIS_OUTPUT, finish_reason="stop",
            model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability = EventRecapCapability(gateway, _prompt_repository())
    candidate = _real_candidate()

    result = await capability.execute(_context(candidate=candidate))

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_SYNTHESIS_OUTPUT
    # Gateway was actually called - exactly once.
    assert len(gateway.received_requests) == 1
    # Cost tracking is not lost: CapabilityResult.calls carries the real CapabilityCall
    # call_generate() produced internally to synthesize_event_recap() - never empty on success.
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"
    assert result.calls[0].gateway_method == "generate"


@pytest.mark.asyncio
async def test_execute_maps_synthesis_error_to_retryable_capability_error_with_calls_attached():
    """A real EventRecapSynthesisError (Gateway failure) must map to RetryableCapabilityError -
    WorkflowStepDefinition.max_attempts governs the retry budget at the workflow level, exactly
    like every other Capability. The failed CapabilityCall must still be attached to the raised
    error's own `calls` - cost tracking must not be lost on the error path either
    (capabilities/executor.py::CapabilityExecutor._record_cost() reads error.calls on failure)."""
    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no routable candidate"))
    capability = EventRecapCapability(gateway, _prompt_repository())
    candidate = _real_candidate()

    with pytest.raises(RetryableCapabilityError) as exc_info:
        await capability.execute(_context(candidate=candidate))

    assert len(exc_info.value.calls) == 1
    assert exc_info.value.calls[0].status == "FAILED"
