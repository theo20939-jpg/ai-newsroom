"""VISUAL-DESIGN-AUTONOMY-1, spec §66/§67: VisualDesignDirector tests - real prompt YAML loads,
substantially different prompts across attempts, palette/composition freedom, Brand Core violation
rejected, Gateway failure raises rather than fabricating a direction."""
from __future__ import annotations

from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.visual_creative_direction import MediaStrategy, PreviousAttemptFeedback
from services.visual_design_director import (
    PROMPT_NAME,
    StoryFactsInput,
    VisualDesignDirectorUnavailableError,
    VisualDesignFactSafetyError,
    build_visual_director_context,
    generate_creative_direction,
)
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


def _context(**overrides: object):
    defaults: dict[str, object] = dict(
        story=StoryFactsInput(story_id="s1", title="OpenAI ships a new model", category="ai", entities=["OpenAI"]),
        platform="telegram", presentation_type="NEWS", designer_brief_text="Be bold but editorial.",
        designer_brief_scope="global", designer_brief_version=1, feed_context_summary=["last 6 posts considered"],
        recent_failure_summary=[], available_media_summary="1 source photo available",
        renderer_constraints_summary="upper-right or lower-left safe zone available",
        attempts_used=0, max_attempts=2, budget_state_summary="$0.00 spent today",
    )
    defaults.update(overrides)
    return build_visual_director_context(**defaults)  # type: ignore[arg-type]


def _direction_output(**overrides: object) -> dict:
    defaults: dict[str, object] = dict(
        creative_intent="convey scale of the announcement", visual_angle="wide establishing shot",
        composition="subject left third, negative space right", subject_priority="product silhouette",
        palette_direction="cool blues, high contrast", lighting_direction="dramatic rim light",
        background_direction="abstract data-flow texture", visual_density="sparse",
        negative_space_strategy="large clean area lower-right", overlay_strategy="lower-right safe",
        style_direction="editorial photojournalism", media_strategy="generate_new",
        preferred_overlay_zone="lower_right", preferred_overlay_variant="white", preferred_overlay_contrast="dark_background",
        risks=["may read as too abstract"], reasoning=["story lacks usable source photo"],
        prompt_text="A wide, cinematic editorial photo of an abstract blue data-flow scene, dramatic rim lighting.",
    )
    defaults.update(overrides)
    return defaults


def _fake_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=PROMPT_NAME, version="1", system="you are the visual director",
        rules=["never draw the logo"], output_schema={"type": "object", "properties": {}, "required": []},
    ))
    return repository


def _response(output: dict) -> GenerateResponse:
    return GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=300, output_tokens=200),
    )


def test_real_prompt_yaml_loads_and_resolves() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    prompt = repository.resolve(PROMPT_NAME, "1")
    assert prompt.name == PROMPT_NAME
    assert "media_strategy" in prompt.output_schema["properties"]


@pytest.mark.asyncio
async def test_generates_real_creative_direction_from_context() -> None:
    gateway = FakeLLMGateway(generate_response=_response(_direction_output()))
    direction = await generate_creative_direction(gateway, _fake_repository(), context=_context())
    assert direction.media_strategy == MediaStrategy.GENERATE_NEW
    assert direction.generation_needed is True
    assert direction.prompt_text
    assert direction.preferred_overlay_zone == "lower_right"


@pytest.mark.asyncio
async def test_creative_direction_may_vary_substantially_between_attempts() -> None:
    """Spec §67: revision is not restricted to a tiny patch - a second call may produce a
    completely different palette/composition/media strategy."""
    gateway = FakeLLMGateway(generate_responses=[
        _response(_direction_output(palette_direction="cool blues", composition="subject left third", media_strategy="generate_new")),
        _response(_direction_output(
            palette_direction="warm monochrome sepia", composition="centered symmetrical portrait",
            media_strategy="use_source_media", prompt_text="",
        )),
    ])
    repository = _fake_repository()
    first = await generate_creative_direction(gateway, repository, context=_context())
    second = await generate_creative_direction(gateway, repository, context=_context(attempts_used=1))
    assert first.palette_direction != second.palette_direction
    assert first.composition != second.composition
    assert first.media_strategy != second.media_strategy
    assert second.source_media_preferred is True


@pytest.mark.asyncio
async def test_rework_feedback_reaches_the_director_context() -> None:
    previous = PreviousAttemptFeedback(
        attempt_number=1, previous_creative_direction_summary="cool blues generated scene",
        previous_prompt_text="abstract blue scene", art_decision="rework",
        issue_codes=["visual_too_busy"], instructions="too many competing elements", root_cause="design_direction",
        attempts_remaining=1,
    )
    context = _context(previous_attempt=previous)
    gateway = FakeLLMGateway(generate_response=_response(_direction_output(composition="single clean focal subject")))
    await generate_creative_direction(gateway, _fake_repository(), context=context)
    sent_text = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "REWORK retry" in sent_text
    assert "visual_too_busy" in sent_text


@pytest.mark.asyncio
async def test_brand_core_violation_in_prompt_is_rejected() -> None:
    gateway = FakeLLMGateway(generate_response=_response(
        _direction_output(prompt_text="A scene featuring the NNJ logo rendered prominently in the corner.")
    ))
    with pytest.raises(VisualDesignFactSafetyError):
        await generate_creative_direction(gateway, _fake_repository(), context=_context())


@pytest.mark.asyncio
async def test_restricted_claim_in_prompt_is_rejected() -> None:
    gateway = FakeLLMGateway(generate_response=_response(
        _direction_output(prompt_text="A photo highlighting the unreleased Pro model launch")
    ))
    context = _context(restricted_claims=["unreleased Pro model launch"])
    with pytest.raises(VisualDesignFactSafetyError):
        await generate_creative_direction(gateway, _fake_repository(), context=context)


@pytest.mark.asyncio
async def test_gateway_failure_raises_never_fabricates() -> None:
    gateway = FakeLLMGateway(generate_error=RuntimeError("provider unavailable"))
    with pytest.raises(VisualDesignDirectorUnavailableError):
        await generate_creative_direction(gateway, _fake_repository(), context=_context())
