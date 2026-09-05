"""NINJA Social Intelligence Foundation, Part IV §81-86: Instagram Content Brain - evidence
stages, anti-overfit gate, creative fatigue, creative scoring dimensions, and experiments. Mirrors
services/telegram_performance_memory.py's own EvidenceStage shape exactly (spec §82's own explicit
reuse of the same ANOMALY/POSSIBLE_SIGNAL/REPEATED_PATTERN/STABLE_WORKING_RULE taxonomy) -
deliberately duplicated here rather than imported cross-platform (Part II §98's own "platform
systems must not import each other" architectural boundary - the two Content Brains share a
SHAPE, never a live coupling)."""
from __future__ import annotations

import enum
from dataclasses import dataclass


class EvidenceStage(str, enum.Enum):
    ANOMALY = "anomaly"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"
    STABLE_WORKING_RULE = "stable_working_rule"


@dataclass(frozen=True)
class PerformancePattern:
    description: str
    sample_size: int
    effect_size: float
    confidence: float
    repeatability: int
    baseline: float
    recency_days: int


_MIN_SAMPLE_SIZE_FOR_SIGNAL = 5
_MIN_REPEATABILITY_FOR_PATTERN = 3
_MIN_SAMPLE_SIZE_FOR_STABLE_RULE = 30
_MAX_RECENCY_DAYS_FOR_STABLE_RULE = 90


def advance_evidence_stage(pattern: PerformancePattern) -> EvidenceStage:
    """Spec §83's own mandatory anti-overfit gate - identical shape/thresholds to services/
    telegram_performance_memory.py::advance_evidence_stage() by design (same underlying
    statistical discipline), never importing across the Telegram/Instagram platform boundary."""
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
class CreativeFatigueSignal:
    """Spec §86: tracks repeated use of a pattern - never assumes a historic winner stays a
    permanent winner (spec §53's own identical instruction, restated here for Instagram)."""

    dimension: str  # "hook_family" | "visual" | "series" | "topic" | "cta"
    value: str
    repetition_count: int
    window_days: int
    is_fatigued: bool


def evaluate_creative_fatigue(*, dimension: str, value: str, repetition_count: int, window_days: int, threshold: int = 4) -> CreativeFatigueSignal:
    return CreativeFatigueSignal(
        dimension=dimension, value=value, repetition_count=repetition_count, window_days=window_days,
        is_fatigued=repetition_count >= threshold,
    )


class FatigueState(str, enum.Enum):
    """Spec §47 Creative Fatigue V2: a graded scale, richer than `CreativeFatigueSignal.is_fatigued`
    alone - tracked identically across EVERY dimension (hook family, visual family, series, format,
    topic, CTA, trend mechanic, campaign angle), never a dimension-specific threshold, so a
    "successful format" and a "successful hook" are held to the same fatigue discipline (spec's own
    "a successful format can become stale" instruction, generalized beyond just format)."""

    FRESH = "fresh"
    NORMAL = "normal"
    REPEATED = "repeated"
    FATIGUED = "fatigued"
    OVERUSED = "overused"


_FATIGUE_STATE_THRESHOLDS: tuple[tuple[int, FatigueState], ...] = (
    (1, FatigueState.FRESH), (3, FatigueState.NORMAL), (5, FatigueState.REPEATED), (8, FatigueState.FATIGUED),
)


def evaluate_fatigue_state(*, dimension: str, repetition_count: int, window_days: int) -> FatigueState:
    """Generic, dimension-agnostic graded fatigue (spec §47) - `dimension` is documentation/logging
    only (mirrors `CreativeFatigueSignal.dimension`'s own convention), the ordinal progression
    itself never varies by dimension without real calibrating evidence to justify doing so."""
    del dimension  # not used in the calculation itself - see docstring
    for ceiling, state in _FATIGUE_STATE_THRESHOLDS:
        if repetition_count <= ceiling:
            return state
    return FatigueState.OVERUSED


@dataclass(frozen=True)
class CreativeScore:
    """Spec §85: dimensions kept explicitly separate - never collapsed into one unexplained 0-100
    magic number."""

    hook_strength: float
    clarity: float
    shareability: float
    saveability: float
    brand_fit: float
    campaign_fit: float
    originality: float
    production_feasibility: float


@dataclass(frozen=True)
class ExperimentRecord:
    hypothesis: str
    variant: str
    control: str
    objective: str
    sample_size: int = 0
    result: str | None = None
    confidence: float = 0.0
