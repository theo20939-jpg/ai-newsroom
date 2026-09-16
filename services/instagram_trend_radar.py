"""NINJA Social Intelligence Foundation, Part IV §62-65: Trend Intelligence contracts. No live
trend acquisition anywhere in this codebase (instagram_trend_intelligence_enabled=False,
core/config.py) - every unverified acquisition mechanism belongs in the Platform Capabilities
Registry (services/instagram_platform_capabilities.py), never assumed available here."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class TrendLifecycleStage(str, enum.Enum):
    EMERGING = "emerging"
    ACCELERATING = "accelerating"
    PEAK = "peak"
    SATURATING = "saturating"
    DECLINING = "declining"
    EVERGREEN_TRANSITION = "evergreen_transition"


class TrendKind(str, enum.Enum):
    TOPIC = "topic"
    MEME_CULTURE = "meme_culture"
    FORMAT = "format"
    DISCUSSION = "discussion"


@dataclass(frozen=True)
class Trend:
    topic: str
    source_platform: str
    format: str | None
    lifecycle_stage: TrendLifecycleStage
    velocity: float
    age_days: float
    fit_with_nnj: float  # 0.0-1.0, advisory only
    kind: TrendKind = TrendKind.TOPIC
    fit_with_current_campaign: float = 0.0
    confidence: float = 0.3


@dataclass(frozen=True)
class TrendNewsOpportunity:
    """Spec §64: a Story fits an active trend - trend FORMATTING must never distort verified
    facts. `story_id` references the Newsroom's own canonical Story; this contract never carries
    a copy of the Story's own text."""

    trend: Trend
    story_id: str
    reasoning: str
    confidence: float = 0.3


@dataclass(frozen=True)
class TrendCampaignOpportunity:
    """Spec §65: trend + Campaign Context - claims must still obey the campaign's own
    approved/restricted claims and embargo, never bypassed because a trend is time-sensitive."""

    trend: Trend
    campaign_id: str
    approved_claims: list[str] = field(default_factory=list)
    restricted_claims: list[str] = field(default_factory=list)
    reasoning: str = ""
    confidence: float = 0.3
