"""Phase 20 M7: suppression-proposal policy tests. Pure, no DB - exhaustively covers the exact
policy table from the Checkpoint-1-approval message: every match_type x confidence_band x
delta_classification combination that must suppress, and every one (deliberately the vast
majority) that must not.
"""
import pytest

from services.story_confidence import HIGH, LOW, MEDIUM
from services.story_delta_engine import (
    CONFIRMATION_ONLY,
    MATERIAL_UPDATE,
    MINOR_DELTA,
    NO_NEW_FACTS,
    UNCERTAIN_DELTA,
)
from services.story_memory import (
    NEW_STORY,
    RELATED_STORY,
    SEMANTIC_DUPLICATE,
    STORY_UPDATE,
    SUPPORTING_SOURCE,
    UNCERTAIN_MATCH,
)
from services.story_suppression import compute_would_suppress

_NO_MATERIAL_DELTA = (NO_NEW_FACTS, CONFIRMATION_ONLY)


@pytest.mark.parametrize("match_type", [SEMANTIC_DUPLICATE, SUPPORTING_SOURCE])
@pytest.mark.parametrize("delta_classification", _NO_MATERIAL_DELTA)
def test_suppresses_when_high_confidence_same_story_with_no_material_delta(match_type: str, delta_classification: str) -> None:
    assert compute_would_suppress(match_type=match_type, confidence_band=HIGH, delta_classification=delta_classification) is True


@pytest.mark.parametrize("match_type", [SEMANTIC_DUPLICATE, SUPPORTING_SOURCE])
@pytest.mark.parametrize("confidence_band", [MEDIUM, LOW])
def test_never_suppresses_below_high_confidence(match_type: str, confidence_band: str) -> None:
    assert compute_would_suppress(match_type=match_type, confidence_band=confidence_band, delta_classification=NO_NEW_FACTS) is False


@pytest.mark.parametrize("match_type", [SEMANTIC_DUPLICATE, SUPPORTING_SOURCE])
@pytest.mark.parametrize("delta_classification", [MINOR_DELTA, MATERIAL_UPDATE, UNCERTAIN_DELTA])
def test_never_suppresses_with_any_real_or_ambiguous_delta(match_type: str, delta_classification: str) -> None:
    """MINOR_DELTA and UNCERTAIN_DELTA are conservative-false by explicit instruction (no strong
    replay evidence yet); MATERIAL_UPDATE is an obvious never-suppress."""
    assert compute_would_suppress(match_type=match_type, confidence_band=HIGH, delta_classification=delta_classification) is False


@pytest.mark.parametrize("match_type", [UNCERTAIN_MATCH, STORY_UPDATE, RELATED_STORY, NEW_STORY])
@pytest.mark.parametrize("confidence_band", [HIGH, MEDIUM, LOW])
@pytest.mark.parametrize("delta_classification", [NO_NEW_FACTS, CONFIRMATION_ONLY, MINOR_DELTA, MATERIAL_UPDATE, UNCERTAIN_DELTA])
def test_never_suppresses_for_non_suppressible_match_types(match_type: str, confidence_band: str, delta_classification: str) -> None:
    """UNCERTAIN_MATCH in particular must never suppress under any input combination - the
    non-negotiable 'false suppression is worse than a duplicate' rule."""
    assert compute_would_suppress(match_type=match_type, confidence_band=confidence_band, delta_classification=delta_classification) is False
