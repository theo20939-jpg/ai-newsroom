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
    # INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES: SINGLE/CAROUSEL/REEL all moved to
    # another new prompt version (services/instagram_creative_director.py::_SINGLE_PROMPT_
    # VERSION/_CAROUSEL_PROMPT_VERSION/_REEL_PROMPT_VERSION's own docstring explains why - the
    # maxLength-vs-Pydantic schema hotfix, on top of the earlier OpenAI strict-schema hotfix
    # already applied to business_context_parser).
    repository.register(RenderedPrompt(
        name=SINGLE_PROMPT_NAME, version="6", system="you are the creative director", rules=["never invent facts"],
        output_schema=_SINGLE_SCHEMA,
    ))
    repository.register(RenderedPrompt(
        name=CAROUSEL_PROMPT_NAME, version="10.7", system="you are the creative director", rules=["never invent facts"],
        output_schema=_CAROUSEL_SCHEMA,
    ))
    repository.register(RenderedPrompt(
        name=REEL_PROMPT_NAME, version="7", system="you are the creative director", rules=["never invent facts"],
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
async def test_launch_context_note_reaches_the_prompt_but_is_optional() -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §7: `launch_context_note` (when a caller supplies one from
    a real SocialLaunchContext) reaches the Gateway prompt text verbatim - and its absence (the
    default "") never breaks generation, exactly as every existing call site above proves."""
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "a", "visual_concept": "a", "on_image_copy": "a", "caption_direction": "a",
        "cta": None, "asset_requirements": [], "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    director_input = _base_input(launch_context_note="first Instagram post ever - assume zero follower familiarity")
    await generate_single_creative(gateway, _prompt_repository(), director_input=director_input)
    prompt_text = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "LAUNCH CONTEXT" in prompt_text
    assert "first Instagram post ever" in prompt_text


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
async def test_prompt_bullet_marker_does_not_make_exact_evidence_ungrounded() -> None:
    """The model may retain the visual marker added by our prompt around an unchanged fact."""
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "a", "visual_concept": "v", "on_image_copy": "c", "caption_direction": "c",
        "cta": None, "asset_requirements": [],
        "evidence_used": ["- OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    outcome = await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())
    assert outcome.single is not None


@pytest.mark.asyncio
async def test_prompt_bullet_marker_does_not_hide_changed_evidence() -> None:
    """Removing the presentation marker must not weaken exact factual grounding."""
    gateway = FakeLLMGateway(generate_response=_response({
        "creative_angle": "a", "visual_concept": "v", "on_image_copy": "c", "caption_direction": "c",
        "cta": None, "asset_requirements": [],
        "evidence_used": ["- OpenAI announced two autonomous coding agents on 2026-09-04"],
    }))
    with pytest.raises(UngroundedEvidenceError):
        await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())


@pytest.mark.asyncio
async def test_gateway_failure_raises_unavailable_never_fabricates() -> None:
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider outage"))
    with pytest.raises(CreativeDirectorUnavailableError):
        await generate_single_creative(gateway, _prompt_repository(), director_input=_base_input())


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 ROLLOUT CLOSURE HOTFIX: structural proof (not a
# spot-check) that all 3 real, currently-resolved prompt files satisfy OpenAI's strict
# response_format="json_schema" contract - every key in `properties` must also appear in that
# object's own `required` array. A real bounded Reel canary against the live production OpenAI
# endpoint proved v1/v2 of all three prompts violated this (the exact same class of bug
# tests/test_business_context_command_parser_v2.py already proved and fixed for that prompt).
# ---------------------------------------------------------------------------


def _strict_mode_violations(node: dict, path: str) -> list[str]:
    violations: list[str] = []
    if node.get("type") == "object" and "properties" in node:
        required = set(node.get("required", []))
        properties = node["properties"]
        missing = set(properties.keys()) - required
        if missing:
            violations.append(f"{path}: missing {sorted(missing)} from required")
        for key, subschema in properties.items():
            violations.extend(_strict_mode_violations(subschema, f"{path}.{key}"))
    if node.get("type") == "array" and "items" in node:
        violations.extend(_strict_mode_violations(node["items"], f"{path}[]"))
    return violations


@pytest.mark.parametrize(("prompt_name", "version"), [
    (SINGLE_PROMPT_NAME, "3"), (CAROUSEL_PROMPT_NAME, "3"), (CAROUSEL_PROMPT_NAME, "6"), (CAROUSEL_PROMPT_NAME, "7"), (CAROUSEL_PROMPT_NAME, "8"), (CAROUSEL_PROMPT_NAME, "9"), (CAROUSEL_PROMPT_NAME, "9.1"), (CAROUSEL_PROMPT_NAME, "10"), (CAROUSEL_PROMPT_NAME, "10.1"), (CAROUSEL_PROMPT_NAME, "10.2"), (CAROUSEL_PROMPT_NAME, "10.3"), (CAROUSEL_PROMPT_NAME, "10.4"), (CAROUSEL_PROMPT_NAME, "10.5"), (CAROUSEL_PROMPT_NAME, "10.6"), (CAROUSEL_PROMPT_NAME, "10.7"), (REEL_PROMPT_NAME, "4"),
])
def test_real_creative_director_prompts_have_no_openai_strict_mode_violations(prompt_name: str, version: str) -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(prompt_name, version)
    violations = _strict_mode_violations(rendered.output_schema, prompt_name)
    assert violations == [], f"OpenAI strict-mode required-field violations: {violations}"


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES (FIX A): a real bounded Reel canary proved
# a SECOND, different prompt<->Pydantic contract mismatch class - a field can satisfy the prompt's
# own (undeclared) JSON schema while failing schemas/instagram_creative.py's own Pydantic
# max_length/gt/le constraints, because the prompt schema never declared them. This structural test
# proves every bounded field in the CURRENT (v3/v3/v4) prompt schemas declares a maxLength/minimum/
# maximum that matches its Pydantic model field exactly - not a spot-check, the complete field set.
# ---------------------------------------------------------------------------

from schemas.instagram_creative import (  # noqa: E402
    InstagramCarouselCreative,
    InstagramCarouselSlideCreative,
    InstagramReelCreative,
    InstagramSingleCreative,
)


def _pydantic_max_length(model: type, field_name: str) -> int | None:
    info = model.model_fields[field_name]
    for meta in info.metadata:
        value = getattr(meta, "max_length", None)
        if value is not None:
            return value
    return None


def test_single_prompt_schema_max_lengths_match_pydantic_model() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(SINGLE_PROMPT_NAME, "3")
    properties = rendered.output_schema["properties"]
    for field_name in ("creative_angle", "visual_concept", "on_image_copy", "caption_direction", "cta"):
        expected = _pydantic_max_length(InstagramSingleCreative, field_name)
        assert properties[field_name].get("maxLength") == expected, field_name


def test_carousel_prompt_schema_max_lengths_match_pydantic_model() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(CAROUSEL_PROMPT_NAME, "3")
    properties = rendered.output_schema["properties"]
    for field_name in ("objective", "final_cta"):
        expected = _pydantic_max_length(InstagramCarouselCreative, field_name)
        assert properties[field_name].get("maxLength") == expected, field_name
    slide_properties = properties["slides"]["items"]["properties"]
    for field_name in ("role", "slide_copy", "visual_direction", "source_evidence"):
        expected = _pydantic_max_length(InstagramCarouselSlideCreative, field_name)
        assert slide_properties[field_name].get("maxLength") == expected, field_name


def test_reel_prompt_schema_max_lengths_match_pydantic_model() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(REEL_PROMPT_NAME, "4")
    properties = rendered.output_schema["properties"]
    for field_name in (
        "objective", "hook", "voiceover_script", "pacing", "audio_direction", "cta",
        "loop_ending_concept", "caption_direction", "visual_direction", "adaptation_notes",
    ):
        expected = _pydantic_max_length(InstagramReelCreative, field_name)
        assert properties[field_name].get("maxLength") == expected, field_name


def test_reel_prompt_schema_duration_bounds_match_pydantic_model() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(REEL_PROMPT_NAME, "4")
    duration_schema = rendered.output_schema["properties"]["target_duration_seconds"]
    assert duration_schema.get("maximum") == 180
    assert duration_schema.get("minimum", 0) >= 1  # Pydantic Field(gt=0) on an int is effectively >= 1


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES (FIX A, tail end): a real end-to-end proof
# that a value which is valid by every OTHER rule but sits right at the old, undeclared 50-char
# `objective` boundary can still round-trip through generate_*_creative() without our own Pydantic
# validation raising - i.e. the schema now actually constrains what the model can return, not just
# that the JSON keys/shape line up.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# INSTAGRAM-CONTENT-STRATEGY-V2 Phase 2/3 MINIMAL FIXES (FIX B): all three real prompt files must
# carry the new state-aware evidence-wording rule, so a PLANNED product fact (now eligible per
# services/director_execution_service.py::_product_opportunities_from_context()) is never rendered
# as already live.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("prompt_name", "version"), [
    (SINGLE_PROMPT_NAME, "3"), (CAROUSEL_PROMPT_NAME, "3"), (CAROUSEL_PROMPT_NAME, "6"), (CAROUSEL_PROMPT_NAME, "7"), (CAROUSEL_PROMPT_NAME, "8"), (CAROUSEL_PROMPT_NAME, "9"), (CAROUSEL_PROMPT_NAME, "9.1"), (CAROUSEL_PROMPT_NAME, "10"), (CAROUSEL_PROMPT_NAME, "10.1"), (CAROUSEL_PROMPT_NAME, "10.2"), (CAROUSEL_PROMPT_NAME, "10.3"), (CAROUSEL_PROMPT_NAME, "10.4"), (CAROUSEL_PROMPT_NAME, "10.5"), (CAROUSEL_PROMPT_NAME, "10.6"), (CAROUSEL_PROMPT_NAME, "10.7"), (REEL_PROMPT_NAME, "4"),
])
def test_real_creative_director_prompts_carry_the_state_aware_evidence_rule(prompt_name: str, version: str) -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(prompt_name, version)
    rule_text = " ".join(rendered.rules)
    assert "confirmed feature:" in rule_text
    assert "planned feature:" in rule_text


@pytest.mark.asyncio
async def test_reel_objective_at_the_declared_boundary_is_accepted() -> None:
    gateway = FakeLLMGateway(generate_response=_response({
        "objective": "x" * 50, "hook": "AI just wrote this entire app", "target_duration_seconds": 25,
        "scene_sequence": ["hook", "demo", "reveal", "cta"], "shot_list": ["screen recording of the agent working"],
        "voiceover_script": "Watch what happens when AI writes the code for you", "on_screen_text": ["No code written by hand"],
        "b_roll_requirements": ["laptop close-up"], "pacing": "fast cuts every 2 seconds",
        "audio_direction": "trending upbeat track", "cta": "Follow for more", "loop_ending_concept": "loops back to the hook line",
        "caption_direction": "explain the agent's capability in plain language",
        "evidence_used": ["OpenAI announced a new autonomous coding agent on 2026-09-04"],
    }))
    outcome = await generate_reel_creative(gateway, _prompt_repository(), director_input=_base_input(format="reel"))
    assert outcome.reel is not None
    assert len(outcome.reel.objective) == 50
