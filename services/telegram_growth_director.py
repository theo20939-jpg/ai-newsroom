"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §22: GrowthDirector - a real,
deterministic advisory synthesizer over already-computed PerformancePattern evidence. Kept distinct
from services/telegram_performance_memory.py itself (spec §22: "not folded entirely into
Performance Memory") - this module answers "what does the evidence suggest we DO", Performance
Memory only tracks "what is the evidence". NO PUBLICATION AUTHORITY (spec §22) - a pure function,
no DB write, no call into any routing/publication path."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.telegram_performance_memory import EvidenceStage, PerformancePattern

_ACTIONABLE_STAGES = frozenset({
    EvidenceStage.POSSIBLE_SIGNAL, EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE,
})


@dataclass(frozen=True)
class GrowthDirectorAdvisory:
    signals: list[str] = field(default_factory=list)
    fatigue: list[str] = field(default_factory=list)
    amplification_candidates: list[str] = field(default_factory=list)
    experiment_recommendations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    confidence: float = 0.0


def derive_growth_director_advisory(patterns: list[PerformancePattern]) -> GrowthDirectorAdvisory:
    """Never asserts a promising/fatigued pattern from a single ANOMALY-stage observation (spec
    §26's own anti-overfit requirement, already enforced upstream by
    `services/telegram_performance_memory.py::advance_evidence_stage()` - this function trusts
    whatever stage it is handed, never re-derives or overrides it). Empty/no-evidence input states
    that plainly rather than inventing a recommendation."""
    if not patterns:
        return GrowthDirectorAdvisory(
            warnings=["insufficient evidence: no performance patterns available yet"], confidence=0.0,
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
