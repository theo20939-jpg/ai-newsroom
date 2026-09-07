"""DIRECTOR-CONTROL-PLANE-1 §26/§53: a final visual that ambiguously changes the key factual
metric must BLOCK, never PASS_WITH_NOTES - a deterministic backstop on top of whatever decision
the vision model itself returns."""
from __future__ import annotations

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.telegram_art_director import ArtDirectorDecision, ArtDirectorIssueCode, PixelInputContract
from services.telegram_art_director_vision import VISION_PROMPT_NAME, VISION_PROMPT_VERSION, evaluate_art_direction_vision
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_VISION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "decision": {"type": "string"}, "severity": {"type": "string"},
        "issues": {"type": "array"}, "overall_confidence": {"type": "number"},
    },
    "required": ["decision", "severity", "issues", "overall_confidence"],
}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=VISION_PROMPT_NAME, version=VISION_PROMPT_VERSION,
        system="Fake Art Director for tests.", rules=["Use only provided codes."],
        output_schema=_VISION_OUTPUT_SCHEMA,
    ))
    return repository


@pytest.mark.asyncio
async def test_number_mismatch_forces_block_even_if_model_said_pass_with_notes() -> None:
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={
            "decision": "pass_with_notes",  # the model under-called it
            "severity": "low",
            "issues": [{
                "code": "number_mismatch", "description": "source shows 42% but overlay reads 142%",
                "confidence": 0.7, "recommended_action": "block",
            }],
            "overall_confidence": 0.6,
        },
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=40, output_tokens=20),
    ))
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes", caption="42% improvement", presentation_type="DATA", renderer_version="v1",
    )

    result = await evaluate_art_direction_vision(gateway, _prompt_repository(), pixel_input=pixel_input)

    assert result.decision == ArtDirectorDecision.BLOCK
    assert ArtDirectorIssueCode.NUMBER_MISMATCH in result.issue_codes


@pytest.mark.asyncio
async def test_no_number_mismatch_leaves_model_decision_untouched() -> None:
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None,
        structured_output={"decision": "pass_with_notes", "severity": "low", "issues": [], "overall_confidence": 0.8},
        finish_reason="stop", model_used="fake-vision-v1", usage=CapabilityUsage(input_tokens=40, output_tokens=20),
    ))
    pixel_input = PixelInputContract(
        rendered_bytes=b"fake-bytes", caption="clean image", presentation_type="NEWS", renderer_version="v1",
    )
    result = await evaluate_art_direction_vision(gateway, _prompt_repository(), pixel_input=pixel_input)
    assert result.decision == ArtDirectorDecision.PASS_WITH_NOTES
