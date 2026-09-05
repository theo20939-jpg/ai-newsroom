"""INSTAGRAM-GROWTH-3, item 1/19: semantic-supplemented Trend x News / Trend x Campaign matching.
Required test cases (item 19): semantic match with low lexical overlap, semantic non-match, AI
unavailable deterministic fallback."""
from __future__ import annotations

import pytest

from integrations.llm_gateway.protocol import GenerateResponse
from integrations.prompts.protocol import RenderedPrompt
from schemas.capability import CapabilityUsage
from services.campaign_planner import CampaignPlan
from services.instagram_semantic_matching import SEMANTIC_MATCH_PROMPT_NAME, SEMANTIC_MATCH_PROMPT_VERSION
from services.instagram_semantic_trend_matching import (
    match_trend_to_campaign_with_semantics,
    match_trend_to_story_with_semantics,
)
from services.instagram_trend_matching import StoryMatchInput
from services.instagram_trend_radar import Trend, TrendLifecycleStage
from tests.fakes.fake_gateway import FakeLLMGateway
from tests.fakes.fake_prompt_repository import FakePromptRepository

_PROMPT = RenderedPrompt(
    name=SEMANTIC_MATCH_PROMPT_NAME, version=SEMANTIC_MATCH_PROMPT_VERSION,
    system="compare two subjects", rules=["never invent facts"],
    output_schema={"type": "object", "properties": {}, "required": []},
)


def _trend(**overrides: object) -> Trend:
    defaults: dict[str, object] = dict(
        topic="split-screen before/after reveal editing style", source_platform="tiktok", format="reel",
        lifecycle_stage=TrendLifecycleStage.ACCELERATING, velocity=0.7, age_days=3.0, fit_with_nnj=0.6,
        fit_with_current_campaign=0.4, confidence=0.5,
    )
    defaults.update(overrides)
    return Trend(**defaults)  # type: ignore[arg-type]


def _gateway_returning(is_related: bool, relatedness: float) -> FakeLLMGateway:
    return FakeLLMGateway(generate_response=GenerateResponse(
        text=None, structured_output={
            "is_related": is_related, "relatedness": relatedness, "rationale": "r", "shared_concepts": [],
        },
        finish_reason="stop", model_used="fake-model-v1", usage=CapabilityUsage(input_tokens=30, output_tokens=10),
    ))


@pytest.mark.asyncio
async def test_semantic_match_succeeds_with_low_lexical_overlap() -> None:
    """The trend topic and story title share essentially no literal tokens - only the semantic
    layer can connect them."""
    story = StoryMatchInput(
        story_id="s1", title="OpenAI unveils a new autonomous coding agent",
        entities=["OpenAI"], keywords=["coding", "agent"],
    )
    trend = _trend(topic="split-screen before/after reveal editing style")
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway_returning(is_related=True, relatedness=0.8)

    deterministic_only = await match_trend_to_story_with_semantics(trend, story)
    assert deterministic_only.matched is False  # confirms there really is no lexical overlap

    with_semantics = await match_trend_to_story_with_semantics(
        trend, story, gateway=gateway, prompt_repository=prompt_repository,
    )
    assert with_semantics.semantic_available is True
    assert with_semantics.matched is True
    assert with_semantics.topic_overlap == deterministic_only.topic_overlap  # lexical evidence retained, not hidden


@pytest.mark.asyncio
async def test_semantic_non_match_does_not_force_a_match() -> None:
    story = StoryMatchInput(story_id="s2", title="local weather forecast update", entities=[], keywords=["weather"])
    trend = _trend()
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway_returning(is_related=False, relatedness=0.05)

    result = await match_trend_to_story_with_semantics(trend, story, gateway=gateway, prompt_repository=prompt_repository)
    assert result.semantic_available is True
    assert result.matched is False


@pytest.mark.asyncio
async def test_ai_unavailable_falls_back_to_deterministic_result() -> None:
    story = StoryMatchInput(
        story_id="s3", title="OpenAI unveils a new autonomous coding agent", entities=["OpenAI"], keywords=["coding"],
    )
    trend = _trend(topic="totally unrelated dance trend")
    # No gateway/prompt_repository supplied at all - the deterministic-only path.
    result = await match_trend_to_story_with_semantics(trend, story)
    assert result.semantic_available is False
    assert result.semantic_relatedness is None
    # Must be IDENTICAL to calling the deterministic matcher directly - never partially upgraded.
    from services.instagram_trend_matching import match_trend_to_story
    baseline = match_trend_to_story(trend, story)
    assert result.matched == baseline.matched
    assert result.topic_overlap == baseline.topic_overlap


@pytest.mark.asyncio
async def test_gateway_error_falls_back_to_deterministic_result() -> None:
    from integrations.llm_gateway.errors import AllProvidersFailedError

    story = StoryMatchInput(story_id="s4", title="ai workflow automation", entities=[], keywords=["ai", "workflow"])
    trend = _trend(topic="ai workflow automation")
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = FakeLLMGateway(generate_error=AllProvidersFailedError("all providers down", reason="all_candidates_failed"))

    result = await match_trend_to_story_with_semantics(trend, story, gateway=gateway, prompt_repository=prompt_repository)
    assert result.semantic_available is False
    from services.instagram_trend_matching import match_trend_to_story
    baseline = match_trend_to_story(trend, story)
    assert result.matched == baseline.matched


@pytest.mark.asyncio
async def test_trend_campaign_semantic_supplement_respects_founder_precedence_inputs() -> None:
    """product_mention_allowed is resolved by the deterministic layer alone - a semantic match
    upgrade never touches it."""
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="PROBLEM_FRAMING", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    trend = _trend(topic="split-screen before/after reveal editing style", fit_with_current_campaign=0.1)
    prompt_repository = FakePromptRepository()
    prompt_repository.register(_PROMPT)
    gateway = _gateway_returning(is_related=True, relatedness=0.9)

    result = await match_trend_to_campaign_with_semantics(
        trend, plan, campaign_theme="AI coding assistant category education",
        gateway=gateway, prompt_repository=prompt_repository,
    )
    assert result.semantic_available is True
    assert result.product_mention_allowed is False  # tentative status still blocks it
