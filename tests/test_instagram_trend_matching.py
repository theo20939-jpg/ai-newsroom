"""INSTAGRAM GROWTH ENGINE v2, spec §64: real Trend x News / Trend x Campaign matching tests."""
from __future__ import annotations

from services.campaign_planner import CampaignPlan
from services.instagram_trend_matching import (
    StoryMatchInput,
    compute_trend_urgency,
    match_trend_to_campaign,
    match_trend_to_story,
    reject_trend_opportunity,
)
from services.instagram_trend_radar import Trend, TrendLifecycleStage


def _trend(**overrides: object) -> Trend:
    defaults: dict[str, object] = dict(
        topic="ai workflow automation", source_platform="tiktok", format="reel",
        lifecycle_stage=TrendLifecycleStage.ACCELERATING, velocity=0.7, age_days=3.0, fit_with_nnj=0.6,
        fit_with_current_campaign=0.4, confidence=0.5,
    )
    defaults.update(overrides)
    return Trend(**defaults)  # type: ignore[arg-type]


def test_trend_news_matching_finds_topic_and_entity_overlap() -> None:
    story = StoryMatchInput(
        story_id="s1", title="New AI workflow automation tool launches",
        entities=["OpenAI"], keywords=["ai", "workflow", "automation"],
    )
    match = match_trend_to_story(_trend(), story)
    assert match.matched is True
    assert match.topic_overlap > 0.0
    assert "not semantic" in match.evidence[0]


def test_trend_news_matching_rejects_when_no_overlap() -> None:
    story = StoryMatchInput(story_id="s2", title="Local weather forecast update", entities=[], keywords=["weather"])
    match = match_trend_to_story(_trend(), story)
    assert match.matched is False
    assert match.topic_overlap == 0.0


def test_declining_trend_is_rejected_for_news_matching() -> None:
    story = StoryMatchInput(story_id="s3", title="ai workflow automation", entities=[], keywords=["ai", "workflow"])
    match = match_trend_to_story(_trend(lifecycle_stage=TrendLifecycleStage.DECLINING), story)
    assert match.lifecycle_favorable is False
    assert match.matched is False
    assert any("unfavorable" in r for r in match.risks)


def test_old_trend_rejected_for_news_matching_even_with_overlap() -> None:
    story = StoryMatchInput(story_id="s4", title="ai workflow automation", entities=[], keywords=["ai", "workflow"])
    match = match_trend_to_story(_trend(age_days=30.0), story)
    assert any("too old" in r for r in match.risks)
    assert match.matched is False


def test_evergreen_old_trend_not_rejected_purely_for_age() -> None:
    reasons = reject_trend_opportunity(_trend(age_days=200.0, lifecycle_stage=TrendLifecycleStage.EVERGREEN_TRANSITION))
    assert not any("too old" in r for r in reasons)


def test_low_brand_fit_rejects_trend() -> None:
    reasons = reject_trend_opportunity(_trend(fit_with_nnj=0.05))
    assert any("fit_with_nnj" in r for r in reasons)


def test_trend_campaign_matching_respects_campaign_restrictions() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="PROBLEM_FRAMING", status="tentative",
        date_confidence="rough", start_at=None, end_at=None,
    )
    match = match_trend_to_campaign(_trend(), plan)
    assert match.product_mention_allowed is False


def test_trend_campaign_matching_allows_mention_for_confirmed_launch() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    match = match_trend_to_campaign(_trend(fit_with_current_campaign=0.8), plan)
    assert match.product_mention_allowed is True
    assert match.matched is True


def test_trend_campaign_matching_rejects_when_no_active_phase() -> None:
    plan = CampaignPlan(
        campaign_id="c1", product_id="p1", objective=None, phase=None, status="cancelled",
        date_confidence="unknown", start_at=None, end_at=None,
    )
    match = match_trend_to_campaign(_trend(), plan)
    assert match.matched is False
    assert any("no active phase" in r for r in match.risks)


def test_trend_urgency_is_separate_from_strategic_fit() -> None:
    urgent = compute_trend_urgency(_trend(lifecycle_stage=TrendLifecycleStage.SATURATING, age_days=5.0, fit_with_nnj=0.9))
    evergreen = compute_trend_urgency(_trend(lifecycle_stage=TrendLifecycleStage.EVERGREEN_TRANSITION, age_days=5.0, fit_with_nnj=0.1))
    assert urgent.expiry_risk == "high"
    assert evergreen.expiry_risk == "low"
    # fit_with_nnj (strategic value) is NOT read by compute_trend_urgency at all - urgency and
    # strategic value never collapse into one number.
    assert not hasattr(urgent, "fit_with_nnj")
