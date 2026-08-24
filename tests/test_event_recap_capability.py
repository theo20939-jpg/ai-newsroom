"""Unit tests for capabilities.event_recap_capability.EventRecapCapability - NINJA PULSE RECAP
Phase R2 integration, Phase B.1. Mirrors tests/test_article_generation_capability.py's own
FakeLLMGateway + FakePromptRepository convention (Phase 8 contract §15.1-§15.4). No DB, no
network, no real LLM call - proves Phase B.1's own "deterministic execution plumbing only"
contract (missing evidence -> fail-fast; present evidence -> deterministic SUCCESS, zero Gateway
calls), not any real synthesis behavior (services/event_recap.py's own tests already cover that;
no synthesize_event_recap() call exists in this capability yet).
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from capabilities.capability_mapping import resolve_ai_capability
from capabilities.errors import CapabilityConfigurationError
from capabilities.event_recap_capability import (
    CAPABILITY_NAME,
    EVENT_RECAP_CAPABILITY_DEFINITION,
    EventRecapCapability,
)
from database.models.ai_execution import AICapability
from database.models.editorial_task import TaskPriority
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import (
    BusinessContext,
    CapabilityContext,
    ExecutionContext,
    NewsEventSnapshot,
    RuntimeContext,
    WorkflowExecutionStateSnapshot,
)
from services.event_recap import EVENT_RECAP_PROMPT_NAME, EVENT_RECAP_PROMPT_VERSION
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_FAKE_EVIDENCE_TEXT = (
    "Story: Example Story\n\n"
    "ANNOUNCEMENT CONTEXT:\n\n- [ORIGIN]\nExample headline\n\n"
    "TIMELINE (order of PUBLICATION only...):\n- 2026-01-01T00:00:00+00:00 | Example headline "
    "(sources: 1, supporting events: 1)\n\n"
    "VERIFIED FACTS (from stored evidence, not LLM-generated):\n- (none recorded)"
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


def _context(*, evidence_text: str | None = None) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Anchor event", summary=None, content="raw content", url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="EVENT_RECAP", workflow_version=1, completed_steps=[],
            ),
            event_recap_evidence_text=evidence_text,
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.C, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def test_capability_definition_matches_the_temporary_phase_b1_output_shape():
    """expected_output_keys must match what execute() actually returns TODAY (Phase B.1's own
    deterministic-plumbing shape, structured_output={"event_recap_evidence_preview": ...}) - not
    the eventual real recap_title/recap_summary/key_takeaways/uncertainty_notes synthesis
    contract, which lands only in Phase B.2 once synthesize_event_recap() is wired in."""
    assert EVENT_RECAP_CAPABILITY_DEFINITION.name == "event_recap"
    assert EVENT_RECAP_CAPABILITY_DEFINITION.expected_output_keys == ["event_recap_evidence_preview"]


def test_capability_maps_to_an_existing_ai_capability_never_a_new_enum_value():
    assert resolve_ai_capability("event_recap") == AICapability.INTELLIGENCE


@pytest.mark.asyncio
async def test_execute_resolves_the_real_recap_prompt_then_raises_when_evidence_missing():
    """Fail-fast contract: execute() proves the prompt-repository wiring resolves the exact
    (name, version) services.event_recap.synthesize_event_recap() itself would resolve, then
    raises CapabilityConfigurationError when context.business.event_recap_evidence_text is
    None/empty - it never fabricates a result and never reaches the LLM Gateway."""
    gateway = FakeLLMGateway()
    capability = EventRecapCapability(gateway, _prompt_repository())

    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context())

    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_execute_raises_configuration_error_not_some_other_capability_error():
    """A missing-context gap is a permanent configuration problem (maps to workflows.errors.
    PermanentStepFailureError - never retried), never RetryableCapabilityError/
    ValidationCapabilityError."""
    capability = EventRecapCapability(FakeLLMGateway(), _prompt_repository())
    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context())


@pytest.mark.asyncio
async def test_execute_raises_when_evidence_text_is_empty_string():
    """Empty string is treated the same as None (falsy check, not `is None`) - an executor bug
    that threads an empty string must still fail fast, never silently succeed with nothing."""
    capability = EventRecapCapability(FakeLLMGateway(), _prompt_repository())
    with pytest.raises(CapabilityConfigurationError):
        await capability.execute(_context(evidence_text=""))


@pytest.mark.asyncio
async def test_execute_returns_deterministic_success_with_evidence_preview_when_evidence_is_present():
    """Phase B.1's own actual contract: when capabilities/executor.py's EVENT_RECAP branch found a
    real deterministic candidate and threaded its rendered evidence text in, execute() returns
    SUCCESS with that exact text in structured_output - never calling synthesize_event_recap() or
    the LLM Gateway to get there."""
    gateway = FakeLLMGateway()
    capability = EventRecapCapability(gateway, _prompt_repository())

    result = await capability.execute(_context(evidence_text=_FAKE_EVIDENCE_TEXT))

    assert result.status == "SUCCESS"
    assert result.structured_output == {"event_recap_evidence_preview": _FAKE_EVIDENCE_TEXT}


@pytest.mark.asyncio
async def test_execute_makes_zero_gateway_calls_on_the_success_path():
    """Phase B.1 is deterministic execution plumbing only - the success path must never touch the
    LLM Gateway. Asserted two ways: the fake gateway recorded zero requests, and the returned
    CapabilityResult itself carries zero CapabilityCall entries."""
    gateway = FakeLLMGateway()
    capability = EventRecapCapability(gateway, _prompt_repository())

    result = await capability.execute(_context(evidence_text=_FAKE_EVIDENCE_TEXT))

    assert gateway.received_requests == []
    assert result.calls == []
