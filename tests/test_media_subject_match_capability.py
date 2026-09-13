"""Tests for capabilities.media_subject_match_capability.MediaSubjectMatchCapability
(CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1). Unit-tier only: FakeLLMGateway + FakePromptRepository -
zero real network/LLM calls, mirrors tests/test_media_vision_review_capability.py's exact
convention (the sibling capability this one was built alongside)."""
from uuid import uuid4

import pytest

from capabilities.errors import ValidationCapabilityError
from capabilities.media_subject_match_capability import CAPABILITY_NAME, MediaSubjectMatchCapability
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
    "properties": {
        "depicted_subject_description": {"type": "string"},
        "subject_match": {"type": "string"},
        "must_not_imply_violated": {"type": "boolean"},
        "violated_statements": {"type": "array"},
        "confidence": {"type": "string"},
        "reason": {"type": "string"},
    },
    "required": [
        "depicted_subject_description", "subject_match", "must_not_imply_violated",
        "violated_statements", "confidence", "reason",
    ],
}

_VALID_OUTPUT = {
    "depicted_subject_description": "An ordinary iPhone, standard candy-bar form factor.",
    "subject_match": "mismatch",
    "must_not_imply_violated": True,
    "violated_statements": ["this is not a foldable device"],
    "confidence": "high",
    "reason": "The image shows a normal single-screen iPhone, not the foldable model the intent names.",
}

_FAKE_DATA_URI = "data:image/jpeg;base64,ZmFrZS1pbWFnZS1ieXRlcw=="


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(
        RenderedPrompt(
            name=CAPABILITY_NAME, version="1", system="You are a fake subject-match reviewer for tests.",
            rules=["Never assume brand similarity means exact match."], output_schema=_OUTPUT_SCHEMA,
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
            media_subject_match_image_data_uri=image_data_uri,
            media_subject_match_intent_summary="product=iPhone Duo (foldable), company=Apple",
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
    capability = MediaSubjectMatchCapability(gateway, _prompt_repository())

    result = await capability.execute(_context())

    assert result.status == "SUCCESS"
    assert result.structured_output == _VALID_OUTPUT
    assert len(result.calls) == 1


@pytest.mark.asyncio
async def test_request_carries_the_image_as_an_artifact_ref_content_part() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MediaSubjectMatchCapability(gateway, _prompt_repository())

    await capability.execute(_context())

    request = gateway.received_requests[0]
    assert "image" in request.modalities
    user_message = next(m for m in request.messages if m.role == "user")
    artifact_parts = [p for p in user_message.content if p.type == "artifact_ref"]
    assert len(artifact_parts) == 1
    assert artifact_parts[0].artifact_ref == _FAKE_DATA_URI


@pytest.mark.asyncio
async def test_missing_image_raises_validation_error_without_calling_the_gateway() -> None:
    gateway = FakeLLMGateway(generate_response=_valid_response())
    capability = MediaSubjectMatchCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context(image_data_uri=None))

    assert gateway.received_requests == []


@pytest.mark.asyncio
async def test_validation_failure_raises_validation_capability_error() -> None:
    gateway = FakeLLMGateway(
        generate_response=GenerateResponse(
            text=None, structured_output={"subject_match": "exact_subject"},  # missing everything else
            finish_reason="stop", model_used="fake-model-v1",
            usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        )
    )
    capability = MediaSubjectMatchCapability(gateway, _prompt_repository())

    with pytest.raises(ValidationCapabilityError):
        await capability.execute(_context())
