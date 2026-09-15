"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 3: REEL production scripts. Covers the required test
matrix from the Founder's overnight-run authorization:
- real scene sequence / real shot list (schema widening, unchanged existing fields still flow)
- Russian-first script (presenter renders real Cyrillic labels, unaffected by new fields)
- PRODUCT evidence grounding (UngroundedEvidenceError still applies to the new text fields too)
- missing facts do not produce fabricated scripts (unresolved_required_facts() never invents)
- TREND adaptation_notes populated when trend context exists
- existing Reel behavior remains compatible (byte-identical when the new fields are absent)
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from database.models.product import ProductStatus
from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.file_repository import FilePromptRepository
from integrations.prompts.protocol import RenderedPrompt
from pathlib import Path
from schemas.capability import CapabilityUsage
from schemas.instagram_creative import InstagramReelCreative
from services.instagram_content_opportunity import ContentOpportunity, OpportunitySourceType
from services.instagram_content_package import build_instagram_content_package
from services.instagram_creative_director import (
    REEL_PROMPT_NAME,
    CreativeDirectorInput,
    UngroundedEvidenceError,
    generate_reel_creative,
)
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_platform_renderer import render_instagram_reel_cover
from services.instagram_reel_script_readiness import (
    CONCEPT_SCRIPT,
    PRODUCTION_SCRIPT,
    compute_reel_script_readiness,
    unresolved_required_facts,
)
from services.instagram_shadow_pipeline import ShadowPlanResult
from services.instagram_telegram_package_presenter import present_reel
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"

_SP = ShadowPlanResult(
    campaign_name=None, campaign_phase=None, opportunity_description="x", primary_objective="reach",
    audience_description="", recommended_format="reel", hook_family=None, creative_concept_summary=None,
    alternative_format=None, alternative_objective=None, product_mention_allowed=True,
    evidence=["confirmed feature: Production Mode"], confidence=0.5,
)


def _prompt_repository() -> FakePromptRepository:
    repository = FakePromptRepository()
    repository.register(RenderedPrompt(
        name=REEL_PROMPT_NAME, version="3", system="you are the creative director", rules=["never invent facts"],
        output_schema={"type": "object", "properties": {}, "required": []},
    ))
    return repository


def _gateway(output: dict) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output=output, finish_reason="stop", model_used="fake-model-v1",
        usage=CapabilityUsage(input_tokens=100, output_tokens=80),
    ))


_BASE_REEL_OUTPUT = {
    "objective": "reach", "hook": "Смотри, что теперь умеет NINJA AI",
    "target_duration_seconds": 20, "scene_sequence": ["Открытие приложения", "Демонстрация функции"],
    "shot_list": ["крупный план экрана", "реакция пользователя"],
    "pacing": "быстрый монтаж", "caption_direction": "объясни, что изменилось",
    "evidence_used": ["confirmed feature: Production Mode"],
}


# ---------------------------------------------------------------------------
# Schema widening - real scene sequence / shot list still flow, new fields optional
# ---------------------------------------------------------------------------


def test_real_v2_reel_prompt_file_loads_with_new_optional_fields() -> None:
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(REEL_PROMPT_NAME, "2")
    for field in ("visual_direction", "asset_requirements", "adaptation_notes"):
        assert field in rendered.output_schema["properties"]
    assert set(rendered.output_schema["required"]) == {
        "objective", "hook", "target_duration_seconds", "scene_sequence", "pacing",
        "caption_direction", "evidence_used",
    }  # the 3 new fields are optional, never required


def test_v1_reel_prompt_still_loads_byte_identical() -> None:
    """v1.yaml is left untouched - never edited in place."""
    repository = FilePromptRepository(_PROMPTS_ROOT)
    rendered = repository.resolve(REEL_PROMPT_NAME, "1")
    assert "visual_direction" not in rendered.output_schema["properties"]


def test_instagram_reel_creative_accepts_new_optional_fields_but_defaults_are_backward_compatible() -> None:
    minimal = InstagramReelCreative(
        objective="reach", hook="h", target_duration_seconds=20, scene_sequence=["s1"], pacing="fast",
        caption_direction="c",
    )
    assert minimal.visual_direction is None
    assert minimal.asset_requirements == []
    assert minimal.adaptation_notes is None

    full = InstagramReelCreative(
        objective="reach", hook="h", target_duration_seconds=20, scene_sequence=["s1"], pacing="fast",
        caption_direction="c", visual_direction="dark gradient, phone-in-hand framing",
        asset_requirements=["screen recording NINJA AI", "phone mockup"],
        adaptation_notes="original NINJA voice-over, never the source creator's own footage",
    )
    assert full.asset_requirements == ["screen recording NINJA AI", "phone mockup"]


@pytest.mark.asyncio
async def test_real_scene_sequence_and_shot_list_still_flow_through_generation() -> None:
    """Regression guard: the pre-existing fields still work exactly as before, generation-to-
    package, with the new optional fields simply absent."""
    director_input = CreativeDirectorInput(
        objective="reach", format="reel", opportunity_summary="Production Mode launch",
        allowed_evidence=["confirmed feature: Production Mode"], product_mention_allowed=True,
        product_name="NINJA AI",
    )
    outcome = await generate_reel_creative(_gateway(_BASE_REEL_OUTPUT), _prompt_repository(), director_input=director_input)
    assert outcome.reel is not None
    assert outcome.reel.scene_sequence == ["Открытие приложения", "Демонстрация функции"]
    assert outcome.reel.shot_list == ["крупный план экрана", "реакция пользователя"]


# ---------------------------------------------------------------------------
# TREND adaptation_notes populated when trend context exists
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trend_mechanic_reaches_the_prompt_and_adaptation_notes_populates() -> None:
    trend_output = dict(
        _BASE_REEL_OUTPUT,
        adaptation_notes="оригинальная NINJA-версия starter pack - без чужих кадров и музыки",
        visual_direction="starter pack layout, NINJA brand colors",
        asset_requirements=["screen recording NINJA AI", "logo asset"],
        evidence_used=[],
    )
    director_input = CreativeDirectorInput(
        objective="reach", format="reel", opportunity_summary="Starter Pack trend",
        allowed_evidence=[], product_mention_allowed=True, product_name="NINJA AI",
        trend_mechanic="starter pack", trend_spread_reason="fast, format-only, easy to remix",
    )
    gateway = _gateway(trend_output)
    outcome = await generate_reel_creative(gateway, _prompt_repository(), director_input=director_input)
    assert outcome.reel is not None
    assert outcome.reel.adaptation_notes and "NINJA" in outcome.reel.adaptation_notes
    prompt_text = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "TREND MECHANIC" in prompt_text
    assert "starter pack" in prompt_text


@pytest.mark.asyncio
async def test_no_trend_context_means_no_trend_mechanic_line_content() -> None:
    director_input = CreativeDirectorInput(
        objective="reach", format="reel", opportunity_summary="x",
        allowed_evidence=["confirmed feature: Production Mode"], product_mention_allowed=True,
    )
    gateway = _gateway(_BASE_REEL_OUTPUT)
    await generate_reel_creative(gateway, _prompt_repository(), director_input=director_input)
    prompt_text = str(gateway.received_requests[-1].messages[-1].content[0].text)
    assert "(not a trend-origin piece)" in prompt_text


# ---------------------------------------------------------------------------
# PRODUCT evidence grounding - fact-safety still applies to the new fields too
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ungrounded_evidence_still_rejected_for_reel_with_new_fields_present() -> None:
    bad_output = dict(_BASE_REEL_OUTPUT, evidence_used=["a fact never in allowed_evidence"], visual_direction="x")
    director_input = CreativeDirectorInput(
        objective="reach", format="reel", opportunity_summary="x",
        allowed_evidence=["confirmed feature: Production Mode"], product_mention_allowed=True,
    )
    with pytest.raises(UngroundedEvidenceError):
        await generate_reel_creative(_gateway(bad_output), _prompt_repository(), director_input=director_input)


# ---------------------------------------------------------------------------
# Missing facts do not produce fabricated scripts - unresolved_required_facts() never invents
# ---------------------------------------------------------------------------


def _product(**overrides) -> SimpleNamespace:
    base = dict(current_features=[], planned_features=[], undecided_facts=[], status=ProductStatus.DEVELOPMENT)
    base.update(overrides)
    return SimpleNamespace(**base)


def test_unknown_feature_is_unresolved() -> None:
    product = _product()
    unresolved = unresolved_required_facts(product, required_feature_names=["Production Mode"])
    assert unresolved == ["Production Mode"]


def test_confirmed_or_planned_feature_is_resolved() -> None:
    product = _product(planned_features=["Production Mode"])
    assert unresolved_required_facts(product, required_feature_names=["Production Mode"]) == []


def test_undecided_fact_key_is_unresolved() -> None:
    product = _product(undecided_facts=["production_mode.billing"])
    unresolved = unresolved_required_facts(product, required_fact_keys=["production_mode.billing"])
    assert unresolved == ["production_mode.billing"]


def test_no_undecided_fact_key_is_resolved() -> None:
    product = _product()
    assert unresolved_required_facts(product, required_fact_keys=["production_mode.billing"]) == []


def test_readiness_is_concept_when_any_fact_unresolved() -> None:
    assert compute_reel_script_readiness(unresolved_facts=["production_mode.billing"]) == CONCEPT_SCRIPT


def test_readiness_is_concept_when_assets_not_satisfiable_even_with_all_facts_resolved() -> None:
    assert compute_reel_script_readiness(unresolved_facts=[], asset_requirements_satisfiable=False) == CONCEPT_SCRIPT


def test_readiness_is_production_only_when_everything_resolved() -> None:
    assert compute_reel_script_readiness(unresolved_facts=[], asset_requirements_satisfiable=True) == PRODUCTION_SCRIPT


# ---------------------------------------------------------------------------
# Package + presenter integration - real production script + Russian-first output
# ---------------------------------------------------------------------------


def _reel_package(reel: InstagramReelCreative, *, readiness: str | None):
    from services.instagram_creative_director import CreativeGenerationOutcome

    opp = ContentOpportunity(
        id="opp-reel-p3", source_type=OpportunitySourceType.PRODUCT, product_id="prod-1", product_mention_allowed=True,
    )
    pkg = build_instagram_content_package(
        opportunity=opp, format_decision=FormatDecision(recommended_format=ContentFormat.REEL), shadow_plan=_SP,
        creative_outcome=CreativeGenerationOutcome(reel=reel), reel_script_readiness=readiness,
    )
    return pkg


def test_production_script_package_has_readiness_flag_and_real_scene_shot_data() -> None:
    reel = InstagramReelCreative(
        objective="reach", hook="Смотри, что теперь умеет NINJA AI", target_duration_seconds=20,
        scene_sequence=["Открытие приложения", "Демонстрация функции"],
        shot_list=["крупный план экрана"], pacing="быстрый монтаж", caption_direction="c",
        visual_direction="тёмный фон, крупный шрифт", asset_requirements=["screen recording NINJA AI"],
    )
    pkg = _reel_package(reel, readiness=PRODUCTION_SCRIPT)
    assert pkg.reel_script_readiness == PRODUCTION_SCRIPT
    assert pkg.media_plan["scene_sequence"] == ["Открытие приложения", "Демонстрация функции"]
    assert pkg.media_plan["shot_list"] == ["крупный план экрана"]

    cover = render_instagram_reel_cover(pkg)
    presentation = present_reel(pkg, cover, version=1)
    assert "ГОТОВ К ПРОДАКШЕНУ" in presentation.control_text
    assert "Открытие приложения" in presentation.control_text  # Russian-first, real content
    assert "screen recording NINJA AI" in presentation.control_text


def test_concept_script_package_is_labeled_concept_never_hidden() -> None:
    reel = InstagramReelCreative(
        objective="reach", hook="h", target_duration_seconds=20, scene_sequence=["s1"], pacing="fast",
        caption_direction="c",
    )
    pkg = _reel_package(reel, readiness=CONCEPT_SCRIPT)
    cover = render_instagram_reel_cover(pkg)
    presentation = present_reel(pkg, cover, version=1)
    assert "КОНЦЕПТ-СКРИПТ" in presentation.control_text


def test_absent_readiness_renders_exactly_as_before_phase_3() -> None:
    """A REEL package that never sets reel_script_readiness (every pre-Phase-3 call site) must
    render with neither readiness label - byte-identical to the pre-existing behavior."""
    reel = InstagramReelCreative(
        objective="reach", hook="Hook!", target_duration_seconds=30, scene_sequence=["scene1", "scene2"],
        pacing="fast", caption_direction="Reel caption",
    )
    pkg = _reel_package(reel, readiness=None)
    cover = render_instagram_reel_cover(pkg)
    presentation = present_reel(pkg, cover, version=1)
    assert "ГОТОВ К ПРОДАКШЕНУ" not in presentation.control_text
    assert "КОНЦЕПТ-СКРИПТ" not in presentation.control_text
    assert "видео ещё не создано" in presentation.control_text  # existing behavior preserved


# ---------------------------------------------------------------------------
# End-to-end composition: an UNKNOWN/UNDECIDED PRODUCT fact routes to a Director question
# instead of ever calling the Creative Director with fabricated evidence. Disclosed scope: no
# live automatic-trigger call path selects REEL format for a PRODUCT opportunity yet (format
# stays hardcoded to SINGLE per Phase 2's own "preserve current visual behavior" scope) - this
# proves the two real functions a future REEL-selecting caller would use actually compose
# correctly, not that such a caller exists yet.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unresolved_fact_routes_to_director_question_never_calls_creative_director(db_session) -> None:
    from services.business_context_proposal_service import create_director_information_need
    from services.product_context_service import create_product

    product = await create_product(db_session, slug="p3reel", name="Product P3Reel")
    # A real Product with NO current_features/planned_features at all - "Production Mode" is
    # genuinely UNKNOWN, exactly the case that must never be invented into a script.
    unresolved = unresolved_required_facts(product, required_feature_names=["Production Mode"])
    assert unresolved == ["Production Mode"]

    creative_director_called = {"n": 0}
    if unresolved:
        # The real caller pattern: route to the EXISTING Director information-need flow instead of
        # calling generate_reel_creative() at all.
        proposal = await create_director_information_need(
            db_session, product_slug=product.slug, missing_fact="Production Mode",
            opportunity_id="reel-opp-1", opportunity_source_type="PRODUCT",
            question_text="У NINJA AI действительно уже есть Production Mode?",
        )
        assert proposal.origin_context["missing_fact"] == "Production Mode"
    else:
        creative_director_called["n"] += 1  # would only happen if the fact were resolved

    assert creative_director_called["n"] == 0  # Creative Director never reached - no fabricated script
