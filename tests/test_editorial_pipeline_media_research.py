"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 S16/S28-B: the foldable-iPhone-class replay, as a fast,
deterministic, always-runnable regression test (no network, no real LLM call - those already
happened as a real, live replay documented in the report and in artifacts/
cross_platform_media_research_canary_1/, using the real scripts/_cross_platform_media_research_
canary_1.py against real downloaded photos and a real OpenAI vision call - see report S O for that
run's actual numbers: candidates_considered=4, exact_subject_media_not_found=False,
selected=web:0:macrumors.com, selected_score=86.0, the wrong local iPhone correctly rejected as
MISMATCH).

This test proves the same SELECTION LOGIC (dominance-by-construction scoring, MISMATCH exclusion)
deterministically, with a fake classifier standing in for the real vision-LLM call, so it can run in
every CI/regression pass without cost or network access.
"""
from datetime import datetime, timezone

import pytest

from schemas.media_intent import DesiredVisualType, MediaIntent, MediaSubjectType, OrientationPreference
from schemas.media_subject_match import (
    DiscoveryTier,
    MediaProvenance,
    MediaUsageClassification,
    ResolvedMediaCandidate,
    SubjectMatchClassification,
    SubjectMatchValidation,
)
from services.editorial_pipeline.media import MediaResearchService

pytestmark = pytest.mark.asyncio

_INTENT = MediaIntent(
    subject_type=MediaSubjectType.PRODUCT, primary_entity="iPhone Duo", product_name="iPhone Duo",
    model_name="iPhone Duo", company="Apple", desired_visual_type=DesiredVisualType.PRODUCT_PHOTO,
    orientation_preference=OrientationPreference.ANY, platform="instagram",
    must_not_imply=["that an ordinary, non-foldable iPhone is the iPhone Duo"],
)


def _candidate(candidate_id: str, *, tier: DiscoveryTier, quality_hint: str) -> ResolvedMediaCandidate:
    return ResolvedMediaCandidate(
        candidate_id=candidate_id,
        provenance=MediaProvenance(
            origin_url=f"https://example.com/{candidate_id}", asset_url=f"https://example.com/{candidate_id}.jpg",
            publisher_domain="example.com", discovered_at=datetime.now(timezone.utc), discovery_tier=tier,
            caption_or_alt=quality_hint,
        ),
        width=4000 if quality_hint == "high_res_wrong" else 800,
        height=3000 if quality_hint == "high_res_wrong" else 600,
        usage_classification=MediaUsageClassification.APPROVED_SOURCE_MEDIA,
    )


async def test_exact_subject_beats_a_higher_resolution_mismatch() -> None:
    """S12's own literal requirement: 'a high-resolution beautiful wrong image must lose to a
    lower-quality truthful image.' The MISMATCH candidate here is 4000x3000 (deliberately much
    higher resolution); the EXACT_SUBJECT candidate is a modest 800x600 - the exact shape of the
    real iPhone-Duo defect (a locally-available, presentable ordinary iPhone photo beating a real,
    lower-resolution foldable photo purely on availability/quality, never on subject correctness)."""
    wrong_high_res = _candidate("ordinary_iphone_4k", tier=DiscoveryTier.TIER1_CURRENT_SOURCE, quality_hint="high_res_wrong")
    correct_low_res = _candidate("iphone_duo_real", tier=DiscoveryTier.TIER2_OFFICIAL_PRIMARY, quality_hint="modest_but_correct")

    async def fake_classifier(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> SubjectMatchValidation:
        verdict = (
            SubjectMatchClassification.MISMATCH if candidate.candidate_id == "ordinary_iphone_4k"
            else SubjectMatchClassification.EXACT_SUBJECT
        )
        return SubjectMatchValidation(
            depicted_subject_description="test", subject_match=verdict, must_not_imply_violated=False,
            confidence="high", reason="test fixture",
        )

    service = MediaResearchService()
    result = await service.research(
        _INTENT, tier1_candidates=[wrong_high_res, correct_low_res], subject_match_classifier=fake_classifier,
    )

    assert result.selected is not None
    assert result.selected.candidate_id == "iphone_duo_real"
    assert result.exact_subject_media_not_found is False


async def test_mismatch_can_never_be_selected_even_with_no_alternative() -> None:
    only_wrong = _candidate("ordinary_iphone_only", tier=DiscoveryTier.TIER1_CURRENT_SOURCE, quality_hint="high_res_wrong")

    async def always_mismatch(candidate: ResolvedMediaCandidate, intent: MediaIntent) -> SubjectMatchValidation:
        return SubjectMatchValidation(
            depicted_subject_description="an ordinary iPhone", subject_match=SubjectMatchClassification.MISMATCH,
            must_not_imply_violated=True, confidence="high", reason="wrong product entirely",
        )

    service = MediaResearchService()
    result = await service.research(_INTENT, tier1_candidates=[only_wrong], subject_match_classifier=always_mismatch)

    assert result.selected is None
    assert result.exact_subject_media_not_found is True  # truthfully reported (S16), never hidden


async def test_no_candidates_at_all_reports_not_found_truthfully() -> None:
    service = MediaResearchService()
    result = await service.research(_INTENT, tier1_candidates=[])
    assert result.selected is None
    assert result.exact_subject_media_not_found is True
    assert result.candidates_considered == 0
