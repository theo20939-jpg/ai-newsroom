"""Tests for ScoringCapability's §10 structured-output correction retry (Phase 8 M5).

Separate from tests/test_scoring_capability.py (M3's own dedicated test file) - this file
exercises only the retry path, using the shared, now-sequence-configurable FakeLLMGateway and
FakePromptRepository (Phase 8 M6 testing convention, contract §15.1-§15.4).
"""
from uuid import uuid4

import pytest

from capabilities.errors import ValidationCapabilityError
from capabilities.scoring_capability import CAPABILITY_NAME, ScoringCapability
from database.models.editorial_task import TaskPriority
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
            version="1",
            system="You are a fake scoring assistant for tests.",
            rules=["Do not invent facts."],
            output_schema=_SCORING_OUTPUT_SCHEMA,
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


def _response(structured_output: dict[str, object] | None, model_used: str = "fake-model-v1") -> GenerateResponse:
    return GenerateResponse(
        text=None,
        structured_output=structured_output,
        finish_reason="stop",
        model_used=model_used,
        usage=CapabilityUsage(input_tokens=20, output_tokens=8),
    )


_MISMATCHED_RESPONSE = _response({"score": 80})  # missing required "rationale"
_VALID_RESPONSE = _response({"score": 80, "rationale": "Broad relevance."}, model_used="fake-model-v2")


@pytest.mark.asyncio
async def test_first_mismatch_triggers_exactly_one_retry_appending_correction_message() -> None:
    gateway = FakeLLMGateway(generate_responses=[_MISMATCHED_RESPONSE, _VALID_RESPONSE])
    capability = ScoringCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert len(gateway.received_requests) == 2
    first_request, retry_request = gateway.received_requests

    # the correction message is APPENDED, not a replacement - the retry's message list is a
    # strict superset of the first attempt's, with exactly one new message at the end.
    assert retry_request.messages[: len(first_request.messages)] == first_request.messages
    assert len(retry_request.messages) == len(first_request.messages) + 1
    assert retry_request.messages[-1].role == "user"

    # §10.2: "no re-routing" - preferred_model is pinned to the first attempt's resolved model.
    assert retry_request.preferred_model == "fake-model-v1"


@pytest.mark.asyncio
async def test_original_rendered_prompt_is_never_mutated_by_the_retry() -> None:
    prompt_repository = _prompt_repository()
    original_prompt = prompt_repository.resolve(CAPABILITY_NAME, "1")

    gateway = FakeLLMGateway(generate_responses=[_MISMATCHED_RESPONSE, _VALID_RESPONSE])
    capability = ScoringCapability(gateway, prompt_repository)

    await capability.execute(_context())

    # resolve() returns the same frozen, immutable object every time (M2) - if the retry had
    # mutated it in place, this identity/equality would break.
    assert prompt_repository.resolve(CAPABILITY_NAME, "1") is original_prompt
    assert prompt_repository.resolve(CAPABILITY_NAME, "1") == original_prompt


@pytest.mark.asyncio
async def test_successful_retry_result_carries_retry_reason_and_retried_call_id_metadata() -> None:
    gateway = FakeLLMGateway(generate_responses=[_MISMATCHED_RESPONSE, _VALID_RESPONSE])
    capability = ScoringCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert len(result.calls) == 2
    first_call, retry_call = result.calls
    assert first_call.sequence == 0
    assert retry_call.sequence == 1
    assert result.metadata == {
        "retry_reason": "schema_validation_failure",
        "retried_call_id": str(first_call.call_id),
    }


@pytest.mark.asyncio
async def test_second_consecutive_mismatch_raises_validation_error_with_no_third_call() -> None:
    gateway = FakeLLMGateway(generate_response=_MISMATCHED_RESPONSE)  # every call mismatches
    capability = ScoringCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())

    assert len(gateway.received_requests) == 2  # exactly one retry - no third attempt


@pytest.mark.asyncio
async def test_retry_success_path_returns_the_corrected_structured_output() -> None:
    gateway = FakeLLMGateway(generate_responses=[_MISMATCHED_RESPONSE, _VALID_RESPONSE])
    capability = ScoringCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == {"score": 80, "rationale": "Broad relevance."}
