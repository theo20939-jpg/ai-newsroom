"""INSTAGRAM-GROWTH-3, item 7/16/19: shadow planning chain tests - mirrors item 16's own
NINJA AI / OpenAI-coding-news example almost verbatim."""
from __future__ import annotations

from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import OpportunitySourceType, build_content_opportunity
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_hook_intelligence import Hook, HookFamily
from services.instagram_objective_selection import ObjectiveRecommendation
from services.instagram_objectives import ContentObjective
from services.instagram_shadow_pipeline import build_shadow_plan, render_shadow_plan_text


def test_shadow_plan_retains_upstream_evidence_references() -> None:
    plan_context = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="PRODUCT_TEASING", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(
        id="opp-1", source_type=OpportunitySourceType.HYBRID, story_id="story-1", campaign_id="c1",
        news_value=0.9, campaign_plan=plan_context, evidence=["OpenAI shipped a new coding agent on 2026-09-04"],
        confidence=0.5,
    )
    objective_recommendation = ObjectiveRecommendation(
        primary_objective=ContentObjective.REACH, secondary_objectives=[ContentObjective.SHARES],
        why="high news_value favors reach", evidence=["source_type=hybrid"], confidence=0.4,
    )
    format_decision = FormatDecision(
        recommended_format=ContentFormat.REEL, alternatives=[ContentFormat.CAROUSEL],
        why="reach objective with a real video asset available", confidence=0.45,
    )
    hook = Hook(family=HookFamily.DEMONSTRATION, mechanic="show the agent working live")

    plan = build_shadow_plan(
        opportunity=opportunity, campaign_name="NINJA AI", objective_recommendation=objective_recommendation,
        format_decision=format_decision, audience_description="solution-aware AI users", hook=hook,
    )
    assert plan.product_mention_allowed is False  # tentative status
    assert plan.recommended_format == "reel"
    assert plan.hook_family == "demonstration"
    assert plan.alternative_format == "carousel"
    assert plan.alternative_objective == "shares"
    assert "OpenAI shipped a new coding agent on 2026-09-04" in plan.evidence
    assert "source_type=hybrid" in plan.evidence


def test_render_shadow_plan_text_matches_required_shape() -> None:
    plan_context = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="PRODUCT_TEASING", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(
        id="opp-1", source_type=OpportunitySourceType.HYBRID, story_id="story-1", campaign_id="c1",
        news_value=0.9, campaign_plan=plan_context,
    )
    objective_recommendation = ObjectiveRecommendation(primary_objective=ContentObjective.REACH, confidence=0.4)
    format_decision = FormatDecision(
        recommended_format=ContentFormat.REEL, alternatives=[ContentFormat.CAROUSEL], confidence=0.45,
    )
    hook = Hook(family=HookFamily.DEMONSTRATION, mechanic="show the agent working live")

    plan = build_shadow_plan(
        opportunity=opportunity, campaign_name="NINJA AI", objective_recommendation=objective_recommendation,
        format_decision=format_decision, audience_description="solution-aware AI users", hook=hook,
    )
    text = render_shadow_plan_text(plan)
    assert text.startswith("INSTAGRAM PLAN")
    assert "Campaign:\nNINJA AI" in text
    assert "Phase:\nPRODUCT_TEASING" in text
    assert "Primary objective:\nREACH" in text
    assert "Recommended format:\nREEL" in text
    assert "Hook:\nDEMONSTRATION" in text
    assert "Product mention:\nNOT ALLOWED" in text


def test_shadow_plan_includes_creative_concept_when_available() -> None:
    from datetime import datetime, timezone

    from schemas.instagram_creative import InstagramSingleCreative
    from services.instagram_creative_director import CreativeGenerationOutcome

    opportunity = build_content_opportunity(id="opp-2", source_type=OpportunitySourceType.NEWS, story_id="s1", news_value=0.5)
    objective_recommendation = ObjectiveRecommendation(primary_objective=ContentObjective.REACH, confidence=0.3)
    format_decision = FormatDecision(recommended_format=ContentFormat.SINGLE, confidence=0.2)
    outcome = CreativeGenerationOutcome(
        single=InstagramSingleCreative(
            creative_angle="the future of coding is here", visual_concept="v", on_image_copy="c",
            caption_direction="c", asset_requirements=[], evidence_used=[],
        ),
        generated_at=datetime.now(timezone.utc),
    )
    plan = build_shadow_plan(
        opportunity=opportunity, campaign_name=None, objective_recommendation=objective_recommendation,
        format_decision=format_decision, creative_outcome=outcome,
    )
    assert plan.creative_concept_summary == "the future of coding is here"
