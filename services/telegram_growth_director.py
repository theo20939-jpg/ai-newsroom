"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §22: GrowthDirector - a real,
deterministic advisory synthesizer over already-computed PerformancePattern evidence. Kept distinct
from services/telegram_performance_memory.py itself (spec §22: "not folded entirely into
Performance Memory") - this module answers "what does the evidence suggest we DO", Performance
Memory only tracks "what is the evidence". NO PUBLICATION AUTHORITY (spec §22) - a pure function,
no DB write, no call into any routing/publication path.

SOCIAL-INTELLIGENCE-PRELAUNCH-1A §5: `first_party_baseline` is an explicit, truthful "NONE" vs
"ESTABLISHED" label (mirrors services/telegram_performance_aggregator.py's own status vocabulary
convention) - zero PerformancePattern rows means zero eligible first-party evidence, never
silently treated as "nothing to say". `growth_hypotheses` are CLEARLY LABELED as hypotheses
(spec §5's own "must NEVER become PerformancePattern merely because the Director proposed them"
requirement) - nothing in this module or its callers ever writes a PerformancePattern row from
these strings; they exist purely for advisory display."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.telegram_performance_memory import EvidenceStage, PerformancePattern

_ACTIONABLE_STAGES = frozenset({
    EvidenceStage.POSSIBLE_SIGNAL, EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE,
})

_DEFAULT_COLD_START_HYPOTHESES = (
    "measure save/share rate on the first 10 posts before drawing any topic conclusion",
    "test whether DATA/QUOTE presentation types outperform plain NEWS in the first week",
    "test posting cadence: one editorial post per major story vs. a fixed daily minimum",
)


@dataclass(frozen=True)
class GrowthDirectorAdvisory:
    signals: list[str] = field(default_factory=list)
    fatigue: list[str] = field(default_factory=list)
    amplification_candidates: list[str] = field(default_factory=list)
    experiment_recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0
    first_party_baseline: str = "ESTABLISHED"
    growth_hypotheses: list[str] = field(default_factory=list)


def derive_growth_director_advisory(
    patterns: list[PerformancePattern], *, is_cold_start: bool = False,
) -> GrowthDirectorAdvisory:
    """Never asserts a promising/fatigued pattern from a single ANOMALY-stage observation (spec
    §26's own anti-overfit requirement, already enforced upstream by
    `services/telegram_performance_memory.py::advance_evidence_stage()` - this function trusts
    whatever stage it is handed, never re-derives or overrides it). Empty/no-evidence input states
    that plainly rather than inventing a recommendation.

    `is_cold_start=True` (spec §5) additionally attaches growth_hypotheses - clearly-labeled
    starting-point measurement/experiment ideas for a platform with zero first-party evidence,
    never presented as an already-observed pattern."""
    if not patterns:
        hypotheses = list(_DEFAULT_COLD_START_HYPOTHESES) if is_cold_start else []
        return GrowthDirectorAdvisory(
            warnings=["insufficient evidence: no performance patterns available yet"], confidence=0.0,
            first_party_baseline="NONE", growth_hypotheses=hypotheses,
        )

    signals = [p.description for p in patterns if p.stage in _ACTIONABLE_STAGES and p.effect_size > 0]
    fatigue = [p.description for p in patterns if p.stage in _ACTIONABLE_STAGES and p.effect_size < 0]
    amplification_candidates = [
        p.description for p in patterns
        if p.stage in (EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE) and p.effect_size > 0
    ]
    experiment_recommendations = [
        f"run a controlled experiment to confirm: {p.description}"
        for p in patterns if p.stage == EvidenceStage.POSSIBLE_SIGNAL
    ]
    warnings = [
        f"anomaly only, not yet actionable: {p.description}"
        for p in patterns if p.stage == EvidenceStage.ANOMALY
    ]
    confidence = max((p.confidence for p in patterns if p.stage in _ACTIONABLE_STAGES), default=0.0)

    return GrowthDirectorAdvisory(
        signals=signals, fatigue=fatigue, amplification_candidates=amplification_candidates,
        experiment_recommendations=experiment_recommendations, warnings=warnings, confidence=confidence,
    )
