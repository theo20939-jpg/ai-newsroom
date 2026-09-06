"""SOCIAL-INTELLIGENCE-PRELAUNCH-1A §9: direct unit coverage of the promotion rule
services/instagram_content_brain.py::advance_intelligence_evidence_stage() enforces - a
HYPOTHESIS-sourced insight (a director's own suggestion with zero real observation behind it) can
never be promoted into OBSERVATION/POSSIBLE_SIGNAL/REPEATED_PATTERN/STABLE_WORKING_RULE by anything
other than real observation_count increments, and the chain itself is never skipped."""
from __future__ import annotations

from database.models.instagram_shared import IntelligenceEvidenceStage
from services.instagram_content_brain import advance_intelligence_evidence_stage


def test_hypothesis_only_never_promotes_regardless_of_count() -> None:
    """A director's own suggestion, however large a count is (mis)supplied, stays HYPOTHESIS -
    is_hypothesis_only is a hard override, never a default that real evidence can quietly beat."""
    for count in (0, 1, 10, 1000):
        assert advance_intelligence_evidence_stage(observation_count=count, is_hypothesis_only=True) == (
            IntelligenceEvidenceStage.HYPOTHESIS
        )


def test_real_evidence_promotes_through_every_stage_in_order() -> None:
    """The chain HYPOTHESIS -> OBSERVATION -> POSSIBLE_SIGNAL -> REPEATED_PATTERN ->
    STABLE_WORKING_RULE is never skipped - each threshold is crossed once, in order, as real
    observation_count grows."""
    stages_in_order = [
        advance_intelligence_evidence_stage(observation_count=0, is_hypothesis_only=False),
        advance_intelligence_evidence_stage(observation_count=1, is_hypothesis_only=False),
        advance_intelligence_evidence_stage(observation_count=2, is_hypothesis_only=False),
        advance_intelligence_evidence_stage(observation_count=4, is_hypothesis_only=False),
        advance_intelligence_evidence_stage(observation_count=10, is_hypothesis_only=False),
    ]
    assert stages_in_order == [
        IntelligenceEvidenceStage.OBSERVATION, IntelligenceEvidenceStage.OBSERVATION,
        IntelligenceEvidenceStage.POSSIBLE_SIGNAL, IntelligenceEvidenceStage.REPEATED_PATTERN,
        IntelligenceEvidenceStage.STABLE_WORKING_RULE,
    ]
