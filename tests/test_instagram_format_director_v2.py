"""INSTAGRAM GROWTH ENGINE v2, spec §69: Format Director V2 tests."""
from __future__ import annotations

from database.models.social_launch_context import (
    HistoricalContentPolicy,
    LaunchDateStatus,
    LaunchState,
    LearningBaselinePolicy,
    SocialLaunchContext,
    SocialLaunchPlatform,
)
from services.campaign_planner import CampaignPlan
from services.instagram_audience_intelligence import AudienceSegment, FunnelStage
from services.instagram_content_opportunity import (
    OpportunitySourceType,
    build_content_opportunity,
)
from services.instagram_format_director import ContentFormat
from services.instagram_format_director_v2 import AssetConstraints, evaluate_format_v2
from services.instagram_hook_intelligence import FatigueState, Hook, HookFamily
from services.instagram_objectives import ContentObjective


def _pre_launch_context() -> SocialLaunchContext:
    return SocialLaunchContext(
        platform=SocialLaunchPlatform.INSTAGRAM, version=1, target_identity="NINJA PULSE",
        current_identity=None, launch_state=LaunchState.PRE_LAUNCH, planned_launch_at=None,
        launch_date_status=LaunchDateStatus.UNSCHEDULED, baseline_policy=LearningBaselinePolicy.FROM_FIRST_PUBLICATION,
        historical_content_policy=HistoricalContentPolicy.IGNORE, raw_instruction="test", confirmed_structure={},
        created_by=5507703201,
    )


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


def test_early_funnel_audience_steers_away_from_pure_discovery_reel() -> None:
    audience = AudienceSegment(name="unaware", description="has not framed the problem yet", funnel_stage=FunnelStage.UNAWARE)
    decision = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=True, has_multi_step_narrative=True),
        audience=audience,
    )
    assert decision.recommended_format != ContentFormat.REEL
    assert "early-funnel audience" in decision.why


def test_late_funnel_audience_increases_conversion_confidence() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    opportunity = build_content_opportunity(id="o2", source_type=OpportunitySourceType.PRODUCT, product_id="p1", campaign_plan=plan)
    audience = AudienceSegment(name="considering", description="evaluating options", funnel_stage=FunnelStage.CONSIDERING)
    with_audience = evaluate_format_v2(objective=ContentObjective.PRODUCT_CLICK, assets=AssetConstraints(), opportunity=opportunity, campaign_plan=plan, audience=audience)
    without_audience = evaluate_format_v2(objective=ContentObjective.PRODUCT_CLICK, assets=AssetConstraints(), opportunity=opportunity, campaign_plan=plan)
    assert with_audience.confidence > without_audience.confidence


def test_alternatives_and_confidence_are_always_present() -> None:
    decision = evaluate_format_v2(objective=ContentObjective.BRAND, assets=AssetConstraints())
    assert decision.alternatives
    assert 0.0 <= decision.confidence <= 1.0
    assert decision.why


def test_cold_start_empty_account_notes_launch_context_never_invents_first_party_signal() -> None:
    """SOCIAL-INTELLIGENCE-PRELAUNCH-1A §6: a genuinely empty account (no audience/hook/series -
    the real state of a brand-new Instagram presence) gets an explicit cold-start note in `why`,
    but the RECOMMENDATION itself is unaffected - still derived from objective/format knowledge
    alone, never an invented first-party preference."""
    cold = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=True),
        launch_context=_pre_launch_context(),
    )
    warm = evaluate_format_v2(objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=True))
    assert cold.recommended_format == warm.recommended_format
    assert "cold-start account" in cold.why
    assert "NINJA PULSE" in cold.why
    assert "cold-start account" not in warm.why


def test_cold_start_note_suppressed_once_any_real_first_party_signal_exists() -> None:
    """The cold-start note only applies while audience/hook/series are ALL absent - a real
    audience/hook/series signal existing means this is not actually a zero-to-one account anymore,
    so the note would be misleading and is correctly withheld."""
    audience = AudienceSegment(name="new users", description="just discovering", funnel_stage=FunnelStage.UNAWARE)
    decision = evaluate_format_v2(
        objective=ContentObjective.REACH, assets=AssetConstraints(has_video_asset=True),
        launch_context=_pre_launch_context(), audience=audience,
    )
    assert "cold-start account" not in decision.why
