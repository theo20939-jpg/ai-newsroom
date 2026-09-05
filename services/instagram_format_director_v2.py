"""INSTAGRAM GROWTH ENGINE v2, spec §30/§31: Format Director V2 - upgrades
services/instagram_format_director.py::evaluate_format_shadow() (objective + two booleans) into a
real multi-signal evaluator: ContentOpportunity, ContentObjective, AudienceSegment, Trend,
CampaignPlan, Hook, Series, assets, and creative fatigue all feed the decision.

Kept in its own module rather than added to services/instagram_format_director.py directly to
avoid a circular import (services/instagram_hook_intelligence.py already imports ContentFormat
from that module) - this module is the one place allowed to depend on both.

Spec §31's own caution preserved: the objective->format hypotheses below are STARTING points, not
permanent universal truth - a real Performance Memory pass would recalibrate them over time (not
implemented in this phase, no live Instagram performance data exists yet, spec §42)."""
from __future__ import annotations

from dataclasses import dataclass

from services.campaign_planner import CampaignPlan
from services.instagram_content_opportunity import ContentOpportunity
from services.instagram_format_director import ContentFormat, FormatDecision
from services.instagram_hook_intelligence import FatigueState, Hook
from services.instagram_objectives import ContentObjective
from services.instagram_series import ContentSeries, SeriesStatus
from services.instagram_trend_radar import Trend, TrendLifecycleStage


@dataclass(frozen=True)
class AssetConstraints:
    has_video_asset: bool = False
    has_multi_step_narrative: bool = False
    has_high_quality_stills: bool = True


def evaluate_format_v2(
    *, objective: ContentObjective, assets: AssetConstraints, opportunity: ContentOpportunity | None = None,
    trend: Trend | None = None, campaign_plan: CampaignPlan | None = None, hook: Hook | None = None,
    series: ContentSeries | None = None,
) -> FormatDecision:
    evidence: list[str] = [f"objective={objective.value}"]
    risks: list[str] = []
    alternatives: list[ContentFormat] = []

    # Spec §69: campaign constraints propagate - a campaign that has NOT approved a product
    # mention should not be steered toward a hard-CTA-carrying format when a safer educational
    # shape (carousel) is available.
    campaign_blocks_conversion_push = campaign_plan is not None and not (
        opportunity.product_mention_allowed if opportunity is not None else True
    )
    if campaign_blocks_conversion_push:
        evidence.append("product mention not currently allowed - conversion-oriented formats are deprioritized")

    hook_fatigued = hook is not None and hook.fatigue in (FatigueState.FATIGUED, FatigueState.OVERUSED)
    if hook is not None and hook_fatigued:
        risks.append(f"selected hook family={hook.family.value} is {hook.fatigue.value}")

    series_favors_repeat_format = bool(
        series is not None and series.status in (SeriesStatus.SERIES_ACTIVE, SeriesStatus.SERIES_TESTING)
        and series.preferred_formats
    )

    trend_favors_video = (
        trend is not None and trend.format == "reel"
        and trend.lifecycle_stage not in (TrendLifecycleStage.SATURATING, TrendLifecycleStage.DECLINING)
    )

    # SAVES/COMMENTS + a real multi-step narrative -> carousel (spec §69: "SAVES objective can
    # evaluate Carousel").
    if objective in (ContentObjective.SAVES, ContentObjective.COMMENTS) and assets.has_multi_step_narrative:
        evidence.append("save/education objective with a multi-step narrative fits a carousel")
        alternatives = [ContentFormat.SINGLE]
        confidence = 0.4
        recommended = ContentFormat.CAROUSEL

    # REACH/FOLLOWS does NOT always force Reel (spec §69) - only when a real video asset exists
    # AND no stronger reason (a fatigued hook, a blocked conversion push) argues against it.
    elif objective in (ContentObjective.REACH, ContentObjective.FOLLOWS) and assets.has_video_asset and not hook_fatigued:
        evidence.append("reach/follow objective with a real video asset available" + (" and trend supports video" if trend_favors_video else ""))
        alternatives = [ContentFormat.CAROUSEL]
        confidence = 0.5 if trend_favors_video else 0.4
        recommended = ContentFormat.REEL

    elif objective in (ContentObjective.REACH, ContentObjective.FOLLOWS) and not assets.has_video_asset:
        evidence.append("reach/follow objective but no real video asset - Reel feasibility is reduced")
        risks.append("no video asset available for a video-favored objective")
        alternatives = [ContentFormat.REEL] if assets.has_multi_step_narrative else [ContentFormat.CAROUSEL]
        confidence = 0.2
        recommended = ContentFormat.SINGLE if not assets.has_multi_step_narrative else ContentFormat.CAROUSEL

    elif objective == ContentObjective.PRODUCT_CLICK and not campaign_blocks_conversion_push:
        evidence.append("product-click objective with product mention allowed")
        alternatives = [ContentFormat.CAROUSEL]
        confidence = 0.35
        recommended = ContentFormat.SINGLE

    else:
        evidence.append("no strong signal for carousel/reel - single post is the safe default")
        alternatives = [ContentFormat.CAROUSEL]
        confidence = 0.2
        recommended = ContentFormat.SINGLE

    if series is not None and series_favors_repeat_format and series.preferred_formats[0] != recommended.value:
        evidence.append(f"series={series.id} prefers format={series.preferred_formats[0]} - consider for consistency")

    return FormatDecision(
        recommended_format=recommended, alternatives=alternatives, why="; ".join(evidence),
        expected_role="education/reference" if recommended == ContentFormat.CAROUSEL else "discovery/general",
        asset_requirements=[], risk="high" if risks else ("medium" if hook_fatigued else "low"),
        confidence=round(confidence, 3),
    )
