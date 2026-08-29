"""Phase 20 M7: suppression-proposal policy tests. Pure, no DB - exhaustively covers the exact
policy table from the Checkpoint-1-approval message: every match_type x confidence_band x
delta_classification combination that must suppress, and every one (deliberately the vast
majority) that must not.

Phase V2.22 (real production evidence - the Sainsbury's AI-scanning story: semantic_duplicate,
score=1.0, delta_classification=minor_delta was NOT being suppressed): SEMANTIC_DUPLICATE now
additionally suppresses on MINOR_DELTA - see services/story_suppression.py's own module docstring
"Phase V2.22 correction" section for the full evidence and scoping rationale. SUPPORTING_SOURCE
deliberately keeps the original, narrower policy - the tests below are split accordingly (no
longer a single "never suppresses with any real or ambiguous delta" rule covering both).
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
@pytest.mark.parametrize("delta_classification", [MATERIAL_UPDATE, UNCERTAIN_DELTA])
def test_never_suppresses_with_material_or_ambiguous_delta(match_type: str, delta_classification: str) -> None:
    """UNCERTAIN_DELTA is conservative-false by explicit instruction (no strong replay evidence);
    MATERIAL_UPDATE is an obvious never-suppress for BOTH match types - unaffected by the V2.22
    MINOR_DELTA widening, which only ever touches the MINOR_DELTA classification specifically."""
    assert compute_would_suppress(match_type=match_type, confidence_band=HIGH, delta_classification=delta_classification) is False


def test_semantic_duplicate_now_suppresses_with_minor_delta() -> None:
    """Phase V2.22 fix: a SEMANTIC_DUPLICATE at HIGH confidence with only a minor/no-material-
    claim wording delta must suppress - real production evidence (Sainsbury's AI-scanning story,
    score=1.0, minor_delta) previously produced False here."""
    assert compute_would_suppress(match_type=SEMANTIC_DUPLICATE, confidence_band=HIGH, delta_classification=MINOR_DELTA) is True


def test_supporting_source_still_never_suppresses_with_minor_delta() -> None:
    """Phase V2.22 deliberately scopes the MINOR_DELTA widening to SEMANTIC_DUPLICATE only -
    SUPPORTING_SOURCE (a weaker, "substantially similar but not identical" same-story signal)
    keeps the original, more conservative policy."""
    assert compute_would_suppress(match_type=SUPPORTING_SOURCE, confidence_band=HIGH, delta_classification=MINOR_DELTA) is False


@pytest.mark.parametrize("match_type", [UNCERTAIN_MATCH, STORY_UPDATE, RELATED_STORY, NEW_STORY])
@pytest.mark.parametrize("confidence_band", [HIGH, MEDIUM, LOW])
@pytest.mark.parametrize("delta_classification", [NO_NEW_FACTS, CONFIRMATION_ONLY, MINOR_DELTA, MATERIAL_UPDATE, UNCERTAIN_DELTA])
def test_never_suppresses_for_non_suppressible_match_types(match_type: str, confidence_band: str, delta_classification: str) -> None:
    """UNCERTAIN_MATCH in particular must never suppress under any input combination - the
    non-negotiable 'false suppression is worse than a duplicate' rule."""
    assert compute_would_suppress(match_type=match_type, confidence_band=confidence_band, delta_classification=delta_classification) is False
