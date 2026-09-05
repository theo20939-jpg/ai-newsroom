"""INSTAGRAM GROWTH ENGINE v2, spec §71: Growth Autopsy tests."""
from __future__ import annotations

from services.instagram_content_brain import EvidenceStage
from services.instagram_growth_autopsy import run_growth_autopsy


def test_no_observation_is_reported_as_unavailable_not_zero_effect() -> None:
    result = run_growth_autopsy(subject="reel-1", expected_outcome="high reach", observed_value=None, baseline=None)
    assert "no performance observation" in result.observed_outcome
    assert result.confidence == 0.0


def test_no_baseline_prevents_causal_conclusion() -> None:
    result = run_growth_autopsy(
        subject="reel-2", expected_outcome="high reach", observed_value=5000.0, baseline=None,
        candidate_explanations=["the hook worked"],
    )
    assert "no baseline" in result.baseline_comparison
    assert result.unsupported_hypotheses == ["the hook worked"]
    assert result.supported_explanations == []


def test_single_post_cannot_create_a_stable_rule() -> None:
    """ANOMALY/POSSIBLE_SIGNAL evidence must never promote a candidate explanation to
    supported - only REPEATED_PATTERN/STABLE_WORKING_RULE can."""
    result = run_growth_autopsy(
        subject="reel-3", expected_outcome="high reach", observed_value=5000.0, baseline=2000.0,
        evidence_stage=EvidenceStage.ANOMALY, candidate_explanations=["the hook worked"],
    )
    assert result.unsupported_hypotheses == ["the hook worked"]
    assert result.supported_explanations == []
    assert result.next_experiment_suggestions


def test_repeated_pattern_evidence_supports_the_explanation() -> None:
    result = run_growth_autopsy(
        subject="reel-4", expected_outcome="high reach", observed_value=5000.0, baseline=2000.0,
        evidence_stage=EvidenceStage.REPEATED_PATTERN, candidate_explanations=["the hook worked"],
    )
    assert result.supported_explanations == ["the hook worked"]
    assert result.unsupported_hypotheses == []


def test_next_experiment_may_be_suggested_when_evidence_is_thin() -> None:
    result = run_growth_autopsy(
        subject="reel-5", expected_outcome="high reach", observed_value=1000.0, baseline=2000.0,
        evidence_stage=EvidenceStage.POSSIBLE_SIGNAL, candidate_explanations=["bad timing"],
    )
    assert result.next_experiment_suggestions
