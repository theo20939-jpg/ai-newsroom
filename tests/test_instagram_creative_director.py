"""INSTAGRAM-GROWTH-3, item 19: Creative Director tests - SINGLE/CAROUSEL/REEL generation,
restricted claim blocked, embargo/product-mention blocked, unsupported Story fact rejected."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.instagram_creative_director import (
    CAROUSEL_PROMPT_NAME,
    REEL_PROMPT_NAME,
    SINGLE_PROMPT_NAME,
    CreativeDirectorInput,
    CreativeDirectorUnavailableError,
    CreativeFactSafetyError,
    UngroundedEvidenceError,
    generate_carousel_creative,
    generate_reel_creative,
    generate_single_creative,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_SINGLE_SCHEMA = {
    "type": "object",
    "properties": {
        "creative_angle": {"type": "string"}, "visual_concept": {"type": "string"},
        "on_image_copy": {"type": "string"}, "caption_direction": {"type": "string"},
        "cta": {"type": ["string", "null"]}, "asset_requirements": {"type": "array"},
        "evidence_used": {"type": "array"},
    },
    "required": ["creative_angle", "visual_concept", "on_image_copy", "caption_direction", "asset_requirements", "evidence_used"],
}
_CAROUSEL_SCHEMA = {"type": "object", "properties": {}, "required": []}
_REEL_SCHEMA = {"type": "object", "properties": {}, "required": []}


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=SINGLE_PROMPT_NAME, version="1", system="you are the creative director", rules=["never invent facts"],
        output_schema=_SINGLE_SCHEMA,
    ))
    repository.register(RenderedPrompt(
        name=CAROUSEL_PROMPT_NAME, version="1", system="you are the creative director", rules=["never invent facts"],
        output_schema=_CAROUSEL_SCHEMA,
    ))
    repository.register(RenderedPrompt(
        name=REEL_PROMPT_NAME, version="1", system="you are the creative director", rules=["never invent facts"],
        output_schema=_REEL_SCHEMA,
    ))
    return repository


def _response(output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=200, output_tokens=150),
    )


def _base_input(**overrides: object) -> CreativeDirectorInput:
    defaults: dict[str, object] = dict(
        objective="reach", format="single", opportunity_summary="OpenAI ships a new coding agent",
        allowed_evidence=["OpenAI announced a new autonomous coding agent on 2026-09-04"],
        audience_summary="solution-aware AI users", hook_family="demonstration",
        product_mention_allowed=True, product_name="NINJA AI",
    )
    defaults.update(overrides)
    return CreativeDirectorInput(**defaults)  # type: ignore[arg-type]


def test_real_prompt_files_load() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    for name in (SINGLE_PROMPT_NAME, CAROUSEL_PROMPT_NAME, REEL_PROMPT_NAME):
        rendered = repository.resolve(name, "1")
        assert rendered.name == name
        assert "evidence_used" in rendered.output_schema["properties"]


@pytest.mark.asyncio
async def test_single_creative_generation_succeeds() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "the future of coding is here", "visual_concept": "split screen human vs AI",
        "on_image_copy": "AI just leveled up", "caption_direction": "explain what changed and why it matters",
        "cta": "Learn more in bio", "asset_requirements": ["screenshot of the agent"],
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    outcome = await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())
    assert outcome.single is not None
    assert outcome.single.creative_angle == "the future of coding is here"
    assert outcome.call is not None


@pytest.mark.asyncio
async def test_carousel_creative_generation_succeeds() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "objective": "saves",
        "slides": [
            {"role": "hook", "slide_copy": "Did you know AI can now code for you?", "visual_direction": "bold text on gradient", "source_evidence": "OpenAI announced a new autonomous coding agent on 2026-09-04"},
            {"role": "takeaway", "slide_copy": "Here's what changed", "visual_direction": "clean list layout", "source_evidence": None},
        ],
        "final_cta": "Save this for later",
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    outcome = await generate_carousel_creative(gateway, _prompt_repository(), director_input=_base_input(format="carousel", objective="saves"))
    assert outcome.carousel is not None
    assert len(outcome.carousel.slides) == 2
    assert outcome.carousel.hook_slide.role == "hook"


@pytest.mark.asyncio
async def test_reel_creative_generation_succeeds() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "objective": "reach", "hook": "AI just wrote this entire app", "target_duration_seconds": 25,
        "scene_sequence": ["hook", "demo", "reveal", "cta"], "shot_list": ["screen recording of the agent working"],
        "voiceover_script": "Watch what happens when AI writes the code for you", "on_screen_text": ["No code written by hand"],
        "b_roll_requirements": ["laptop close-up"], "pacing": "fast cuts every 2 seconds",
        "audio_direction": "trending upbeat track", "cta": "Follow for more", "loop_ending_concept": "loops back to the hook line",
        "caption_direction": "explain the agent's capability in plain language",
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    outcome = await generate_reel_creative(gateway, _prompt_repository(), director_input=_base_input(format="reel"))
    assert outcome.reel is not None
    assert outcome.reel.target_duration_seconds == 25


@pytest.mark.asyncio
async def test_restricted_claim_is_blocked() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "a", "visual_concept": "v", "on_image_copy": "Only $4.99/month!",
        "caption_direction": "c", "cta": None, "asset_requirements": [],
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    with pytest.raises(CreativeFactSafetyError):
        await generate_single_creative(
            gateway, _prompt_repository(), director_input=_base_input(restricted_claims=["$4.99/month"]),
        )


@pytest.mark.asyncio
async def test_product_mention_blocked_when_not_allowed() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "NINJA AI does this better than anyone", "visual_concept": "v", "on_image_copy": "c",
        "caption_direction": "c", "cta": None, "asset_requirements": [],
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    with pytest.raises(CreativeFactSafetyError):
        await generate_single_creative(
            gateway, _prompt_repository(),
            director_input=_base_input(product_mention_allowed=False, product_name="NINJA AI"),
        )


@pytest.mark.asyncio
async def test_unsupported_story_fact_rejected() -> None:
    """The model claims evidence that was never supplied - an invented fact must be rejected."""
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "a", "visual_concept": "v", "on_image_copy": "c", "caption_direction": "c",
        "cta": None, "asset_requirements": [],
        "evidence_used": ["OpenAI's agent is used by 50 million developers worldwide"],
    }))
    with pytest.raises(UngroundedEvidenceError):
        await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())


@pytest.mark.asyncio
async def test_gateway_failure_raises_unavailable_never_fabricates() -> None:
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider outage"))
    with pytest.raises(CreativeDirectorUnavailableError):
        await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())
