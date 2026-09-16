"""NINJA Social Intelligence Foundation, Part IV §62-65: Trend Intelligence contracts. No live
trend acquisition anywhere in this codebase (instagram_trend_intelligence_enabled=False,
core/config.py) - every unverified acquisition mechanism belongs in the Platform Capabilities
Registry (services/instagram_platform_capabilities.py), never assumed available here."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import UTC, datetime


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


class TrendSignalType(str, enum.Enum):
    """Meaning of the evidence, not a claim about where it is popular."""

    TOPIC_MOMENTUM = "topic_momentum"
    DISCUSSION_MOMENTUM = "discussion_momentum"
    MEME_TREND = "meme_trend"
    AUDIO_TREND = "audio_trend"
    REEL_FORMAT_TREND = "reel_format_trend"
    VISUAL_TREND = "visual_trend"
    CULTURAL_TREND = "cultural_trend"


class TrendSignalProvenance(str, enum.Enum):
    STORY_MEMORY = "STORY_MEMORY"
    INSTAGRAM = "INSTAGRAM"
    MANUAL_EDITORIAL = "MANUAL_EDITORIAL"
    OTHER_FUTURE_SOURCE = "OTHER_FUTURE_SOURCE"


_PLATFORM_NATIVE_SIGNAL_TYPES = {
    TrendSignalType.MEME_TREND,
    TrendSignalType.AUDIO_TREND,
    TrendSignalType.REEL_FORMAT_TREND,
    TrendSignalType.VISUAL_TREND,
}


@dataclass(frozen=True)
class TrendSignal:
    """Normalized Director boundary shared by Story Memory and future trend providers.

    Story Memory supplies topic/discussion momentum only. A future Instagram collector can use
    the same contract with Instagram provenance and a platform-native signal type; neither source
    needs to know how the other acquires evidence.
    """

    signal_type: TrendSignalType
    provenance: TrendSignalProvenance
    topic: str
    evidence: list[str]
    observed_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    freshness_hours: int | None = None
    confidence: float = 0.5
    relevance: str = ""
    event_count: int | None = None
    source_count: int | None = None

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("trend signal confidence must be between 0 and 1")
        if self.provenance is TrendSignalProvenance.STORY_MEMORY and self.signal_type not in {
            TrendSignalType.TOPIC_MOMENTUM,
            TrendSignalType.DISCUSSION_MOMENTUM,
        }:
            raise ValueError("Story Memory can prove only topic/discussion momentum")

    @property
    def is_platform_native(self) -> bool:
        return (
            self.provenance is TrendSignalProvenance.INSTAGRAM
            and self.signal_type in _PLATFORM_NATIVE_SIGNAL_TYPES
        )

    def to_director_context(self) -> str:
        fields = [
            f"signal_type={self.signal_type.value}",
            f"provenance={self.provenance.value}",
            f"platform_native={'true' if self.is_platform_native else 'false'}",
            f"topic={self.topic}",
            f"observed_at={self.observed_at.isoformat()}",
            f"confidence={self.confidence:.2f}",
        ]
        if self.freshness_hours is not None:
            fields.append(f"freshness_hours={self.freshness_hours}")
        if self.event_count is not None:
            fields.append(f"event_count={self.event_count}")
        if self.source_count is not None:
            fields.append(f"source_count={self.source_count}")
        if self.relevance:
            fields.append(f"relevance={self.relevance}")
        if self.evidence:
            fields.append("evidence=" + " | ".join(self.evidence))
        return "; ".join(fields)


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
