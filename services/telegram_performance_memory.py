"""NINJA Social Intelligence Foundation, Part III §49-52/§56: Visual Failure Memory (structural
evidence, not generic AI memory), performance evidence stages, experiments, and the
PlatformCapabilitiesRegistry - built from a REAL forensic check of this codebase's own existing
Telegram integration, never assumed from memory (spec §50's own explicit instruction).

Forensic finding: `integrations/sources/telegram_source.py` (a Telethon/MTProto client, NOT
aiogram's Bot API) already reads `views`/`forwards`/`replies`/`reactions` directly off real
`Message` objects - but ONLY for EXTERNAL channels this codebase monitors as news sources
(services/collector.py's own ingestion path). Nothing in this codebase points that same
mechanism at NNJ's own published channel, and aiogram's own Bot API (bot/loader.py) exposes none
of these fields for messages the bot itself sends - a bot cannot read back views/reactions/
forwards on its own sent messages via the Bot API at all, only via a user-account MTProto client
watching the channel. So: the underlying MECHANISM is proven real, but pointing it at NNJ's own
channel is unimplemented, not merely uncertain - correctly AVAILABLE (mechanism exists,
demonstrated working) is misleading; this registry marks these UNKNOWN rather than fabricating a
capability that has never been exercised for this specific target."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime


class CapabilityStatus(str, enum.Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    MANUAL_ONLY = "manual_only"


@dataclass(frozen=True)
class PlatformCapability:
    name: str
    status: CapabilityStatus
    evidence: str


# Built from the forensic finding in this module's own docstring - never guessed.
TELEGRAM_PLATFORM_CAPABILITIES: dict[str, PlatformCapability] = {
    "views": PlatformCapability(
        "views", CapabilityStatus.UNKNOWN,
        "integrations/sources/telegram_source.py reads message.views via Telethon/MTProto for "
        "EXTERNAL monitored channels only - the mechanism exists but has never been pointed at "
        "NNJ's own published channel; aiogram's Bot API (this bot's own send path) exposes no "
        "view count for messages it sends.",
    ),
    "reactions": PlatformCapability(
        "reactions", CapabilityStatus.UNKNOWN,
        "Same Telethon mechanism as views (integrations/sources/telegram_source.py::"
        "_reactions_count()) - proven for external channels, never wired to NNJ's own channel.",
    ),
    "reposts": PlatformCapability(
        "reposts", CapabilityStatus.UNKNOWN,
        "message.forwards read via the same external-channel Telethon path - not wired to NNJ's "
        "own channel.",
    ),
    "comments": PlatformCapability(
        "comments", CapabilityStatus.UNKNOWN,
        "message.replies.replies read via the same external-channel Telethon path - not wired to "
        "NNJ's own channel.",
    ),
    "link_clicks": PlatformCapability(
        "link_clicks", CapabilityStatus.UNAVAILABLE,
        "Telegram exposes no per-link click analytics via Bot API or MTProto for an ordinary "
        "inline-keyboard URL button - would require a redirect service NNJ does not operate.",
    ),
    "subscriber_delta": PlatformCapability(
        "subscriber_delta", CapabilityStatus.UNKNOWN,
        "aiogram's Bot.get_chat_member_count() gives a real point-in-time count (genuinely "
        "AVAILABLE as a raw call), but nothing in this codebase snapshots it over time to compute "
        "a delta - the delta itself is not implemented.",
    ),
}


class EvidenceStage(str, enum.Enum):
    ANOMALY = "anomaly"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"
    STABLE_WORKING_RULE = "stable_working_rule"


@dataclass(frozen=True)
class PerformancePattern:
    """Spec §51/§83: never one magic score - every field below must be present before a pattern
    may be promoted past ANOMALY, and anti-overfit is enforced by `advance_evidence_stage()`
    below, never by a caller's own judgment call."""

    description: str
    stage: EvidenceStage
    sample_size: int
    effect_size: float
    confidence: float
    repeatability: int  # number of independent times this exact pattern was observed
    baseline: float
    recency_days: int


# Anti-overfit thresholds (spec §83) - explicit, hand-set, not learned. A future phase may
# calibrate these against real data; today they exist to prove the promotion gate is real and
# enforced in code, not merely a docstring promise.
_MIN_SAMPLE_SIZE_FOR_SIGNAL = 5
_MIN_REPEATABILITY_FOR_PATTERN = 3
_MIN_SAMPLE_SIZE_FOR_STABLE_RULE = 30
_MAX_RECENCY_DAYS_FOR_STABLE_RULE = 90


def advance_evidence_stage(pattern: PerformancePattern) -> EvidenceStage:
    """Deterministic, one-directional gate - never skips a stage, never promotes on a single
    strong-looking sample (spec §83's own explicit "no simplistic permanent winner rules")."""
    if pattern.sample_size < _MIN_SAMPLE_SIZE_FOR_SIGNAL:
        return EvidenceStage.ANOMALY
    if pattern.repeatability < _MIN_REPEATABILITY_FOR_PATTERN:
        return EvidenceStage.POSSIBLE_SIGNAL
    if (
        pattern.sample_size >= _MIN_SAMPLE_SIZE_FOR_STABLE_RULE
        and pattern.recency_days <= _MAX_RECENCY_DAYS_FOR_STABLE_RULE
    ):
        return EvidenceStage.STABLE_WORKING_RULE
    return EvidenceStage.REPEATED_PATTERN


@dataclass(frozen=True)
class VisualFailureRecord:
    """Spec §49: structured operational evidence, not persisted in this phase (see this module's
    own docstring for the honest real-vs-contract line) - a future phase may promote this to a
    real table once a real Art Director caller exists to populate it."""

    presentation_type: str
    template: str | None
    renderer_version: str | None
    issue_codes: list[str] = field(default_factory=list)
    revision_action: str | None = None
    result: str | None = None
    resolved: bool = False
    created_at: datetime | None = None


@dataclass(frozen=True)
class ExperimentRecord:
    """Spec §52/§84: hypothesis/variant/baseline/sample_size/result/confidence - kept distinct
    from an ordinary PerformancePattern observation (spec §51's own "distinguish experiment from
    observation from stable policy")."""

    hypothesis: str
    variant: str
    baseline: str
    sample_size: int
    result: str | None = None
    confidence: float = 0.0
