"""INSTAGRAM GROWTH ENGINE v2, spec §9/§10/§11/§12: real Trend x News and Trend x Campaign
matching, plus Trend urgency and trend-safety rejection.

Matching is deterministic lexical/entity overlap (topic + entity tokens), not an LLM/embedding
call (spec §60's own cost-control instruction: "do not call LLM to ... check enums" - and there is
no existing embedding/semantic-similarity provider anywhere in this codebase to reuse, so building
one now would be exactly the "ad-hoc provider" spec §10 forbids). This is a real, evidence-bearing
matcher - topic/entity overlap is computed and returned as evidence, never fabricated - but it is
NOT a semantic/LLM matcher; `MatchExplanation.evidence` says so explicitly so no caller mistakes a
lexical match for semantic understanding. Wiring an LLM-based matcher through the existing
capabilities/gateway_call.py path is a documented future enhancement, not done here."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.campaign_planner import CampaignPlan
from services.instagram_trend_radar import Trend, TrendLifecycleStage

_UNFAVORABLE_LIFECYCLE_STAGES = {TrendLifecycleStage.SATURATING, TrendLifecycleStage.DECLINING}
_MAX_TREND_AGE_DAYS_FOR_NEWS_MATCH = 14.0
_MIN_BRAND_FIT_FOR_RECOMMENDATION = 0.3
_STATUSES_BLOCKING_PRODUCT_MENTION_IN_TREND_CONTENT = {"draft", "tentative", "cancelled"}


def _tokenize(*texts: str | None) -> set[str]:
    tokens: set[str] = set()
    for text in texts:
        if not text:
            continue
        tokens.update(word.strip(".,!?:;\"'()").lower() for word in text.split() if len(word) > 2)
    return tokens


def _overlap_ratio(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


@dataclass(frozen=True)
class StoryMatchInput:
    """Lightweight, DB-decoupled view of a Newsroom Story - never the ORM row itself, so this
    matcher stays unit-testable without a database session (mirrors Trend's own plain-dataclass
    convention)."""

    story_id: str
    title: str
    entities: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TrendNewsMatch:
    trend: Trend
    story_id: str
    matched: bool
    topic_overlap: float
    entity_overlap: float
    lifecycle_favorable: bool
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class TrendCampaignMatch:
    trend: Trend
    campaign_id: str
    matched: bool
    campaign_fit: float
    brand_fit_ok: bool
    product_mention_allowed: bool
    evidence: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    confidence: float = 0.0


@dataclass(frozen=True)
class TrendUrgency:
    """Spec §9: urgency (how fast this trend expires) is explicitly NOT the same axis as strategic
    value (fit_with_nnj/campaign_fit) - both are kept on the record, never collapsed."""

    freshness: float  # 1.0 = just emerged, 0.0 = fully aged out
    time_to_value_days: float  # rough estimate of remaining days before action is pointless
    expiry_risk: str  # "low" | "medium" | "high"
    estimated_remaining_window_days: float
    confidence: float


_LIFECYCLE_REMAINING_WINDOW_DAYS = {
    TrendLifecycleStage.EMERGING: 10.0,
    TrendLifecycleStage.ACCELERATING: 6.0,
    TrendLifecycleStage.PEAK: 3.0,
    TrendLifecycleStage.SATURATING: 1.0,
    TrendLifecycleStage.DECLINING: 0.5,
    TrendLifecycleStage.EVERGREEN_TRANSITION: 90.0,
}


def compute_trend_urgency(trend: Trend) -> TrendUrgency:
    remaining = _LIFECYCLE_REMAINING_WINDOW_DAYS[trend.lifecycle_stage]
    freshness = max(0.0, 1.0 - (trend.age_days / max(remaining + trend.age_days, 1.0)))
    if trend.lifecycle_stage == TrendLifecycleStage.EVERGREEN_TRANSITION:
        expiry_risk = "low"
    elif remaining <= 1.0:
        expiry_risk = "high"
    elif remaining <= 4.0:
        expiry_risk = "medium"
    else:
        expiry_risk = "low"
    return TrendUrgency(
        freshness=round(freshness, 3), time_to_value_days=remaining, expiry_risk=expiry_risk,
        estimated_remaining_window_days=remaining, confidence=min(0.3 + trend.confidence, 0.8),
    )


def reject_trend_opportunity(trend: Trend, *, min_brand_fit: float = _MIN_BRAND_FIT_FOR_RECOMMENDATION) -> list[str]:
    """Spec §12: a trend recommendation must be optional - collects every reason NOT to use it.
    An empty list means "no structural objection", never "guaranteed to work"."""
    reasons: list[str] = []
    if trend.lifecycle_stage in _UNFAVORABLE_LIFECYCLE_STAGES:
        reasons.append(f"trend lifecycle_stage={trend.lifecycle_stage.value} is unfavorable (saturating/declining)")
    if trend.age_days > _MAX_TREND_AGE_DAYS_FOR_NEWS_MATCH and trend.lifecycle_stage != TrendLifecycleStage.EVERGREEN_TRANSITION:
        reasons.append(f"trend is {trend.age_days:.1f} days old - too old for a timely news tie-in")
    if trend.fit_with_nnj < min_brand_fit:
        reasons.append(f"fit_with_nnj={trend.fit_with_nnj:.2f} is below the brand-fit floor ({min_brand_fit:.2f})")
    return reasons


def match_trend_to_story(trend: Trend, story: StoryMatchInput) -> TrendNewsMatch:
    """Spec §10: real topic/entity overlap + lifecycle/age-aware matching. Trend formatting must
    never distort the Story's own facts - this function returns a match verdict/evidence only, it
    never copies or rewrites the Story's text."""
    topic_tokens = _tokenize(trend.topic, trend.format)
    story_tokens = _tokenize(story.title, *story.entities, *story.keywords)
    topic_overlap = _overlap_ratio(topic_tokens, story_tokens)
    entity_tokens = {e.lower() for e in story.entities}
    entity_overlap = _overlap_ratio(topic_tokens, entity_tokens)

    lifecycle_favorable = trend.lifecycle_stage not in _UNFAVORABLE_LIFECYCLE_STAGES
    risks = reject_trend_opportunity(trend)

    evidence = [
        f"lexical topic/entity overlap only, not semantic (trend={trend.topic!r})",
        f"topic_overlap={topic_overlap:.2f}", f"entity_overlap={entity_overlap:.2f}",
        f"trend.lifecycle_stage={trend.lifecycle_stage.value}", f"trend.age_days={trend.age_days:.1f}",
    ]

    matched = lifecycle_favorable and not risks and (topic_overlap > 0.0 or entity_overlap > 0.0)
    confidence = round(min(0.6, (topic_overlap * 0.4 + entity_overlap * 0.4) + (0.1 if lifecycle_favorable else 0.0)), 3)

    return TrendNewsMatch(
        trend=trend, story_id=story.story_id, matched=matched, topic_overlap=round(topic_overlap, 3),
        entity_overlap=round(entity_overlap, 3), lifecycle_favorable=lifecycle_favorable, evidence=evidence,
        risks=risks, confidence=confidence,
    )


def match_trend_to_campaign(trend: Trend, campaign_plan: CampaignPlan) -> TrendCampaignMatch:
    """Spec §11: trend + CampaignPlan - product mention is resolved independently from
    campaign_fit, exactly the way spec §7 requires for ContentOpportunity (never bypassed because
    a trend is time-sensitive - spec §11's own explicit instruction)."""
    risks = reject_trend_opportunity(trend)
    brand_fit_ok = not any("fit_with_nnj" in r for r in risks)

    campaign_fit = round(min(1.0, trend.fit_with_current_campaign + (0.2 if brand_fit_ok else 0.0)), 3)
    if campaign_plan.phase is None:
        risks.append("campaign has no active phase - nothing to attach this trend to")

    product_mention_allowed = campaign_plan.status not in _STATUSES_BLOCKING_PRODUCT_MENTION_IN_TREND_CONTENT

    evidence = [
        f"campaign.phase={campaign_plan.phase!r}", f"campaign.status={campaign_plan.status!r}",
        f"trend.fit_with_current_campaign={trend.fit_with_current_campaign:.2f}",
    ]

    matched = brand_fit_ok and not risks
    confidence = round(min(0.6, campaign_fit * 0.5 + (0.1 if matched else 0.0)), 3)

    return TrendCampaignMatch(
        trend=trend, campaign_id=campaign_plan.campaign_id, matched=matched, campaign_fit=campaign_fit,
        brand_fit_ok=brand_fit_ok, product_mention_allowed=product_mention_allowed, evidence=evidence,
        risks=risks, confidence=confidence,
    )
