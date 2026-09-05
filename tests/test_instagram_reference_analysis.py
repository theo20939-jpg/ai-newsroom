"""INSTAGRAM-GROWTH-3, item 12/19: AI-assisted Reference Deconstruction tests - originality
constraint enforced even on AI output."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.instagram_reference_analysis import (
    REFERENCE_ANALYSIS_PROMPT_NAME,
    REFERENCE_ANALYSIS_PROMPT_VERSION,
    ReferenceAnalysisUnavailableError,
    analyze_reference_with_ai,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_PROMPT = RenderedPrompt(
    name=REFERENCE_ANALYSIS_PROMPT_NAME, version=REFERENCE_ANALYSIS_PROMPT_VERSION,
    system="analyze the reference", rules=["must_not_copy required"],
    output_schema={"type": "object", "properties": {}, "required": []},
)


def test_real_prompt_file_loads() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(REFERENCE_ANALYSIS_PROMPT_NAME, REFERENCE_ANALYSIS_PROMPT_VERSION)
    assert "must_not_copy" in rendered.output_schema["properties"]


@pytest.mark.asyncio
async def test_ai_assisted_analysis_succeeds() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={
            "hook_mechanics": "before/after split reveal", "pacing": "fast cuts", "must_not_copy": ["exact audio track"],
            "originality_constraints": ["use a different product angle"],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=80, output_tokens=40),
    ))
    result = await analyze_reference_with_ai(gateway, prompt_repository, reference_description="a viral split-screen reel")
    assert result.hook_mechanics == "before/after split reveal"
    assert result.must_not_copy == ["exact audio track"]


@pytest.mark.asyncio
async def test_missing_must_not_copy_is_rejected_even_from_ai() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={"hook_mechanics": "x", "must_not_copy": [], "originality_constraints": []},
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=80, output_tokens=40),
    ))
    with pytest.raises(ReferenceAnalysisUnavailableError):
        await analyze_reference_with_ai(gateway, prompt_repository, reference_description="a viral split-screen reel")


@pytest.mark.asyncio
async def test_gateway_failure_raises_unavailable() -> None:
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider outage"))
    with pytest.raises(ReferenceAnalysisUnavailableError):
        await analyze_reference_with_ai(gateway, prompt_repository, reference_description="a viral split-screen reel")
