"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 12: bounded, deterministic candidate scoring.

Section 12's own explicit invariant - "a beautiful wrong image must lose to a slightly weaker
correct one" - is enforced STRUCTURALLY here, not just by convention: `SUBJECT_MATCH_SCORE[EXACT_
SUBJECT]` (60) is set higher than the maximum possible score any non-exact classification could
ever reach from every OTHER component combined (source authority + freshness + quality = 40 max),
so no combination of source/freshness/quality can ever let a STRONG_CONTEXT/GENERIC_CONTEXT
candidate outscore a genuine EXACT_SUBJECT one - proven directly in
tests/test_media_candidate_scoring.py, not merely asserted in a comment.

A MISMATCH candidate is not merely low-scored - `is_selectable()` excludes it (and any
`MediaUsageClassification.NOT_USABLE` candidate) from selection entirely, regardless of score
(section 10's "MISMATCH must not be selected", section 8's "NOT_USABLE... must not silently become
an unrestricted publication asset")."""
from __future__ import annotations

from schemas.media_intent import MediaIntent, OrientationPreference
from schemas.media_subject_match import DiscoveryTier, MediaUsageClassification, ResolvedMediaCandidate, SubjectMatchClassification

# Budgets (sum to 100 at most) - documented, centralized, no dead component.
SUBJECT_MATCH_SCORE: dict[SubjectMatchClassification, int] = {
    SubjectMatchClassification.EXACT_SUBJECT: 60,
    SubjectMatchClassification.STRONG_CONTEXT: 25,
    SubjectMatchClassification.GENERIC_CONTEXT: 10,
    SubjectMatchClassification.MISMATCH: 0,
}
SOURCE_AUTHORITY_SCORE: dict[DiscoveryTier, int] = {
    DiscoveryTier.TIER1_CURRENT_SOURCE: 20,
    DiscoveryTier.TIER2_OFFICIAL_PRIMARY: 20,
    DiscoveryTier.TIER3_CORROBORATING_EDITORIAL: 14,
    DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY: 8,
    DiscoveryTier.TIER5_SAFE_FALLBACK: 4,
}
FRESHNESS_MAX = 10
QUALITY_MAX = 10

assert SUBJECT_MATCH_SCORE[SubjectMatchClassification.EXACT_SUBJECT] > (
    max(SOURCE_AUTHORITY_SCORE.values()) + FRESHNESS_MAX + QUALITY_MAX
), "the section-12 dominance invariant must hold by construction, not by convention"


def _orientation_matches(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> bool:
    if intent.orientation_preference is OrientationPreference.ANY:
        return True
    return candidate.orientation == intent.orientation_preference.value


def _quality_score(candidate: ResolvedMediaCandidate) -> int:
    """Resolution-based only, deliberately simple - a real perceptual-quality model is out of this
    phase's scope (never invented here); reuses the same coarse "is this at least a usable
    resolution" judgment `services/image_quality.py::resolution_band()` already makes elsewhere,
    without importing that module's Phase-16-specific bands directly (this scorer intentionally
    stays independent of the Telegram-side pipeline's own calibration - section 14's own "avoid
    unnecessary coupling" spirit)."""
    if candidate.width is None or candidate.height is None:
        return QUALITY_MAX // 2  # unknown - neutral, never penalized to zero for missing metadata
    pixel_count = candidate.width * candidate.height
    if pixel_count >= 500_000:
        return QUALITY_MAX
    if pixel_count >= 150_000:
        return round(QUALITY_MAX * 0.6)
    return round(QUALITY_MAX * 0.2)


def _freshness_score(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> int:
    """Deliberately conservative - this phase does not build a date-parsing subsystem. A Tier-1
    candidate (the NewsEvent's own already-vetted source) is always treated as current enough (it
    IS the story); anything else gets neutral credit unless discovery evidence says otherwise -
    never a fabricated freshness claim from an unverified date string."""
    if candidate.provenance.discovery_tier is DiscoveryTier.TIER1_CURRENT_SOURCE:
        return FRESHNESS_MAX
    return round(FRESHNESS_MAX * 0.7)


def is_selectable(candidate: ResolvedMediaCandidate) -> bool:
    """Section 8/10's hard exclusions - never a matter of score.

    RUNTIME-CLOSURE-1 (S14/S34): `EDITORIAL_REVIEW_REQUIRED` is excluded here too, not merely
    low-scored - Founder audit finding "a candidate called EDITORIAL_REVIEW_REQUIRED must not
    silently become an automatic publication asset". Before this fix, only `NOT_USABLE` and
    `MISMATCH` were hard-excluded; a high-scoring, subject-verified-correct but rights-unverified
    third-party photo could still win automatic selection - exactly the silent-approval gap S14
    describes. `APPROVED_SOURCE_MEDIA` (Tier 1 - the NewsEvent's own already-vetted source) and
    `OFFICIAL_PRESS_ASSET` remain selectable; only `EDITORIAL_REVIEW_REQUIRED` (S14's own "a human
    editor must decide before this ever becomes a publication asset") and `NOT_USABLE` are
    excluded from AUTOMATIC selection here. This does not delete the candidate: a caller may still
    surface it for human review, use it as the basis for a truthful fallback search, or choose a
    truthful alternate composition (S14's own disclosed options) - `is_selectable()` only answers
    "may this be chosen without a human in the loop", never "does this candidate exist"."""
    if candidate.usage_classification in (
        MediaUsageClassification.NOT_USABLE, MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED,
    ):
        return False
    if candidate.subject_match is not None and candidate.subject_match.subject_match is SubjectMatchClassification.MISMATCH:
        return False
    return True


def score_candidate(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> float:
    """Returns 0 for anything `is_selectable()` rejects - callers should still call
    `is_selectable()` explicitly before treating a 0 score as "merely weak" (section 10: a MISMATCH
    is disqualified, not just penalized, and the two are distinguishable in `MediaSelectionResult.
    rejection_reasons`, never silently conflated)."""
    if not is_selectable(candidate):
        return 0.0

    subject_score = (
        SUBJECT_MATCH_SCORE[candidate.subject_match.subject_match] if candidate.subject_match is not None
        else SUBJECT_MATCH_SCORE[SubjectMatchClassification.GENERIC_CONTEXT]  # unclassified - never
        # assumed EXACT; treated as the same conservative default section 11 implies for unverified media
    )
    authority_score = SOURCE_AUTHORITY_SCORE.get(candidate.provenance.discovery_tier, 0)
    freshness = _freshness_score(candidate, intent)
    quality = _quality_score(candidate)

    total: float = subject_score + authority_score + freshness + quality
    if not _orientation_matches(candidate, intent):
        total *= 0.9  # a small, non-dominant nudge - never enough to overturn subject-match dominance
    return round(total, 2)
