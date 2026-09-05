"""INSTAGRAM GROWTH ENGINE v2, spec §48: Growth Autopsy - upgrades
services/instagram_growth_strategist.py::GrowthAutopsy from a structure-only contract into a real
evidence-driven service. Strict discipline (spec §48's own "no hindsight storytelling" instruction):
a candidate explanation is only ever `supported_explanations` when the EvidenceStage backing it is
already REPEATED_PATTERN/STABLE_WORKING_RULE (services/instagram_content_brain.py) - a single
post's autopsy NEVER manufactures a causal conclusion on its own, and a missing baseline/observation
is reported as exactly that, never silently treated as "no effect"."""
from __future__ import annotations

from dataclasses import dataclass, field

from services.instagram_content_brain import EvidenceStage

_STAGES_ALLOWING_SUPPORTED_EXPLANATION = (EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE)


@dataclass(frozen=True)
class GrowthAutopsyResult:
    subject: str
    observed_outcome: str
    expected_outcome: str
    baseline_comparison: str
    supported_explanations: list[str] = field(default_factory=list)
    unsupported_hypotheses: list[str] = field(default_factory=list)
    next_experiment_suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.1


def run_growth_autopsy(
    *, subject: str, expected_outcome: str, observed_value: float | None, baseline: float | None,
    evidence_stage: EvidenceStage | None = None, candidate_explanations: list[str] | None = None,
) -> GrowthAutopsyResult:
    candidates = list(candidate_explanations or [])

    if observed_value is None:
        return GrowthAutopsyResult(
            subject=subject, observed_outcome="no performance observation available",
            expected_outcome=expected_outcome, baseline_comparison="unavailable - nothing was observed",
            unsupported_hypotheses=candidates,
            next_experiment_suggestions=["instrument this content once real performance ingestion exists"],
            confidence=0.0,
        )

    if baseline is None:
        return GrowthAutopsyResult(
            subject=subject, observed_outcome=f"observed={observed_value}", expected_outcome=expected_outcome,
            baseline_comparison="no baseline available - over/under-performance cannot be judged",
            unsupported_hypotheses=candidates,
            next_experiment_suggestions=["establish a baseline before drawing any conclusion"], confidence=0.1,
        )

    delta = observed_value - baseline
    comparison = f"observed={observed_value} vs baseline={baseline} (delta={delta:+.2f})"

    if evidence_stage in _STAGES_ALLOWING_SUPPORTED_EXPLANATION:
        return GrowthAutopsyResult(
            subject=subject, observed_outcome=f"observed={observed_value}", expected_outcome=expected_outcome,
            baseline_comparison=comparison, supported_explanations=candidates, confidence=0.5,
        )

    return GrowthAutopsyResult(
        subject=subject, observed_outcome=f"observed={observed_value}", expected_outcome=expected_outcome,
        baseline_comparison=comparison, unsupported_hypotheses=candidates,
        next_experiment_suggestions=["run this as a controlled experiment before drawing a causal conclusion"],
        confidence=0.2,
    )
