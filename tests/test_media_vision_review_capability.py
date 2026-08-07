"""Tests for capabilities.media_vision_review_capability.MediaVisionReviewCapability (Phase 19
M13). Unit-tier only: FakeLLMGateway + FakePromptRepository - zero real network/LLM calls, mirrors
tests/test_editorial_planning_capability.py's exact convention.
"""
from uuid import uuid4

import pytest

from capabilities.errors import ValidationCapabilityError
from capabilities.media_vision_review_capability import CAPABILITY_NAME, MediaVisionReviewCapability
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

_REVIEW_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant_to_story": {"type": "boolean"},
        "source_logo_present": {"type": "boolean"},
        "watermark_present": {"type": "boolean"},
        "website_or_social_ui_present": {"type": "boolean"},
        "advertisement_or_banner_present": {"type": "boolean"},
        "readable_quality": {"type": "string"},
        "recommended_role": {"type": "string"},
    },
    "required": [
        "relevant_to_story", "source_logo_present", "watermark_present",
        "website_or_social_ui_present", "advertisement_or_banner_present", "readable_quality",
        "recommended_role",
    ],
}

_VALID_OUTPUT = {
    "relevant_to_story": True, "source_logo_present": False, "watermark_present": False,
    "website_or_social_ui_present": False, "advertisement_or_banner_present": False,
    "readable_quality": "good", "recommended_role": "hero",
}

_FAKE_DATA_URI = "data:image/jpeg;base64,ZmFrZS1pbWFnZS1ieXRlcw=="


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="1", system="You are a fake vision reviewer for tests.",
            rules=["Answer only about what is visible."], output_schema=_REVIEW_OUTPUT_SCHEMA,
        )
    )
    return repository


def _context(*, image_data_uri: str | None = _FAKE_DATA_URI) -> CapabilityContext:
    return CapabilityContext(
        business=BusinessContext(
            news_event=NewsEventSnapshot(
                id=uuid4(), title="Example headline", summary=None, content="Example body", url=None,
                category="technology", published_at=None,
            ),
            workflow_state=WorkflowExecutionStateSnapshot(
                workflow_name="content_generation", workflow_version=1, completed_steps=[],
            ),
            media_review_image_data_uri=image_data_uri, media_review_story_summary="Example headline",
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
    capability = MediaVisionReviewCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1
    assert result.calls[0].status == "SUCCESS"


@pytest.mark.asyncio
async def test_request_carries_the_image_as_an_artifact_ref_content_part() -> None:
    """Proves the request actually reaches the gateway with an image ContentPart, not merely
    text - the whole point of this capability being the first real vision-input consumer."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MediaVisionReviewCapability(gateway, _prompt_repository())

    await capability.execute(_context())

    request = gateway.received_requests[0]
    assert "image" in request.modalities
    user_message = next(m for m in request.messages if m.role == "user")
    artifact_parts = [p for p in user_message.content if p.type == "artifact_ref"]
    assert len(artifact_parts) == 1
    assert artifact_parts[0].artifact_ref == _FAKE_DATA_URI


@pytest.mark.asyncio
async def test_missing_image_raises_validation_error_without_calling_the_gateway() -> None:
    """The structural guarantee: this capability must never be invoked without a real image -
    see its own module docstring."""
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MediaVisionReviewCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context(image_data_uri=None))

    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"relevant_to_story": True},  # missing everything else
            finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )
    )
    capability = MediaVisionReviewCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())
