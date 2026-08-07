"""Tests for capabilities.editorial_planning_capability.EditorialPlanningCapability (Phase 19
M3). Unit-tier only: FakeLLMGateway + FakePromptRepository - zero real network/LLM calls, mirrors
tests/test_research_capability.py's exact convention.
"""
from uuid import uuid4

import pytest

from capabilities.editorial_planning_capability import CAPABILITY_NAME, EditorialPlanningCapability
from capabilities.errors import ValidationCapabilityError
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

_PLAN_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "central_fact": {"type": "string"},
        "what_changed": {"type": ["string", "null"]},
        "what_is_new": {"type": "string"},
        "why_it_matters": {"type": "string"},
        "essential_facts": {"type": "array", "items": {"type": "string"}},
        "secondary_facts_omittable": {"type": "array", "items": {"type": "string"}},
        "necessary_background": {"type": ["string", "null"]},
        "already_published_summary": {"type": ["string", "null"]},
        "must_not_repeat": {"type": ["string", "null"]},
        "story_classification": {"type": "string"},
        "headline_emphasis": {"type": "string"},
        "opening_emphasis": {"type": "string"},
        "what_remains_unknown": {"type": ["string", "null"]},
        "verified_quote_text": {"type": ["string", "null"]},
        "media_role_needed": {"type": "string"},
        "editorial_risks": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "central_fact", "what_changed", "what_is_new", "why_it_matters", "essential_facts",
        "secondary_facts_omittable", "necessary_background", "already_published_summary",
        "must_not_repeat", "story_classification", "headline_emphasis", "opening_emphasis",
        "what_remains_unknown", "verified_quote_text", "media_role_needed", "editorial_risks",
    ],
}

_VALID_OUTPUT = {
    "central_fact": "The company raised five million dollars.", "what_changed": None,
    "what_is_new": "A new funding round.", "why_it_matters": "It funds their next product.",
    "essential_facts": ["Raised $5M"], "secondary_facts_omittable": [],
    "necessary_background": None, "already_published_summary": None, "must_not_repeat": None,
    "story_classification": "new_story", "headline_emphasis": "Funding round",
    "opening_emphasis": "The company raised funds.", "what_remains_unknown": None,
    "verified_quote_text": None, "media_role_needed": "none", "editorial_risks": [],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="1", system="You are a fake editorial planner for tests.",
            rules=["Ground every field in the evidence."], output_schema=_PLAN_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(*, content: str | None = "Example body text.") -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Example headline", summary=None, content=content, url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation", workflow_version=1, completed_steps=["research", "intelligence"],
            ),
        ),
        runtime=RuntimeContext(
            task_id=uuid4(), event_id=uuid4(), capability_name=CAPABILITY_NAME, priority=TaskPriority.B,
            attempt=1, iteration_count=0,
        ),
        execution=ExecutionContext(),
    )


def _valid_response(structured_output: dict[str, object] | None = None) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=structured_output if structured_output is not None else _VALID_OUTPUT,
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=30, output_tokens=15),
    )


@pytest.mark.asyncio
async def test_execute_full_shape_end_to_end() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = EditorialPlanningCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"central_fact": "x"},  # missing everything else
            finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )
    )
    capability = EditorialPlanningCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())


@pytest.mark.asyncio
async def test_nullable_field_is_accepted_by_floor_validation() -> None:
    """The [type, "null"] union schema fields (what_changed, etc.) must not trip
    _floor_validate()'s type check - the exact isinstance(declared_type, str) guard this
    capability duplicates from copywriting_capability.py's own established fix."""
    output = dict(_VALID_OUTPUT)
    output["what_changed"] = "A genuine update to an existing story."
    gateway = FakeLLMGateway(generate_response=_valid_response(output))
    capability = EditorialPlanningCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output["what_changed"] == "A genuine update to an existing story."
