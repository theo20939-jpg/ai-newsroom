"""CROSS-PLATFORM-MEDIA-RESEARCH-SELECTION-1 section 2/11: services.media_research_selection."""
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
    SubjectMatchValidation,
)
from services.media_research_selection import research_and_select_media
from services.media_web_discovery import NullWebDiscoveryClient

_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", model_name="iPhone Duo",
    company="Apple", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
)


def _candidate(candidate_id: str, *, tier: DiscoveryTier = DiscoveryTier.TIER4_WEB_IMAGE_DISCOVERY, usage: MediaUsageClassification = MediaUsageClassification.EDITORIAL_REVIEW_REQUIRED, subject_match: SubjectMatchClassification | None = None) -> ResolvedMediaCandidate:
    validation = None
    if subject_match is not None:
        validation = SubjectMatchValidation(depicted_subject_description="x", subject_match=subject_match, must_not_imply_violated=False, reason="test")
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url=f"https://x.example/{candidate_id}", asset_url=f"https://x.example/{candidate_id}.jpg",
            discovered_at=datetime.now(timezone.utc), discovery_tier=tier,
        ),
        width=1200, height=900, usage_classification=usage, subject_match=validation,
    )


@pytest.mark.asyncio
async def test_selects_the_exact_subject_candidate_over_the_wrong_ordinary_one() -> None:
    """The literal INSTAGRAM-AUTONOMOUS-TREND-TO-CAROUSEL-CANARY-1 failure this whole phase
    exists to fix: an ordinary/generic candidate must never win over a genuinely exact one."""
    wrong_ordinary_iphone = _candidate("ordinary_iphone", tier=DiscoveryTier.TIER1_CURRENT_SOURCE, subject_match=SubjectMatchClassification.MISMATCH)
    correct_foldable = _candidate("foldable_duo", tier=DiscoveryTier.TIER3_CORROBORATING_EDITORIAL, subject_match=SubjectMatchClassification.EXACT_SUBJECT)

    result = await research_and_select_media(
        _INTENT, tier1_candidates=[wrong_ordinary_iphone], web_discovery_client=NullWebDiscoveryClient(),
    )
    # NullWebDiscoveryClient discovers nothing, so inject the "web-found" correct candidate the
    # same way discover_web_candidates would have - via tier1_candidates for this unit test's
    # purposes (the orchestrator does not care which list a candidate arrived in).
    result2 = await research_and_select_media(
        _INTENT, tier1_candidates=[wrong_ordinary_iphone, correct_foldable], web_discovery_client=NullWebDiscoveryClient(),
    )

    assert result.selected is None or result.selected.candidate_id != "ordinary_iphone"
    assert result2.selected is not None
    assert result2.selected.candidate_id == "foldable_duo"
    assert result2.exact_subject_media_not_found is False
    assert any("mismatch" in r for r in result2.rejection_reasons)


@pytest.mark.asyncio
async def test_no_selectable_candidate_falls_back_and_discloses_not_found() -> None:
    only_mismatch = _candidate("wrong", subject_match=SubjectMatchClassification.MISMATCH)
    fallback = _candidate("graphic_fallback", tier=DiscoveryTier.TIER5_SAFE_FALLBACK)

    result = await research_and_select_media(
        _INTENT, tier1_candidates=[only_mismatch], web_discovery_client=NullWebDiscoveryClient(),
        fallback_candidate=fallback,
    )

    assert result.exact_subject_media_not_found is True
    assert result.fallback_used is True
    assert result.selected is not None
    assert result.selected.candidate_id == "graphic_fallback"


@pytest.mark.asyncio
async def test_no_candidates_at_all_and_no_fallback_selects_nothing() -> None:
    result = await research_and_select_media(_INTENT, web_discovery_client=NullWebDiscoveryClient())
    assert result.selected is None
    assert result.exact_subject_media_not_found is True
    assert result.fallback_used is False
    assert result.candidates_considered == 0


@pytest.mark.asyncio
async def test_strong_context_selected_when_no_exact_subject_exists_but_still_flags_not_found() -> None:
    strong_context = _candidate("family_photo", subject_match=SubjectMatchClassification.STRONG_CONTEXT)
    result = await research_and_select_media(_INTENT, tier1_candidates=[strong_context], web_discovery_client=NullWebDiscoveryClient())

    assert result.selected is not None
    assert result.selected.candidate_id == "family_photo"
    assert result.exact_subject_media_not_found is True  # selected, but NOT an exact-subject claim
    assert result.fallback_used is False


@pytest.mark.asyncio
async def test_subject_match_classifier_is_invoked_and_result_attached() -> None:
    unclassified = _candidate("needs_classification")
    calls: list[str] = []

    async def classifier(candidate, intent):
        calls.append(candidate.candidate_id)
        return SubjectMatchValidation(
            depicted_subject_description="the exact product", subject_match=SubjectMatchClassification.EXACT_SUBJECT,
            must_not_imply_violated=False, reason="matches",
        )

    result = await research_and_select_media(
        _INTENT, tier1_candidates=[unclassified], web_discovery_client=NullWebDiscoveryClient(),
        subject_match_classifier=classifier,
    )

    assert calls == ["needs_classification"]
    assert result.selected is not None
    assert result.selected.subject_match is not None
    assert result.selected.subject_match.subject_match is SubjectMatchClassification.EXACT_SUBJECT
    assert result.exact_subject_media_not_found is False


@pytest.mark.asyncio
async def test_classifier_failure_does_not_abort_the_whole_selection() -> None:
    candidate_a = _candidate("a")
    candidate_b = _candidate("b", subject_match=SubjectMatchClassification.EXACT_SUBJECT)

    async def flaky_classifier(candidate, intent):
        if candidate.candidate_id == "a":
            raise RuntimeError("simulated provider failure")
        return candidate.subject_match

    result = await research_and_select_media(
        _INTENT, tier1_candidates=[candidate_a, candidate_b], web_discovery_client=NullWebDiscoveryClient(),
        subject_match_classifier=flaky_classifier,
    )
    assert result.selected is not None
    assert result.selected.candidate_id == "b"
