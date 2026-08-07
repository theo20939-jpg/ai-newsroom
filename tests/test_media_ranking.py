"""Phase 19 M11: services.media_ranking.rank_media_candidates() - pure, deterministic, no I/O."""
from __future__ import annotations

import uuid

from schemas.media_ranking import MediaRankingInput, RecommendedRole
from services.media_ranking import is_perceptually_reused, rank_media_candidates


def _input(**overrides: object) -> MediaRankingInput:
    defaults: dict[str, object] = dict(
        media_item_id=uuid.uuid4(), media_type="image", quality_score=70, source_priority=15,
    )
    defaults.update(overrides)
    return MediaRankingInput(**defaults)  # type: ignore[arg-type]


def test_higher_quality_image_ranks_above_lower_quality_image() -> None:
    good = _input(quality_score=80)
    weak = _input(quality_score=30)
    results = rank_media_candidates([weak, good])
    assert results[0].media_item_id == good.media_item_id
    assert results[0].recommended_order == 0
    assert results[1].media_item_id == weak.media_item_id


def test_ties_preserve_input_order() -> None:
    first = _input(quality_score=70, source_priority=15)
    second = _input(quality_score=70, source_priority=15)
    results = rank_media_candidates([first, second])
    assert results[0].media_item_id == first.media_item_id
    assert results[1].media_item_id == second.media_item_id


def test_low_quality_image_is_ineligible_for_delivery() -> None:
    result = rank_media_candidates([_input(quality_score=10)])[0]
    assert result.eligible_for_delivery is False
    assert result.recommended_role == RecommendedRole.REJECT


def test_story_reuse_match_is_ineligible_and_never_hero() -> None:
    result = rank_media_candidates([_input(quality_score=90, story_reuse_match=True)])[0]
    assert result.eligible_for_delivery is False
    assert result.story_reuse_penalty > 0
    assert result.recommended_role == RecommendedRole.REJECT


def test_rejected_video_is_ineligible() -> None:
    result = rank_media_candidates(
        [_input(media_type="video", quality_score=80, video_validation_status="rejected")]
    )[0]
    assert result.eligible_for_delivery is False
    assert result.recommended_role == RecommendedRole.REJECT


def test_valid_video_with_tv_like_aspect_is_demo_video() -> None:
    result = rank_media_candidates(
        [_input(
            media_type="video", quality_score=80, video_validation_status="valid",
            aspect_ratio_band="editorial_landscape",
        )]
    )[0]
    assert result.recommended_role == RecommendedRole.DEMO_VIDEO
    assert result.eligible_for_delivery is True


def test_valid_video_without_tv_like_aspect_is_context_video() -> None:
    result = rank_media_candidates(
        [_input(media_type="video", quality_score=80, video_validation_status="valid", aspect_ratio_band="portrait")]
    )[0]
    assert result.recommended_role == RecommendedRole.CONTEXT_VIDEO


def test_high_quality_landscape_image_with_no_branding_risk_is_hero() -> None:
    result = rank_media_candidates(
        [_input(quality_score=80, aspect_ratio_band="editorial_landscape")]
    )[0]
    assert result.recommended_role == RecommendedRole.HERO


def test_high_branding_risk_image_is_never_hero_even_if_high_quality() -> None:
    result = rank_media_candidates(
        [_input(quality_score=90, aspect_ratio_band="editorial_landscape", possible_logo=True, possible_banner=True)]
    )[0]
    assert result.recommended_role == RecommendedRole.SUPPORTING
    assert result.branding_risk > 0
    assert result.eligible_for_delivery is True  # branding risk alone does not make it ineligible


def test_branding_risk_never_exceeds_100() -> None:
    result = rank_media_candidates(
        [_input(
            possible_logo=True, possible_banner=True, possible_watermark=True,
            possible_tv_lower_third=True, possible_branded_screenshot=True,
        )]
    )[0]
    assert result.branding_risk <= 100


def test_duplicate_within_event_lowers_rank_but_not_automatically_ineligible() -> None:
    unique = _input(quality_score=70)
    duplicate = _input(quality_score=70, is_duplicate_within_event=True)
    results = rank_media_candidates([duplicate, unique])
    assert results[0].media_item_id == unique.media_item_id
    dup_result = next(r for r in results if r.media_item_id == duplicate.media_item_id)
    assert dup_result.eligible_for_delivery is True


def test_missing_relevance_score_defaults_to_neutral() -> None:
    result = rank_media_candidates([_input(relevance_score=None)])[0]
    assert result.relevance_score == 50


def test_explicit_relevance_score_is_used() -> None:
    result = rank_media_candidates([_input(relevance_score=90)])[0]
    assert result.relevance_score == 90


def test_empty_input_returns_empty_result() -> None:
    assert rank_media_candidates([]) == []


def test_recommended_order_is_zero_indexed_and_contiguous() -> None:
    results = rank_media_candidates([_input() for _ in range(5)])
    assert [r.recommended_order for r in results] == [0, 1, 2, 3, 4]


# --- is_perceptually_reused ----------------------------------------------------------------------


def test_perceptually_identical_hash_is_reused() -> None:
    assert is_perceptually_reused("0000000000000000", ["0000000000000000"]) is True


def test_perceptually_close_hash_within_threshold_is_reused() -> None:
    # differs by exactly one bit
    assert is_perceptually_reused("0000000000000001", ["0000000000000000"]) is True


def test_perceptually_distant_hash_is_not_reused() -> None:
    assert is_perceptually_reused("ffffffffffffffff", ["0000000000000000"]) is False


def test_no_candidate_hash_is_never_reused() -> None:
    assert is_perceptually_reused(None, ["0000000000000000"]) is False


def test_empty_known_hashes_is_never_reused() -> None:
    assert is_perceptually_reused("0000000000000000", []) is False
