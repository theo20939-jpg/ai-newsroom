"""Phase 19 M4: proves capabilities.copywriting_capability.CopywritingCapability.execute() reads
settings.copywriting_prompt_version at call time (not a fixed constant), and that the default
("4") is byte-identical to pre-Phase-19 behavior. Unit-tier only: FakeLLMGateway +
FakePromptRepository, zero real network/LLM calls.
"""
from uuid import uuid4

import pytest

from capabilities.copywriting_capability import CAPABILITY_NAME, CopywritingCapability
from core.config import settings
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

_V4_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "body": {"type": "string"},
        "what_happened": {"type": "string"}, "why_it_matters": {"type": "string"},
        "what_remains_unknown": {"type": ["string", "null"]}, "quote": {"type": ["object", "null"]},
    },
    "required": ["title", "body", "what_happened", "why_it_matters", "what_remains_unknown", "quote"],
}
_V5_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"}, "opening": {"type": "string"}, "context": {"type": "string"},
        "why_it_matters": {"type": "string"}, "what_changed": {"type": "string"},
        "what_happens_next": {"type": ["string", "null"]}, "conclusion": {"type": "string"},
        "what_remains_unknown": {"type": ["string", "null"]}, "quote": {"type": ["object", "null"]},
    },
    "required": [
        "title", "opening", "context", "why_it_matters", "what_changed", "what_happens_next",
        "conclusion", "what_remains_unknown", "quote",
    ],
}
_V4_OUTPUT = {
    "title": "V4 title", "body": "V4 body.", "what_happened": "x", "why_it_matters": "y",
    "what_remains_unknown": None, "quote": None,
}
_V5_OUTPUT = {
    "title": "V5 title", "opening": "A strong opening.", "context": "Some context.",
    "why_it_matters": "y", "what_changed": "z", "what_happens_next": None,
    "conclusion": "A short conclusion.", "what_remains_unknown": None, "quote": None,
}


def _dual_version_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="4", system="fake v4 system", rules=["r"],
            output_schema=_V4_SCHEMA,
        )
    )
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="5", system="fake v5 system", rules=["r"],
            output_schema=_V5_SCHEMA,
        )
    )
    return repository


def _context() -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="t", summary=None, content="c", url=None, category="AI",
                published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation", workflow_version=1, completed_steps=[],
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME, priority=TaskPriority.B,
            attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def _response(structured_output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output, finish_reason="stop",
        model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=10, output_tokens=5),
    )


@pytest.mark.asyncio
async def test_default_setting_resolves_v4_byte_identical_to_pre_phase19(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert settings.copywriting_prompt_version == "4"  # the shipped default, unchanged
    gateway = FakeLLMGateway(generate_response=_response(_V4_OUTPUT))
    capability = CopywritingCapability(gateway, _dual_version_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _V4_OUTPUT
    assert set(result.structured_output) == {"title", "body", "what_happened", "why_it_matters", "what_remains_unknown", "quote"}


@pytest.mark.asyncio
async def test_setting_v5_resolves_the_v5_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "copywriting_prompt_version", "5")
    gateway = FakeLLMGateway(generate_response=_response(_V5_OUTPUT))
    capability = CopywritingCapability(gateway, _dual_version_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _V5_OUTPUT
    assert "opening" in result.structured_output
    assert "what_changed" in result.structured_output
    assert "body" not in result.structured_output


@pytest.mark.asyncio
async def test_v5_request_schema_sent_to_gateway_matches_v5_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "copywriting_prompt_version", "5")
    gateway = FakeLLMGateway(generate_response=_response(_V5_OUTPUT))
    capability = CopywritingCapability(gateway, _dual_version_repository())

    await capability.execute(_context())

    assert len(gateway.received_requests) == 1
    assert gateway.received_requests[0].response_schema == _V5_SCHEMA
