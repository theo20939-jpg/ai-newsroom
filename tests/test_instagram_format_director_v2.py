"""INSTAGRAM GROWTH ENGINE v2, spec §69: Format Director V2 tests."""
from __future__ import annotations

from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import (
    OpportunitySourceType,
    build_content_opportunity,
)
from services.instagram_format_director import ContentFormat
from services.instagram_format_director_v2 import AssetConstraints, evaluate_format_v2
from services.instagram_hook_intelligence import FatigueState, Hook, HookFamily
from services.instagram_objectives import ContentObjective


def test_saves_objective_can_evaluate_carousel() -> None:
    decision = evaluate_format_v2(
        objective=ContentObjective.SAVES, assets=AssetConstraints(has_multi_step_narrative=True),
    )
    assert decision.recommended_format == ContentFormat.CAROUSEL
    assert decision.why and decision.confidence > 0


def test_reach_does_not_always_force_reel_without_video_asset() -> None:
    decision = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=False),
    )
    assert decision.recommended_format != ContentFormat.REEL


def test_missing_video_assets_reduce_reel_feasibility() -> None:
    decision = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=False, has_multi_step_narrative=True),
    )
    assert "no real video asset" in decision.why
    assert decision.confidence <= 0.3


def test_campaign_constraints_propagate_to_format_decision() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="AWARENESS", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(
        id="o1", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=plan,
    )
    assert opportunity.product_mention_allowed is False
    decision = evaluate_format_v2(
        objective=ContentObjective.PRODUCT_CLICK, assets=AssetConstraints(), opportunity=opportunity, campaign_plan=plan,
    )
    assert decision.recommended_format != ContentFormat.SINGLE or "not currently allowed" in decision.why


def test_fatigue_influences_recommendation() -> None:
    hook = Hook(family=HookFamily.VISUAL_MOTION, mechanic="x", fatigue=FatigueState.FATIGUED)
    decision = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=True), hook=hook,
    )
    assert decision.recommended_format != ContentFormat.REEL
    assert decision.risk in ("medium", "high")


def test_alternatives_and_confidence_are_always_present() -> None:
    decision = evaluate_format_v2(objective=ContentObjective.BRAND, assets=AssetConstraints())
    assert decision.alternatives
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.why
