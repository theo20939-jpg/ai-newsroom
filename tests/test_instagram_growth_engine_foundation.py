"""NINJA Social Intelligence Foundation, Part IV §108: required Instagram Growth Engine foundation
tests. Pure unit tests - no DB needed for this branch's own contracts."""
from __future__ import annotations

import pytest

from core.config import settings
from services.campaign_planner import CampaignPlan
from services.instagram_content_brain import (
    EvidenceStage,
    PerformancePattern,
    advance_evidence_stage,
    evaluate_creative_fatigue,
)
from services.instagram_format_director import (
    CarouselPackage,
    CarouselSlide,
    ClaimViolationError,
    ContentFormat,
    ReelPackage,
    SinglePostPackage,
    evaluate_format_shadow,
)
from services.instagram_growth_strategist import propose_ideas_from_campaign_plan
from services.instagram_objectives import ContentObjective
from services.instagram_platform_capabilities import INSTAGRAM_PLATFORM_CAPABILITIES, CapabilityStatus
from services.instagram_trend_radar import Trend, TrendLifecycleStage


def test_objective_taxonomy_covers_spec_list() -> None:
    expected = {"reach", "shares", "saves", "comments", "follows", "profile_visits", "product_click", "brand"}
    assert {o.value for o in ContentObjective} == expected


def test_format_director_never_defaults_everything_to_reels() -> None:
    """Spec §71: no strong signal -> SINGLE, never a blind default to Reel."""
    decision = evaluate_format_shadow(
        objective=ContentObjective.BRAND, has_video_asset=False, has_multi_step_narrative=False,
    )
    assert decision.recommended_format == ContentFormat.SINGLE

    decision2 = evaluate_format_shadow(
        objective=ContentObjective.REACH, has_video_asset=True, has_multi_step_narrative=False,
    )
    assert decision2.recommended_format == ContentFormat.REEL


def test_carousel_package_requires_hook_slide_and_min_two_slides() -> None:
    with pytest.raises(ValueError):
        CarouselPackage(objective=ContentObjective.SAVES, slides=[CarouselSlide("body", "x", "y")], final_cta=None)
    with pytest.raises(ValueError):
        CarouselPackage(
            objective=ContentObjective.SAVES,
            slides=[CarouselSlide("hook", "x", "y")],  # only 1 slide
            final_cta=None,
        )
    package = CarouselPackage(
        objective=ContentObjective.SAVES,
        slides=[CarouselSlide("hook", "Did you know?", "v1"), CarouselSlide("body", "Here's why.", "v2")],
        final_cta="Learn more",
    )
    assert len(package.slides) == 2


def test_reel_package_requires_scene_sequence_and_positive_duration() -> None:
    with pytest.raises(ValueError):
        ReelPackage(objective=ContentObjective.REACH, hook="x", duration_target_seconds=15, scene_sequence=[])
    with pytest.raises(ValueError):
        ReelPackage(objective=ContentObjective.REACH, hook="x", duration_target_seconds=0, scene_sequence=["a"])
    package = ReelPackage(
        objective=ContentObjective.REACH, hook="You won't believe this", duration_target_seconds=20,
        scene_sequence=["intro", "demo", "cta"],
    )
    assert package.duration_target_seconds == 20


def test_package_rejects_restricted_claim_in_text() -> None:
    """Campaign restrictions propagate into production packages and are ENFORCED, not advisory
    (spec §65/§95's own claim-policy requirement)."""
    with pytest.raises(ClaimViolationError):
        SinglePostPackage(
            objective=ContentObjective.BRAND, visual_concept="v", copy="Only $99 per month!", caption="Buy now",
            cta="Buy", restricted_claims=["$99"],
        )


def test_approved_claims_propagate_without_error() -> None:
    package = SinglePostPackage(
        objective=ContentObjective.BRAND, visual_concept="v", copy="Multiple AI models inside", caption="Try it",
        cta="Learn more", approved_claims=["multiple AI models"], restricted_claims=["exact price"],
    )
    assert package.approved_claims == ["multiple AI models"]


def test_campaign_plan_claims_propagate_into_growth_strategist_ideas() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="FEATURE_REVEAL", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None, key_messages=["multiple models"],
        approved_claims=["multiple models"], restricted_claims=["exact price"],
    )
    ideas = propose_ideas_from_campaign_plan(plan)
    assert ideas
    for idea in ideas:
        assert idea.campaign_id == "c1"
        assert idea.restricted_claims == ["exact price"]


def test_trend_lifecycle_states() -> None:
    trend = Trend(
        topic="ai workflow", source_platform="tiktok", format="reel", lifecycle_stage=TrendLifecycleStage.PEAK,
        velocity=0.8, age_days=3.0, fit_with_nnj=0.6,
    )
    assert trend.lifecycle_stage == TrendLifecycleStage.PEAK
    assert set(TrendLifecycleStage) == {
        TrendLifecycleStage.EMERGING, TrendLifecycleStage.ACCELERATING, TrendLifecycleStage.PEAK,
        TrendLifecycleStage.SATURATING, TrendLifecycleStage.DECLINING, TrendLifecycleStage.EVERGREEN_TRANSITION,
    }


def test_content_brain_evidence_progression_matches_anti_overfit_gate() -> None:
    thin = PerformancePattern(description="x", sample_size=2, effect_size=0.9, confidence=0.9, repeatability=1, baseline=0.1, recency_days=1)
    assert advance_evidence_stage(thin) == EvidenceStage.ANOMALY

    stable = PerformancePattern(description="x", sample_size=40, effect_size=0.5, confidence=0.8, repeatability=8, baseline=0.2, recency_days=20)
    assert advance_evidence_stage(stable) == EvidenceStage.STABLE_WORKING_RULE


def test_creative_fatigue_structure() -> None:
    signal = evaluate_creative_fatigue(dimension="hook_family", value="contrarian", repetition_count=5, window_days=14)
    assert signal.is_fatigued is True
    fresh = evaluate_creative_fatigue(dimension="hook_family", value="question", repetition_count=1, window_days=14)
    assert fresh.is_fatigued is False


def test_platform_capabilities_are_honestly_unavailable_not_fabricated() -> None:
    """Spec §94: no Meta API credentials exist - every capability must be UNAVAILABLE/UNKNOWN,
    never fabricated AVAILABLE."""
    for capability in INSTAGRAM_PLATFORM_CAPABILITIES.values():
        assert capability.status in (CapabilityStatus.UNAVAILABLE, CapabilityStatus.UNKNOWN)
        assert capability.evidence
    assert INSTAGRAM_PLATFORM_CAPABILITIES["publish_single"].status == CapabilityStatus.UNAVAILABLE


def test_instagram_feature_flags_default_false() -> None:
    assert settings.instagram_growth_engine_enabled is False
    assert settings.instagram_story_opportunity_shadow_enabled is False
    assert settings.instagram_trend_intelligence_enabled is False
    assert settings.instagram_performance_memory_enabled is False
    assert settings.instagram_format_director_shadow_enabled is False
    assert settings.instagram_competitor_intelligence_enabled is False
    assert settings.instagram_growth_strategy_shadow_enabled is False
    assert settings.instagram_calendar_enabled is False


def test_no_publication_flag_exists_at_all() -> None:
    """Spec §92/§96: paid boost and publication are FUTURE ONLY - there must be no flag anywhere
    that could ever be flipped to make this codebase publish to Instagram."""
    assert not hasattr(settings, "instagram_publication_enabled")
    assert not hasattr(settings, "instagram_ad_spend_enabled")
