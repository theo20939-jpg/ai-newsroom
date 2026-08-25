"""Unit tests for capabilities.final_post_authoring_capability.FinalPostAuthoringCapability -
Phase I.1. Mirrors tests/test_article_generation_capability.py's own FakeLLMGateway +
FakePromptRepository convention exactly (Phase 8 contract §15.1-§15.4). No DB, no network.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import CapabilityConfigurationError, RetryableCapabilityError, ValidationCapabilityError
from capabilities.final_post_authoring_capability import (
    CAPABILITY_NAME,
    FINAL_POST_AUTHORING_CAPABILITY_DEFINITION,
    FinalPostAuthoringCapability,
)
from database.models.ai_execution import AICapability
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

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"title": {"type": "string"}, "body": {"type": "string"}},
    "required": ["title", "body"],
    "additionalProperties": False,
}

_VALID_OUTPUT = {"title": "A public news title", "body": "A public news body, in prose."}

_BUNDLE = {
    "source_event_recap_task_id": str(uuid4()),
    "source_event_recap_review_id": str(uuid4()),
    "story_id": str(uuid4()),
    "anchor_event_id": str(uuid4()),
    "approved_recap": {
        "recap_title": "Approved recap title",
        "recap_summary": "Approved recap summary sentence.",
        "key_takeaways": ["First development.", "Second development."],
        "uncertainty_notes": ["It remains unclear whether X will happen."],
    },
    "verified_facts": [{"fact_type": "numeric", "value": "42", "source_event_ids": [], "source_count": 2, "status": "MULTI_SOURCE_CONFIRMED", "conflicting_evidence": False}],
    "source_refs": ["example.com"],
    "selected_media_plan": {"tier": "none", "representative": None},
    "legacy_snapshot_missing": False,
    "language": "ru",
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="1", system="You are a fake final-post copywriter.",
            rules=["Never invent facts."], output_schema=_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(*, bundle: dict | None = _BUNDLE) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Anchor event", summary=None, content="raw content that must never be read",
                url=None, category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="FINAL_POST_AUTHORING", workflow_version=1, completed_steps=[],
            ),
            final_post_authoring_bundle=bundle,
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.C, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def test_capability_definition_matches_the_real_authoring_contract():
    assert FINAL_POST_AUTHORING_CAPABILITY_DEFINITION.name == "final_post_authoring"
    assert FINAL_POST_AUTHORING_CAPABILITY_DEFINITION.expected_output_keys == ["title", "body"]


def test_capability_maps_to_an_existing_ai_capability_never_a_new_enum_value():
    assert resolve_ai_capability("final_post_authoring") == AICapability.COPYWRITING


@pytest.mark.asyncio
async def test_execute_raises_when_bundle_missing():
    """Fail-fast contract: no context.business.final_post_authoring_bundle ->
    CapabilityConfigurationError, zero Gateway calls."""
    gateway = FakeLLMGateway()
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context(bundle=None))

    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_execute_returns_real_authoring_output_and_records_exactly_one_gateway_call():
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(gateway.received_requests) == 1
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"
    assert result.calls[0].gateway_method == "generate"


@pytest.mark.asyncio
async def test_request_carries_approved_recap_text_never_raw_news_event_content():
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    await capability.execute(_context())

    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "raw content that must never be read" not in sent_text
    assert "Approved recap title" in sent_text
    assert "Approved recap summary sentence." in sent_text
    assert "First development." in sent_text
    assert "It remains unclear whether X will happen." in sent_text
    assert "42" in sent_text


@pytest.mark.asyncio
async def test_request_never_includes_media_plan_or_source_refs():
    """Instruction item 8: media/source-ref metadata is a provenance pointer, never LLM-facing
    editorial content."""
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=_VALID_OUTPUT, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    await capability.execute(_context())

    sent_text = gateway.received_requests[0].messages[-1].content[0].text
    assert "example.com" not in sent_text
    assert "story_pool" not in sent_text and "branded_fallback" not in sent_text


@pytest.mark.asyncio
async def test_missing_required_key_raises_validation_error():
    incomplete = {"title": "Only a title"}
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=incomplete, finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=50),
        )
    )
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


@pytest.mark.asyncio
async def test_truncated_response_raises_retryable_error():
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output=None, finish_reason="length", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=100, output_tokens=900),
        )
    )
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    with pytest.raises(RetryableCapabilityError):
        await capability.execute(_context())


@pytest.mark.asyncio
async def test_gateway_failure_raises_a_capability_error():
    from integrations.llm_gateway.errors import NoRoutableCandidateError

    gateway = FakeLLMGateway(generate_error=NoRoutableCandidateError("no routable candidate"))
    capability = FinalPostAuthoringCapability(gateway, _prompt_repository())

    # capabilities/gateway_call.py::_classify_gateway_error() translates NoRoutableCandidateError
    # into CapabilityConfigurationError - this capability raises that classified error as-is
    # (mirrors capabilities/article_generation_capability.py's own `raise outcome.error`).
    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context())

    assert len(gateway.received_requests) == 1
