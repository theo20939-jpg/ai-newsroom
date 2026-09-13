"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-FINAL-HARDENING-1 §9/§10: end-to-end media-selection
replays through the REAL `services.editorial_pipeline.media.MediaResearchService.research()` (which
itself calls the real, unmodified `services.media_research_selection.research_and_select_media()`
and `services.media_candidate_scoring.py` dominance/exclusion policy) with the real, newly-wired
`services.editorial_pipeline.subject_match.classify_subject_match()` injected as the
`subject_match_classifier` - exactly how `services.editorial_pipeline.telegram_integration.py`
wires it in production. This proves SELECTION behavior, not merely classification output (see
tests/test_unified_pipeline_subject_match_classifier.py for the classifier's own unit tests).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
)
from services.editorial_pipeline.media import MediaResearchService
from services.editorial_pipeline.subject_match import classify_subject_match

pytestmark = pytest.mark.asyncio


def _candidate(
    candidate_id: str, caption_or_alt: str, *,
    discovery_tier: DiscoveryTier = DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY,
    usage_classification: MediaUsageClassification = MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
    width: int | None = 1600, height: int | None = 1200,
) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url=f"https://example.com/{candidate_id}",
            asset_url=f"https://example.com/{candidate_id}.jpg",
            discovered_at=datetime.now(timezone.utc),
            discovery_tier=discovery_tier,
            caption_or_alt=caption_or_alt,
        ),
        usage_classification=usage_classification,
        width=width, height=height,
    )


# ---------------------------------------------------------------------------
# §9 MANDATORY - the Founder-discovered foldable iPhone case
# ---------------------------------------------------------------------------

_FOLDABLE_IPHONE_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT,
    primary_entity="Apple's newly announced foldable iPhone",
    product_name="iPhone",
    model_name="foldable iPhone",
    company="Apple",
    must_show=["foldable design"],
    must_not_imply=["standard non-folding design"],
    desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)

# A. ordinary current-generation non-foldable iPhone image
_CANDIDATE_A_ORDINARY_IPHONE = _candidate(
    "candidate-a-ordinary-iphone",
    "Apple iPhone 16 Pro Max in Desert Titanium, standard non-folding design, studio photo",
    discovery_tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY,  # high authority/reputable source
    usage_classification=MediaUsageClassification.OFFICIAL_PRESS_ASSET,
    width=6000, height=4000,  # excellent resolution - must still lose
)

# B. truthful contextual Apple imagery (a safe, non-deceptive fallback)
_CANDIDATE_B_CONTEXTUAL_APPLE = _candidate(
    "candidate-b-contextual-apple",
    "Apple corporate logo and Apple Park campus signage, generic corporate context photo",
    discovery_tier=DiscoveryTier.TIER5_SAFE_FALLBACK,
)

# C. an exact foldable candidate (only present in some scenarios)
_CANDIDATE_C_EXACT_FOLDABLE = _candidate(
    "candidate-c-exact-foldable",
    "Apple's newly unveiled foldable iPhone concept, folded and unfolded views showing the foldable design",
    discovery_tier=DiscoveryTier.TIER3_CORROBORATING_EDITORIAL,
    width=800, height=600,  # deliberately LOWER quality than candidate A - must still win
)


async def test_foldable_iphone_ordinary_candidate_is_classified_mismatch() -> None:
    result = await classify_subject_match(_CANDIDATE_A_ORDINARY_IPHONE, _FOLDABLE_IPHONE_INTENT)
    assert result.subject_match == SubjectMatchClassification.MISMATCH


async def test_foldable_iphone_replay_exact_candidate_present_wins_over_wrong_and_generic() -> None:
    """C exists -> C must be selected, never A (wrong subject) and never B (generic fallback,
    unnecessarily weaker than a real, confirmed exact candidate)."""
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT,
        tier1_candidates=[_CANDIDATE_A_ORDINARY_IPHONE, _CANDIDATE_B_CONTEXTUAL_APPLE, _CANDIDATE_C_EXACT_FOLDABLE],
        subject_match_classifier=classify_subject_match,
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "candidate-c-exact-foldable"
    WRONG_IPHONE_IMAGE_SELECTED = selection.selected.candidate_id == "candidate-a-ordinary-iphone"
    assert WRONG_IPHONE_IMAGE_SELECTED is False


async def test_foldable_iphone_replay_no_exact_candidate_falls_to_truthful_contextual_fallback() -> None:
    """C does NOT exist -> the system must choose B (truthful contextual fallback), never A (the
    wrong-subject candidate), even though A has better resolution and a more reputable/official
    source classification."""
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT,
        tier1_candidates=[_CANDIDATE_A_ORDINARY_IPHONE, _CANDIDATE_B_CONTEXTUAL_APPLE],
        subject_match_classifier=classify_subject_match,
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "candidate-b-contextual-apple"
    WRONG_IPHONE_IMAGE_SELECTED = selection.selected.candidate_id == "candidate-a-ordinary-iphone"
    assert WRONG_IPHONE_IMAGE_SELECTED is False
    assert "candidate-a-ordinary-iphone: subject_match=mismatch" in " ".join(selection.rejection_reasons)


async def test_foldable_iphone_replay_only_wrong_candidate_available_never_selected_as_exact() -> None:
    """Only the wrong candidate exists at all - it must never be selected, and the result must
    honestly report no usable candidate (exact_subject_media_not_found=True, no fallback
    available) rather than silently accepting the mismatch."""
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT,
        tier1_candidates=[_CANDIDATE_A_ORDINARY_IPHONE],
        subject_match_classifier=classify_subject_match,
    )
    assert selection.selected is None
    assert selection.exact_subject_media_not_found is True
    WRONG_IPHONE_IMAGE_SELECTED = selection.selected is not None and selection.selected.candidate_id == "candidate-a-ordinary-iphone"
    assert WRONG_IPHONE_IMAGE_SELECTED is False


# ---------------------------------------------------------------------------
# §10 item 8 - a lower-quality EXACT candidate must beat a high-quality MISMATCH, at the real
# selection layer (not merely the classifier's own output - see test_unified_pipeline_subject_
# match_classifier.py for that narrower proof).
# ---------------------------------------------------------------------------


async def test_low_quality_exact_candidate_beats_high_quality_mismatch_at_selection() -> None:
    service = MediaResearchService()
    selection = await service.research(
        _FOLDABLE_IPHONE_INTENT,
        tier1_candidates=[_CANDIDATE_A_ORDINARY_IPHONE, _CANDIDATE_C_EXACT_FOLDABLE],
        subject_match_classifier=classify_subject_match,
    )
    assert selection.selected is not None
    assert selection.selected.candidate_id == "candidate-c-exact-foldable"
    assert selection.selected.width == 800  # confirms the LOWER-resolution candidate won on
    # identity, never merely because it happened to also be technically better
