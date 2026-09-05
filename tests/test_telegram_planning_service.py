"""SOCIAL-INTELLIGENCE-OPS-1, spec §61: TelegramPlanningService tests - entries only ever come from
real StoryCampaignMatch evidence, never auto-created per Story, feed saturation influences the
advisory (timing/warning) but never the underlying business truth (match_type/campaign_value)."""
from __future__ import annotations

from datetime import datetime, timezone

from database.models.telegram_content_calendar_item import TelegramContentRole
from services.campaign_planner import CampaignPlan
from services.story_campaign_matcher import StoryCampaignMatch, StoryCampaignMatchType
from services.telegram_feed_state import FeedState
from services.telegram_planning_service import propose_calendar_entries

_NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def _plan(**overrides: object) -> CampaignPlan:
    defaults: dict[str, object] = dict(
        campaign_id="c1", product_id="p1", objective=None, phase="LAUNCH", status="confirmed",
        date_confidence="exact", start_at=None, end_at=None,
    )
    defaults.update(overrides)
    return CampaignPlan(**defaults)  # type: ignore[arg-type]


def _match(**overrides: object) -> StoryCampaignMatch:
    defaults: dict[str, object] = dict(
        story_id="s1", campaign_id="c1", product_id="p1", topic_relevance=0.4, entity_relevance=0.2,
        semantic_relevance=None, campaign_phase_relevance=1.0, audience_relevance=None,
        organic_value_reference=0.4, campaign_value=0.5, product_mention_allowed=True,
        match_type=StoryCampaignMatchType.RELEVANT, confidence=0.4,
    )
    defaults.update(overrides)
    return StoryCampaignMatch(**defaults)  # type: ignore[arg-type]


def _feed_state(**overrides: object) -> FeedState:
    defaults: dict[str, object] = dict(as_of=_NOW, posts_1h=0, posts_6h=0, posts_24h=5, topic_streak=0)
    defaults.update(overrides)
    return FeedState(**defaults)  # type: ignore[arg-type]


def test_relevant_match_produces_a_proposal() -> None:
    proposals = propose_calendar_entries(
        campaign_plan=_plan(), feed_state=_feed_state(), story_campaign_matches=[_match()], now=_NOW,
    )
    assert len(proposals) == 1
    assert proposals[0].story_id == "s1"
    assert proposals[0].objective == "product_click"


def test_none_match_never_produces_a_proposal() -> None:
    """Spec §61: no auto-entry per every Story - a NONE match is simply skipped."""
    proposals = propose_calendar_entries(
        campaign_plan=_plan(), feed_state=_feed_state(),
        story_campaign_matches=[_match(match_type=StoryCampaignMatchType.NONE, topic_relevance=0.0, entity_relevance=0.0)],
        now=_NOW,
    )
    assert proposals == []


def test_product_mention_not_allowed_produces_news_role_reach_objective() -> None:
    proposals = propose_calendar_entries(
        campaign_plan=_plan(phase="PROBLEM_FRAMING"), feed_state=_feed_state(),
        story_campaign_matches=[_match(product_mention_allowed=False)], now=_NOW,
    )
    assert proposals[0].content_role == TelegramContentRole.NEWS
    assert proposals[0].objective == "reach"


def test_feed_saturation_delays_timing_but_not_the_underlying_match(caplog=None) -> None:
    saturated_feed = _feed_state(topic_streak=4)
    proposals = propose_calendar_entries(
        campaign_plan=_plan(), feed_state=saturated_feed, story_campaign_matches=[_match()], now=_NOW,
    )
    assert proposals[0].feed_saturation_warning is not None
    assert proposals[0].planned_at > _NOW  # advisory push, real business truth (match) unaffected
    assert proposals[0].confidence == 0.4  # confidence still comes from the real match, not invented


def test_low_saturation_does_not_delay() -> None:
    proposals = propose_calendar_entries(
        campaign_plan=_plan(), feed_state=_feed_state(topic_streak=1), story_campaign_matches=[_match()], now=_NOW,
    )
    assert proposals[0].feed_saturation_warning is None
    assert proposals[0].planned_at == _NOW


def test_exact_date_dependent_phase_only_tagged_when_mention_allowed() -> None:
    proposals = propose_calendar_entries(
        campaign_plan=_plan(phase="LAUNCH"), feed_state=_feed_state(), story_campaign_matches=[_match(product_mention_allowed=True)], now=_NOW,
    )
    assert proposals[0].depends_on_campaign_phase == "LAUNCH"

    proposals_blocked = propose_calendar_entries(
        campaign_plan=_plan(phase="LAUNCH"), feed_state=_feed_state(), story_campaign_matches=[_match(product_mention_allowed=False)], now=_NOW,
    )
    assert proposals_blocked[0].depends_on_campaign_phase is None
