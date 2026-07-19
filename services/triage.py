"""Triage: a pure function recommending a TaskPriority for one NewsEvent from
Freshness and source Authority (NewsSource.reliability_score) only.

Phase 9 Contract §2.2/§3/§4/§6. See scripts/validate_architecture.py's
triage-purity rule for the mechanically-enforced dependency boundary: no DB
session, no LLMGateway, no Capability layer, no workflows/ module.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from database.models.editorial_task import TaskPriority
from services.freshness import compute_freshness

# Contract §3 "Ordering - binding, frozen" / §21 rule 13: the one place TaskPriority
# is ever ranked in this phase. TaskPriority(str, Enum) inherits str's native
# lexicographic comparison - TaskPriority.S < TaskPriority.A is False, and
# sorted([S, A, B, C]) yields [A, B, C, S] (alphabetical), which inverts the intended
# S > A > B > C urgency order for the A/B/C tiers. Native </>/<=/>=/sorted()/min()/
# max() applied to TaskPriority values MUST NOT be used anywhere for a
# business-priority decision - this explicit ordinal mapping is the only sanctioned
# mechanism, and it is used here only for logging/explaining a decision already made
# by _priority_for_score(), never to make the decision itself.
TASK_PRIORITY_ORDINAL: dict[TaskPriority, int] = {
    TaskPriority.C: 0,
    TaskPriority.B: 1,
    TaskPriority.A: 2,
    TaskPriority.S: 3,
}

# PRODUCT CONFIGURATION (Contract §22) - provisional starting values, not architecture.
# The default is Contract §6 rule 4's own worked example: "a fixed neutral value, e.g.
# the midpoint of the configured range."
DEFAULT_RELIABILITY_SCORE = 0.5
FRESHNESS_WEIGHT = 0.6
RELIABILITY_WEIGHT = 0.4

# Combined-score cutoffs, checked highest-first; the trailing "else" in
# _priority_for_score always applies, so every input deterministically maps to a
# TaskPriority - Contract §4's no-hard-drop invariant is satisfied by construction,
# not merely by convention.
_PRIORITY_THRESHOLDS: tuple[tuple[float, TaskPriority], ...] = (
    (0.75, TaskPriority.S),
    (0.55, TaskPriority.A),
    (0.35, TaskPriority.B),
)


@dataclass(frozen=True)
class TriageResult:
    """JSON-serializable, immutable - Contract §3's "Output shape" requirement.
    Never persisted as its own database row (§14) - it exists only in memory and in
    structured logs, wired by the Triage Orchestrator (M3)."""

    priority: TaskPriority
    explanation: dict[str, Any]


def _combined_score(freshness_weight: float, reliability_score: float) -> float:
    return FRESHNESS_WEIGHT * freshness_weight + RELIABILITY_WEIGHT * reliability_score


def _priority_for_score(combined_score: float) -> TaskPriority:
    for threshold, priority in _PRIORITY_THRESHOLDS:
        if combined_score >= threshold:
            return priority
    return TaskPriority.C


def decide_triage(
    published_at: datetime | None,
    collected_at: datetime,
    reliability_score: float | None,
    reference_now: datetime,
) -> TriageResult:
    """Pure. Contract §3: identical (inputs, configuration, reference_now) MUST
    produce identical output, every time - zero LLM/provider/web/embedding calls.
    Freshness (§2.1) and NewsSource.reliability_score (§6) are the complete, closed
    signal set (§3's allowed-input table); no other NewsEvent/NewsSource field may be
    added to this formula without a Contract amendment.
    """
    freshness = compute_freshness(published_at, collected_at, reference_now)

    used_reliability_default = reliability_score is None
    effective_reliability = DEFAULT_RELIABILITY_SCORE if reliability_score is None else reliability_score

    combined_score = _combined_score(freshness.weight, effective_reliability)
    priority = _priority_for_score(combined_score)

    explanation: dict[str, Any] = {
        "freshness_tier": freshness.tier_label,
        "freshness_weight": freshness.weight,
        "freshness_age_seconds": freshness.age_seconds,
        "used_collected_at_fallback": freshness.used_collected_at_fallback,
        "reliability_score": effective_reliability,
        "used_reliability_default": used_reliability_default,
        "combined_score": combined_score,
        "priority": priority.value,
    }

    return TriageResult(priority=priority, explanation=explanation)
