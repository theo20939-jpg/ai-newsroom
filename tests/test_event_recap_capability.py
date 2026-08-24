"""Unit tests for capabilities.event_recap_capability.EventRecapCapability - NINJA PULSE RECAP
Phase R2 integration, Phase A. Mirrors tests/test_article_generation_capability.py's own
FakeLLMGateway + FakePromptRepository convention (Phase 8 contract §15.1-§15.4). No DB, no
network, no real LLM call - proves Phase A's own "dormant registration only" contract, not any
real synthesis behavior (services/event_recap.py's own tests already cover that).
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


def _context() -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Anchor event", summary=None, content="raw content", url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="EVENT_RECAP", workflow_version=1, completed_steps=[],
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME,
            priority=TaskPriority.C, attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def test_capability_definition_matches_the_real_recap_output_schema_fields():
    assert EVENT_RECAP_CAPABILITY_DEFINITION.name == "event_recap"
    assert EVENT_RECAP_CAPABILITY_DEFINITION.expected_output_keys == [
        "recap_title", "recap_summary", "key_takeaways", "uncertainty_notes",
    ]


def test_capability_maps_to_an_existing_ai_capability_never_a_new_enum_value():
    assert resolve_ai_capability("event_recap") == AICapability.INTELLIGENCE


@pytest.mark.asyncio
async def test_execute_resolves_the_real_recap_prompt_then_raises_configuration_error():
    """Phase A's own explicit boundary: execute() proves the prompt-repository wiring resolves
    the exact (name, version) services.event_recap.synthesize_event_recap() itself would resolve,
    then raises CapabilityConfigurationError - it never fabricates a result and never reaches the
    LLM Gateway, because no capabilities/executor.py hook exists yet to supply a real Story/
    EventRecapCandidate (see the capability's own module docstring)."""
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
