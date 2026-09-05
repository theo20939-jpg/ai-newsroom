"""NINJA Social Intelligence Foundation, Part III §55/§56 + Telegram Directors Phase 2 §23-24:
Strategy Director + Platform Director. `telegram_strategy_director_enabled=False` (core/config.py)
- neither has any wired publication/generation call anywhere; `derive_strategy_advisory()` is a
pure, deterministic function a caller may invoke for advisory display only. Never publishes
directly (spec §55)."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.telegram_feed_state import FeedState
from services.telegram_performance_memory import (
    TELEGRAM_PLATFORM_CAPABILITIES,
    CapabilityStatus,
    EvidenceStage,
    PerformancePattern,
    PlatformCapability,
)

# Spec §24: deterministic, no-LLM confidence/requirements per capability status - hand-set, not
# learned, exactly like services/telegram_performance_memory.py's own anti-overfit thresholds.
_STATUS_CONFIDENCE: dict[CapabilityStatus, float] = {
    CapabilityStatus.AVAILABLE: 0.95,
    CapabilityStatus.AVAILABLE_WITH_EXISTING_MTPROTO: 0.7,
    CapabilityStatus.AVAILABLE_WITH_NEW_AUTH: 0.4,
    CapabilityStatus.UNAVAILABLE: 0.95,
    CapabilityStatus.UNKNOWN: 0.2,
    CapabilityStatus.MANUAL_ONLY: 0.5,
}
_STATUS_REQUIREMENTS: dict[CapabilityStatus, list[str]] = {
    CapabilityStatus.AVAILABLE: [],
    CapabilityStatus.AVAILABLE_WITH_EXISTING_MTPROTO: [
        "the already-authorized Telethon session must be a member of NNJ's own owned channel",
    ],
    CapabilityStatus.AVAILABLE_WITH_NEW_AUTH: ["a new credential/authorization must be obtained"],
    CapabilityStatus.UNAVAILABLE: ["not exposed by the Telegram platform via any known mechanism"],
    CapabilityStatus.UNKNOWN: ["unverified - requires a real test against NNJ's own owned channel"],
    CapabilityStatus.MANUAL_ONLY: ["only reachable via a manual/diagnostic script today"],
}


@dataclass(frozen=True)
class PlatformCapabilityReport:
    """Spec §24's own "expose the capability truth from §3, no LLM needed" output shape."""

    name: str
    status: CapabilityStatus
    evidence: str
    limitations: list[str]
    requirements: list[str]
    confidence: float
    source: str = "services/telegram_performance_memory.py::TELEGRAM_PLATFORM_CAPABILITIES"


@dataclass(frozen=True)
class StrategyDirectorAdvisory:
    """Spec §55's own output shape. Left entirely empty-list/None in this phase's own contract-
    only implementation - a future phase supplies the real derivation from Channel Memory/Feed
    State history/Performance Memory/Business Context/Campaign Plans/news-topic mix."""

    priority_themes: list[str] = field(default_factory=list)
    content_balance_notes: list[str] = field(default_factory=list)
    campaign_support_notes: list[str] = field(default_factory=list)
    series_opportunities: list[str] = field(default_factory=list)
    avoidance_fatigue_notes: list[str] = field(default_factory=list)
    experiment_suggestions: list[str] = field(default_factory=list)
    content_gaps: list[str] = field(default_factory=list)


def derive_strategy_advisory(
    feed_state: FeedState, patterns: list[PerformancePattern] | None = None,
) -> StrategyDirectorAdvisory:
    """Spec §23: a real, structured synthesizer, not an empty dataclass - but every field is
    derived ONLY from real FeedState/PerformancePattern inputs, never invented. When neither
    carries any real evidence, every relevant field states insufficient evidence explicitly rather
    than fabricating a recommendation (spec §23's own "if no performance data exists, state
    insufficient evidence rather than inventing recommendations")."""
    patterns = patterns or []
    has_feed_history = feed_state.posts_24h > 0 or bool(feed_state.topic_distribution)

    content_balance_notes: list[str] = []
    if not has_feed_history:
        content_balance_notes.append("insufficient evidence: no recent channel post history available")
    else:
        if feed_state.commercial_content_share > 0:
            content_balance_notes.append(
                f"commercial-content share of recent posts: {feed_state.commercial_content_share:.0%}"
            )
        if feed_state.recent_update_recap_density > 0:
            content_balance_notes.append(
                f"UPDATE/RECAP density of recent posts: {feed_state.recent_update_recap_density:.0%}"
            )

    campaign_support_notes: list[str] = []
    if feed_state.campaign_content_share > 0:
        campaign_support_notes.append(
            f"campaign-linked share of recent posts: {feed_state.campaign_content_share:.0%}"
        )
    else:
        campaign_support_notes.append("insufficient evidence: no recent campaign-linked posts observed")

    priority_topics: list[str] = []
    if feed_state.topic_distribution:
        top_topics = sorted(feed_state.topic_distribution, key=lambda k: feed_state.topic_distribution[k], reverse=True)
        priority_topics = top_topics[:5]
    else:
        priority_topics = []

    avoidance_fatigue_notes = [
        f"possible fatigue: {p.description}" for p in patterns
        if p.stage != EvidenceStage.ANOMALY and p.effect_size < 0
    ]
    if not avoidance_fatigue_notes:
        avoidance_fatigue_notes.append("insufficient evidence: no fatigue pattern observed yet")

    experiment_suggestions = [
        f"test: {p.description}" for p in patterns if p.stage == EvidenceStage.POSSIBLE_SIGNAL
    ]

    series_opportunities = [
        f"recurring topic candidate: {p.description}" for p in patterns
        if p.stage in (EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE) and p.effect_size > 0
    ]

    content_gaps: list[str] = []
    if feed_state.source_saturation >= 0.7 and feed_state.source_distribution:
        content_gaps.append("single-source saturation detected - consider diversifying sources")
    if not content_gaps:
        content_gaps.append("insufficient evidence: no content gap pattern observed yet")

    return StrategyDirectorAdvisory(
        priority_themes=priority_topics, content_balance_notes=content_balance_notes,
        campaign_support_notes=campaign_support_notes, series_opportunities=series_opportunities,
        avoidance_fatigue_notes=avoidance_fatigue_notes, experiment_suggestions=experiment_suggestions,
        content_gaps=content_gaps,
    )


def get_platform_capability(name: str) -> PlatformCapability | None:
    """Spec §56: capability truth must be explicit, never hallucinated. Reuses the SAME registry
    services/telegram_performance_memory.py already established (never a second, competing
    capabilities list) - this function exists only as the Platform Director's own read-only
    accessor."""
    return TELEGRAM_PLATFORM_CAPABILITIES.get(name)


def describe_platform_capability(name: str) -> PlatformCapabilityReport | None:
    """Spec §24: strengthens Platform Director beyond a bare status lookup - exposes limitations/
    requirements/confidence/source too, all deterministically derived from the same registry
    entry, never a second competing source of truth."""
    capability = TELEGRAM_PLATFORM_CAPABILITIES.get(name)
    if capability is None:
        return None
    return PlatformCapabilityReport(
        name=capability.name, status=capability.status, evidence=capability.evidence,
        limitations=[capability.evidence], requirements=_STATUS_REQUIREMENTS.get(capability.status, []),
        confidence=_STATUS_CONFIDENCE.get(capability.status, 0.0),
    )
