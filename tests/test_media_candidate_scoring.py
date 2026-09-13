"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 12: services.media_candidate_scoring."""
from __future__ import annotations

from datetime import datetime, timezone

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.media_candidate_scoring import is_selectable, score_candidate

_INTENT = MediaIntent(subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO)


def _candidate(
    *, subject_match: SubjectMatchClassification | None, tier: DiscoveryTier, width: int | None = 2000,
    height: int | None = 1500, usage: MediaUsageClassification = MediaUsageClassification.APPROVED_SOURCE_MEDIA,
    # RUNTIME-CLOSURE-1 (S14/S34): the scoring-dominance tests below are about subject-match/tier/
    # quality scoring, not rights classification - they need a usage class `is_selectable()` never
    # excludes so the dominance invariant they actually test remains observable. The dedicated
    # `EDITORIAL_REVIEW_REQUIRED`-exclusion behavior itself has its own explicit test below
    # (`test_editorial_review_required_is_not_selectable_regardless_of_subject_match`).
) -> ResolvedMediaCandidate:
    validation = None
    if subject_match is not None:
        validation = SubjectMatchValidation(
            depicted_subject_description="x", subject_match=subject_match, must_not_imply_violated=False,
            reason="test",
        )
    return ResolvedMediaCandidate(
        candidate_id="c1",
        provenance=MediaProvenance(
            origin_url="https://x.example/a", asset_url="https://x.example/a.jpg", discovered_at=datetime.now(timezone.utc),
            discovery_tier=tier,
        ),
        width=width, height=height, usage_classification=usage, subject_match=validation,
    )


def test_mismatch_is_not_selectable_regardless_of_everything_else() -> None:
    candidate = _candidate(subject_match=SubjectMatchClassification.MISMATCH, tier=DiscoveryTier.TIER1_CURRENT_SOURCE, width=8000, height=6000)
    assert not is_selectable(candidate)
    assert score_candidate(candidate, _INTENT) == 0.0


def test_not_usable_is_not_selectable_regardless_of_subject_match() -> None:
    candidate = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY, usage=MediaUsageClassification.NOT_USABLE)
    assert not is_selectable(candidate)
    assert score_candidate(candidate, _INTENT) == 0.0


def test_editorial_review_required_is_not_selectable_regardless_of_subject_match() -> None:
    """RUNTIME-CLOSURE-1 (S14/S34) - Founder audit finding: a candidate awaiting human rights
    review must never silently become an automatic publication asset, no matter how strong its
    subject-match verdict is."""
    candidate = _candidate(
        subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY,
        usage=MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
    )
    assert not is_selectable(candidate)
    assert score_candidate(candidate, _INTENT) == 0.0


def test_official_press_asset_remains_selectable() -> None:
    """The fix must not overreach: OFFICIAL_PRESS_ASSET (the entity's own manufacturer/press
    domain) is not "awaiting review" - it stays selectable, unlike EDITORIAL_REVIEW_REQUIRED."""
    candidate = _candidate(
        subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY,
        usage=MediaUsageClassification.OFFICIAL_PRESS_ASSET,
    )
    assert is_selectable(candidate)
    assert score_candidate(candidate, _INTENT) > 0.0


def test_dominance_invariant_weak_exact_subject_beats_strong_everything_else_mismatch() -> None:
    """Section 12's own explicit requirement: "a beautiful wrong image must lose to a slightly
    weaker correct one." Weak EXACT_SUBJECT: worst tier, tiny resolution. Strong STRONG_CONTEXT:
    best tier, huge resolution. EXACT_SUBJECT must still win."""
    weak_exact = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER5_SAFE_FALLBACK, width=100, height=100)
    strong_context_high_quality = _candidate(subject_match=SubjectMatchClassification.STRONG_CONTEXT, tier=DiscoveryTier.TIER1_CURRENT_SOURCE, width=8000, height=6000)

    assert score_candidate(weak_exact, _INTENT) > score_candidate(strong_context_high_quality, _INTENT)


def test_dominance_invariant_holds_against_generic_context_too() -> None:
    weak_exact = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER5_SAFE_FALLBACK, width=100, height=100)
    generic_high_quality = _candidate(subject_match=SubjectMatchClassification.GENERIC_CONTEXT, tier=DiscoveryTier.TIER1_CURRENT_SOURCE, width=8000, height=6000)
    assert score_candidate(weak_exact, _INTENT) > score_candidate(generic_high_quality, _INTENT)


def test_unclassified_candidate_defaults_conservatively_never_treated_as_exact() -> None:
    unclassified = _candidate(subject_match=None, tier=DiscoveryTier.TIER1_CURRENT_SOURCE, width=8000, height=6000)
    exact = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER5_SAFE_FALLBACK, width=100, height=100)
    assert score_candidate(exact, _INTENT) > score_candidate(unclassified, _INTENT)


def test_higher_source_authority_breaks_ties_among_equal_subject_match() -> None:
    tier1 = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER1_CURRENT_SOURCE)
    tier4 = _candidate(subject_match=SubjectMatchClassification.EXACT_SUBJECT, tier=DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY)
    assert score_candidate(tier1, _INTENT) > score_candidate(tier4, _INTENT)
