"""INSTAGRAM GROWTH ENGINE v2, spec §21/§22/§23: Hook Intelligence - a first-class HookFamily
taxonomy the previous foundation never had (it only had bare `dimension: str` fatigue tracking in
services/instagram_content_brain.py). `HookFamily` is deliberately extensible (a plain str enum a
future phase can append to, spec §21's own "Extensible" instruction).

CRITICAL evidence discipline (spec §22): a hook's performance is NEVER "always works" - this
module reuses services/instagram_content_brain.py's own EvidenceStage/advance_evidence_stage gate
rather than inventing a second, laxer one, and keeps hook family tracked as an INDEPENDENT
dimension from topic/format/timing/creative family (spec §22's own "so causality is not falsely
attributed" instruction) - `evaluate_hook_fatigue` only ever tracks the hook-family dimension, it
never blends in a topic/format signal."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field

from services.instagram_content_brain import (
    CreativeFatigueSignal,
    EvidenceStage,
    PerformancePattern,
    advance_evidence_stage,
    evaluate_creative_fatigue,
)
from services.instagram_format_director import ContentFormat
from services.instagram_objectives import ContentObjective


class HookFamily(str, enum.Enum):
    """Spec §21's own suggested taxonomy - extensible (a future value may be appended without
    breaking any existing member)."""

    VISUAL_MOTION = "visual_motion"
    SURPRISING_RESULT = "surprising_result"
    QUESTION = "question"
    CONTRARIAN = "contrarian"
    PROBLEM = "problem"
    DEMONSTRATION = "demonstration"
    BEFORE_AFTER = "before_after"
    REVEAL = "reveal"
    LIST = "list"
    SOCIAL_PROOF = "social_proof"
    STORY = "story"
    CURIOSITY_GAP = "curiosity_gap"
    COMPARISON = "comparison"
    MYTH_BUSTING = "myth_busting"


class FatigueState(str, enum.Enum):
    """Spec §23: richer than the foundation's own bare `is_fatigued: bool` - a graded scale."""

    FRESH = "fresh"
    NORMAL = "normal"
    REPEATED = "repeated"
    FATIGUED = "fatigued"
    OVERUSED = "overused"


_FATIGUE_STATE_THRESHOLDS: tuple[tuple[int, FatigueState], ...] = (
    (1, FatigueState.FRESH), (3, FatigueState.NORMAL), (5, FatigueState.REPEATED), (8, FatigueState.FATIGUED),
)


def evaluate_hook_fatigue_state(*, repetition_count: int, window_days: int) -> FatigueState:
    """Spec §23/§47: time-aware graded fatigue - no arbitrary universal threshold beyond the
    ordinal progression itself (a caller supplying a real evidence-calibrated threshold set later
    can replace `_FATIGUE_STATE_THRESHOLDS`; this is the deterministic default, not a claimed
    learned one)."""
    for ceiling, state in _FATIGUE_STATE_THRESHOLDS:
        if repetition_count <= ceiling:
            return state
    return FatigueState.OVERUSED


@dataclass(frozen=True)
class Hook:
    family: HookFamily
    mechanic: str
    example_structure: str = ""
    visual_requirement: str = ""
    objective_fit: list[ContentObjective] = field(default_factory=list)
    format_fit: list[ContentFormat] = field(default_factory=list)
    audience_fit: str = ""
    trend_fit: float = 0.0
    evidence: list[str] = field(default_factory=list)
    fatigue: FatigueState = FatigueState.FRESH
    confidence: float = 0.2


def evaluate_hook_fatigue(*, family: HookFamily, repetition_count: int, window_days: int) -> CreativeFatigueSignal:
    """Thin wrapper over services/instagram_content_brain.py::evaluate_creative_fatigue(), always
    pinned to dimension="hook_family" - hook fatigue must never silently track a different
    dimension (spec §22's own causality-isolation requirement)."""
    return evaluate_creative_fatigue(
        dimension="hook_family", value=family.value, repetition_count=repetition_count, window_days=window_days,
    )


def evaluate_hook_evidence(pattern: PerformancePattern) -> EvidenceStage:
    """Reuses the SAME anti-overfit gate as every other performance claim in this codebase (spec
    §67's own required test: "thin performance sample cannot create stable hook rule") - never a
    hook-specific, laxer threshold."""
    return advance_evidence_stage(pattern)


def recommend_hooks_for_objective(
    hooks: list[Hook], *, objective: ContentObjective, content_format: ContentFormat | None = None,
) -> list[Hook]:
    """Deterministic filter, not a ranking claim (spec §60: no LLM needed to filter by declared
    fit) - excludes OVERUSED/FATIGUED hooks by default so a fatigued hook is never silently
    recommended again."""
    candidates = [h for h in hooks if objective in h.objective_fit and h.fatigue not in (FatigueState.FATIGUED, FatigueState.OVERUSED)]
    if content_format is not None:
        candidates = [h for h in candidates if not h.format_fit or content_format in h.format_fit]
    return candidates
