"""Phase B.4.1 section 4: PROVES B.4 is not diagnostic-only. A `FakeLLMGateway` returns a raw
structured-output dict shaped exactly like the REAL `instagram_creative_director_carousel` v6
prompt's own `output_schema` (see prompts/instagram_creative_director_carousel/v6.yaml) - the same
contract the real OpenAI-backed Gateway would return - and the test then drives the REAL,
unmodified production call chain:

    FakeLLMGateway.generate() (fake boundary only)
      -> capabilities/gateway_call.py::call_generate()                          (real)
      -> services/instagram_creative_director.py::generate_carousel_creative()  (real)
      -> InstagramCarouselCreative.model_validate()                             (real)
      -> derive_content_archetype() override                                    (real)
      -> services/instagram_content_package.py::build_instagram_content_package()  (real)
      -> services/instagram_platform_renderer.py::render_instagram_carousel()   (real)
      -> pixels

No `InstagramCarouselSlideCreative`/`InstagramCarouselCreative` is ever constructed directly in
this file - the only way B.4's structured fields enter the test is by round-tripping through the
real prompt-schema-shaped dict and the real Creative Director parsing path, exactly as the founder
required ("Do NOT instantiate InstagramCarouselCreative directly inside the test as the only
proof")."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from integrations.llm_gateway.protocol import GenerateRequest, GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramCarouselCreative, InstagramEditorialDecision
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import (
    CAROUSEL_PROMPT_NAME,
    CreativeDirectorInput,
    generate_carousel_creative,
)
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_carousel
from services.instagram_shadow_pipeline import ShadowPlanResult

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_EVIDENCE = "confirmed feature: NINJA now drafts a full Instagram carousel autonomously"

# The exact raw JSON shape the REAL v6.yaml `output_schema` requires (additionalProperties: false,
# every nullable field explicitly present) - i.e. what the real Gateway/LLM would hand back, not a
# convenience shortcut.
_FAKE_STRUCTURED_OUTPUT = {
    "objective": "saves",
    "slides": [
        {
            "role": "hook",
            "slide_copy": "Ты это видел?",
            "visual_direction": "hero shot, high contrast",
            "source_evidence": None,
            "slide_purpose": "stop the scroll",
            "media_need": "hero photo",
            "composition": None,
            "media_position": None,
            "media_scale": None,
            "overlay_mode": None,
            "media_subject": None,
            "must_match_story": False,
        },
        {
            "role": "context",
            "slide_copy": "Вот что теперь умеет NINJA",
            "visual_direction": "product screenshot, left-aligned copy",
            "source_evidence": _EVIDENCE,
            "slide_purpose": "explain the new capability",
            "media_need": "product screenshot",
            "composition": "contained_media",
            "media_position": "left",
            "media_scale": 0.5,
            "overlay_mode": "subtle",
            "media_subject": "product_screenshot",
            "must_match_story": False,
        },
        {
            "role": "takeaway",
            "slide_copy": "Смотри сам в профиле",
            "visual_direction": "clean typographic close",
            "source_evidence": None,
            "slide_purpose": "close the loop",
            "media_need": None,
            "composition": None,
            "media_position": None,
            "media_scale": None,
            "overlay_mode": None,
            "media_subject": None,
            "must_match_story": False,
        },
    ],
    "final_cta": "Смотри в профиле",
    "evidence_used": [_EVIDENCE],
    "final_caption": "NINJA теперь собирает карусель для Instagram полностью самостоятельно.",
    # Deliberately WRONG/stale - proves derive_content_archetype() (the real archetype owner)
    # overrides whatever the model itself declared, rather than trusting it.
    "content_archetype": "ai_hack",
    "creative_execution_plan": {
        "main_idea": "NINJA can now plan its own carousel",
        "focal_point": "the product screenshot on slide 2",
        "media_strategy": "source_media",
        "media_rationale": "a real screenshot proves the claim better than typography alone",
        "composition_direction": "vary crop and hierarchy across the 3 slides",
        "branding_treatment": "logo mark, bottom-right, subtle",
        "visual_treatment": "clean, high-contrast, editorial",
        "avoid_recent_treatment": None,
    },
}

_DECISION = InstagramEditorialDecision(
    source_summary="NINJA shipped autonomous carousel planning",
    opportunity_type="NEWS",
    why_now="just shipped",
    audience_value="see the new capability",
    angle="behind the feature",
    angle_intent="EXPLAINER",
    topic="NINJA carousel autonomy",
    purpose="ENGAGEMENT",
    origin="NEWS",
    recommended_format="carousel",
    format_reason="visual proof reads better as a sequence",
    creative_direction="show, then explain, then invite",
    evidence_used=[],
)


class FakeLLMGateway:
    """Implements only the one `LLMGateway.generate()` coroutine `call_generate()` actually calls -
    the same partial-fake pattern already used across this test suite (e.g.
    tests/test_content_generation_integration.py) for the same Protocol."""

    def __init__(self, structured_output: dict) -> None:
        self._structured_output = structured_output
        self.received_requests: list[GenerateRequest] = []

    async def generate(self, request: GenerateRequest) -> GenerateResponse:
        self.received_requests.append(request)
        return GenerateResponse(
            text=None,
            structured_output=self._structured_output,
            finish_reason="stop",
            model_used="fake-model-b41",
            usage=CapabilityUsage(),
        )


_OPP = ContentOpportunity(
    id="opp-b41", source_type=OpportunitySourceType.NEWS, story_id="s-b41", product_mention_allowed=True,
)
_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="b41", primary_objective="reach",
    audience_description="", recommended_format="carousel", hook_family=None, creative_concept_summary="c",
    alternative_format=None, alternative_objective=None, product_mention_allowed=True, evidence=[], confidence=0.5,
)


def _director_input() -> CreativeDirectorInput:
    return CreativeDirectorInput(
        objective="saves",
        format="carousel",
        opportunity_summary="NINJA shipped autonomous carousel planning",
        allowed_evidence=[_EVIDENCE],
        locale="ru",
        product_mention_allowed=True,
        editorial_decision=_DECISION.model_dump_json(),
    )


@pytest.mark.asyncio
async def test_real_prompt_schema_accepts_b4_fields_without_rejection() -> None:
    """Test A/B: the REAL v6.yaml `output_schema`, loaded through the REAL `FilePromptRepository`,
    is what gets sent to the Gateway - and it must not reject the B.4 fields via
    `additionalProperties: false` (the exact root cause B.4.1 found and fixed in v5 -> v6)."""
    repo = FilePromptRepository(_PROMPTS_ROOT)
    prompt = repo.resolve(CAROUSEL_PROMPT_NAME, "6")
    slide_schema = prompt.output_schema["properties"]["slides"]["items"]
    for field_name in ("composition", "media_position", "media_scale", "overlay_mode", "media_subject", "must_match_story"):
        assert field_name in slide_schema["properties"], f"v6 schema missing {field_name}"
        assert field_name in slide_schema["required"], f"v6 schema does not require {field_name}"
    assert "content_archetype" in prompt.output_schema["properties"]
    assert "content_archetype" in prompt.output_schema["required"]
    # additionalProperties: false must still be present (strict-mode discipline unchanged) - it is
    # the presence of the field in `properties`/`required` above, not its absence, that closes the
    # gap.
    assert slide_schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_fake_gateway_through_real_pipeline_produces_pixels_with_b4_fields() -> None:
    """Test C: fake LLM structured output -> actual Creative Director parsing -> actual package ->
    actual renderer -> pixel output. The ONLY fake in this test is the Gateway transport itself."""
    gateway = FakeLLMGateway(_FAKE_STRUCTURED_OUTPUT)
    repo = FilePromptRepository(_PROMPTS_ROOT)

    outcome = await generate_carousel_creative(gateway, repo, director_input=_director_input())  # type: ignore[arg-type]

    assert outcome.carousel is not None
    carousel = outcome.carousel
    assert isinstance(carousel, InstagramCarouselCreative)

    # The real prompt call actually happened, carrying the real v6 output_schema.
    assert len(gateway.received_requests) == 1
    sent = gateway.received_requests[0]
    assert sent.response_schema is not None
    assert "content_archetype" in sent.response_schema["properties"]

    # B.4 fields survived InstagramCarouselCreative.model_validate() (real Pydantic parsing, not
    # a hand-built object).
    context_slide = carousel.slides[1]
    assert context_slide.composition == "contained_media"
    assert context_slide.media_position == "left"
    assert context_slide.media_scale == 0.5
    assert context_slide.overlay_mode == "subtle"

    # derive_content_archetype() (the real, deterministic owner) overrode the model's own stale
    # "ai_hack" - EXPLAINER/NEWS with no trend/product signal derives to "news_insight".
    assert carousel.content_archetype == "news_insight"

    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=_SP, creative_outcome=outcome,
    )
    assert package.media_plan.get("content_archetype") == "news_insight"
    slide_plan = package.media_plan["slides"][1]
    assert slide_plan["composition"] == "contained_media"
    assert slide_plan["media_position"] == "left"

    results = render_instagram_carousel(package)
    assert len(results) == 3
    context_result = results[1]
    assert context_result.evidence.notes.get("structured_composition_present") is True
    assert context_result.evidence.notes.get("structured_composition_executed") is True
    assert context_result.evidence.notes.get("fallback_role_layout_used") is False
    assert len(context_result.image_bytes) > 0

    # The hook/takeaway slides set no structured fields at all - role-based fallback, proving the
    # fallback path (Phase B.4.1 section 5) is still exactly that: a fallback, not the only path.
    hook_result = results[0]
    assert hook_result.evidence.notes.get("structured_composition_present") is False
    assert hook_result.evidence.notes.get("fallback_role_layout_used") is True


def _decision(**overrides) -> InstagramEditorialDecision:
    base = dict(
        source_summary="s", opportunity_type="NEWS", why_now="w", audience_value="a", angle="x",
        angle_intent="EXPLAINER", topic="t", purpose="ENGAGEMENT", origin="NEWS",
        recommended_format="carousel", format_reason="f", creative_direction="c", evidence_used=[],
    )
    base.update(overrides)
    return InstagramEditorialDecision(**base)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("decision", "expected"),
    [
        (_decision(angle_intent="HOW_TO", opportunity_type="EVERGREEN", origin="EVERGREEN"), "ai_hack"),
        (_decision(opportunity_type="NEWS_X_TREND", origin="TREND", trend_rationale="spreading mechanic"), "trend_generative"),
    ],
)
async def test_ai_hack_and_trend_archetypes_reach_pixels_via_real_path(decision, expected) -> None:
    """Tests L/M: the archetype is derived from the real editorial decision (not the model's own
    label) and the structured plan renders through the full real path for both archetypes."""
    from dataclasses import replace

    gateway = FakeLLMGateway(_FAKE_STRUCTURED_OUTPUT)
    director_input = replace(_director_input(), editorial_decision=decision.model_dump_json())
    outcome = await generate_carousel_creative(
        gateway, FilePromptRepository(_PROMPTS_ROOT), director_input=director_input,  # type: ignore[arg-type]
    )
    assert outcome.carousel is not None and outcome.carousel.content_archetype == expected
    package = build_instagram_content_package(
        opportunity=_OPP, format_decision=FormatDecision(recommended_format=ContentFormat.CAROUSEL),
        shadow_plan=_SP, creative_outcome=outcome,
    )
    assert package.media_plan["content_archetype"] == expected
    results = render_instagram_carousel(package)
    assert results[1].evidence.notes["structured_composition_executed"] is True
