"""NINJA Social Intelligence Foundation, Part III §42/§43: Telegram Channel Director - SHADOW /
ADVISORY ONLY (spec §42, §111). No automatic delay/deprioritization/publication control exists
anywhere that calls this module - it is not wired into worker/content_cycle.py's real publish
path in this phase. Deterministic, rule-based (no LLM) - a genuinely calibrated, learning-based
director is explicitly future work; this phase's own job is to prove the STRUCTURED CONTRACT
(decision/priority/reasons/...) is reachable, testable, and correctly separates organic news
value from campaign relevance (spec §43's own critical requirement)."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from services.campaign_planner import CampaignPlan
from services.telegram_editorial_need import EditorialNeed
from services.telegram_feed_state import FeedState


class ChannelDirectorDecision(str, enum.Enum):
    PUBLISH_NOW = "publish_now"
    PUBLISH_SOON = "publish_soon"
    DELAY = "delay"
    DEPRIORITIZE = "deprioritize"
    HUMAN_REVIEW = "human_review"


@dataclass(frozen=True)
class ChannelDirectorResult:
    decision: ChannelDirectorDecision
    priority: int
    channel_fit: float  # 0.0-1.0, advisory only
    feed_role: str
    timing: str
    balance_effect: str
    organic_relevance: float  # spec §43: kept explicitly separate from campaign_relevance
    business_campaign_relevance: float
    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    next_feed_need: str | None = None
    confidence: float = 0.5


def evaluate_channel_fit_shadow(
    *, news_importance: float, feed_state: FeedState, editorial_need: EditorialNeed,
    campaign_plan: CampaignPlan | None = None, campaign_mention_explicitly_allowed: bool = False,
) -> ChannelDirectorResult:
    """`campaign_mention_explicitly_allowed` must come from the real CampaignPlan (§43's own
    "Channel Director may identify high campaign adjacency but must NOT rewrite it into an
    advertisement unless the Campaign Plan explicitly allows product mention" rule) - this
    function never infers permission from `news_importance` or `feed_state` alone."""
    reasons: list[str] = []
    warnings: list[str] = []

    organic_relevance = min(1.0, max(0.0, news_importance))
    business_campaign_relevance = 0.0
    if campaign_plan is not None and campaign_plan.phase is not None:
        business_campaign_relevance = 0.5
        reasons.append(f"active campaign phase={campaign_plan.phase}")
        if not campaign_mention_explicitly_allowed:
            warnings.append("campaign relevance detected but Campaign Plan does not allow product mention here")

    saturation_notes = [n for n in editorial_need.notes]
    if editorial_need.feed_too_commercial:
        warnings.append("feed is already commercial-heavy - avoid stacking another campaign-linked post")

    if organic_relevance >= 0.8 and not saturation_notes:
        decision = ChannelDirectorDecision.PUBLISH_NOW
        priority = 10
    elif organic_relevance >= 0.5:
        decision = ChannelDirectorDecision.PUBLISH_SOON
        priority = 50
    elif saturation_notes:
        decision = ChannelDirectorDecision.DEPRIORITIZE
        priority = 80
        reasons.extend(saturation_notes)
    else:
        decision = ChannelDirectorDecision.PUBLISH_SOON
        priority = 60

    return ChannelDirectorResult(
        decision=decision, priority=priority, channel_fit=organic_relevance, feed_role="advisory_only",
        timing="shadow - no automatic timing effect", balance_effect="shadow - no automatic balance effect",
        organic_relevance=organic_relevance, business_campaign_relevance=business_campaign_relevance,
        reasons=reasons, warnings=warnings,
        next_feed_need=editorial_need.saturated_topic or editorial_need.saturated_entity, confidence=0.4,
    )
