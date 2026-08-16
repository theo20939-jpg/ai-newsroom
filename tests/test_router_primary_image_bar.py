"""2026-08-16 production forensic (Telegram NEWS image quality): the router-mode primary image
bar. Pure unit tests only - `worker.content_cycle._select_top_ranked_image_candidates()` and its
new `_meets_primary_image_bar()` helper are both pure/synchronous (no DB, no async, no network) -
`services.media_ranking.rank_media_candidates()` underneath is documented as "Pure. Deterministic"
and this module's own selection layer adds nothing stateful on top of it.

Root cause this covers: the strict quality bar (`_meets_additional_album_image_bar()`) was only
ever applied to SECOND/THIRD album images - `selected = [eligible[0][1]]` took the single
best-ranked candidate unconditionally, so a WEAK or possible_logo image could become the one
photo actually sent to Telegram. Confirmed real production rank=1 candidates: 124x83 WEAK
(quality=65), a 328x328 Techmeme logo (possible_logo=True, possible_branded_screenshot=True,
quality=51). This file proves the new primary bar (ADEQUATE/GOOD resolution, known dimensions,
not possible_logo) now gates the primary slot too, while the existing album bar - and duplicate
filtering, and ranked ordering - stay byte-identical.

Reuses tests.test_router_media_integration._fake_candidate() (this repo's own established
cross-file fixture-reuse convention, documented in that file's own module docstring), never
duplicated.
"""
from services.image_persistence import EditorialImageCandidate
from tests.test_router_media_integration import _fake_candidate
from worker.content_cycle import _meets_primary_image_bar, _select_top_ranked_image_candidates

_LIMIT = 3


def _ids(candidates: list[EditorialImageCandidate]) -> list[str]:
    return [c.candidate_id for c in candidates]


# ---------------------------------------------------------------------------
# Requirements 1-7: primary bar pass/fail, single candidate
# ---------------------------------------------------------------------------


def test_good_primary_passes() -> None:
    candidate = _fake_candidate(candidate_id="good", width=1600, height=899, quality_score=90)
    assert _meets_primary_image_bar(candidate) is True
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["good"]


def test_adequate_primary_passes() -> None:
    candidate = _fake_candidate(candidate_id="adequate", width=610, height=343, quality_score=80)
    assert _meets_primary_image_bar(candidate) is True
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["adequate"]


def test_weak_primary_excluded() -> None:
    candidate = _fake_candidate(candidate_id="weak", width=124, height=83, quality_score=65)
    assert _meets_primary_image_bar(candidate) is False
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_icon_primary_excluded() -> None:
    candidate = _fake_candidate(candidate_id="icon", width=60, height=60, quality_score=80)
    assert _meets_primary_image_bar(candidate) is False
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_tracking_primary_excluded() -> None:
    candidate = _fake_candidate(candidate_id="tracking", width=1, height=1, quality_score=80)
    assert _meets_primary_image_bar(candidate) is False
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_unknown_dimensions_primary_excluded() -> None:
    candidate = _fake_candidate(candidate_id="unknown-dims", width=None, height=None, quality_score=80)
    assert _meets_primary_image_bar(candidate) is False
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_possible_logo_primary_excluded() -> None:
    candidate = _fake_candidate(
        candidate_id="logo", width=328, height=328, quality_score=51, warnings=["possible_logo"],
    )
    assert _meets_primary_image_bar(candidate) is False
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


# ---------------------------------------------------------------------------
# Requirements 8-9: the selector falls through to the next ranked candidate
# ---------------------------------------------------------------------------


def test_rank1_weak_rank2_good_promotes_rank2_to_primary() -> None:
    """The task's own worked example: rank1 = 124x83 WEAK, rank2 = 1200x800 GOOD -> rank2 becomes
    primary. Composite scores are set so the WEAK candidate genuinely outranks the GOOD one before
    the primary-bar filter runs (quality/relevance high enough to beat the GOOD candidate's own
    composite), proving the fallthrough is a real re-ranking step, not just "the only candidate
    left."""
    weak_but_top_ranked = _fake_candidate(
        candidate_id="rank1-weak", width=124, height=83, quality_score=95, relevance_score=95,
    )
    good_candidate = _fake_candidate(
        candidate_id="rank2-good", width=1200, height=800, quality_score=70, relevance_score=70,
    )
    selected = _select_top_ranked_image_candidates([weak_but_top_ranked, good_candidate], limit=_LIMIT)
    assert _ids(selected) == ["rank2-good"]


def test_rank1_logo_rank2_adequate_clean_promotes_rank2_to_primary() -> None:
    """rank1 possible_logo (even a genuinely high-resolution one) + rank2 ADEQUATE clean -> rank2
    becomes primary. The logo candidate also fails the (unchanged) album bar on branding_risk, so
    it does not survive into an album slot either - it is fully excluded, not merely demoted."""
    logo_but_top_ranked = _fake_candidate(
        candidate_id="rank1-logo", width=328, height=328, quality_score=95, relevance_score=95,
        warnings=["possible_logo"],
    )
    adequate_clean = _fake_candidate(
        candidate_id="rank2-adequate", width=610, height=343, quality_score=70, relevance_score=70,
    )
    selected = _select_top_ranked_image_candidates([logo_but_top_ranked, adequate_clean], limit=_LIMIT)
    assert _ids(selected) == ["rank2-adequate"]


def test_all_candidates_fail_primary_bar_returns_empty() -> None:
    """No candidate clears the primary bar -> [] -> the router's existing text-only fallback
    remains possible. A known-bad image must never be sent merely to avoid a text-only post."""
    weak = _fake_candidate(candidate_id="weak", width=124, height=83, quality_score=65)
    unknown_dims = _fake_candidate(candidate_id="unknown-dims", width=None, height=None, quality_score=80)
    selected = _select_top_ranked_image_candidates([weak, unknown_dims], limit=_LIMIT)
    assert selected == []


# ---------------------------------------------------------------------------
# Requirements 11-12: branded_screenshot/tv_lower_third alone must NOT hard-fail the primary
# ---------------------------------------------------------------------------


def test_branded_screenshot_alone_does_not_reject_a_high_resolution_primary() -> None:
    candidate = _fake_candidate(
        candidate_id="branded", width=1600, height=899, quality_score=85,
        warnings=["possible_branded_screenshot"],
    )
    assert _meets_primary_image_bar(candidate) is True
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["branded"]


def test_tv_lower_third_alone_does_not_reject_a_high_resolution_primary() -> None:
    candidate = _fake_candidate(
        candidate_id="lower-third", width=1600, height=899, quality_score=85,
        warnings=["possible_tv_lower_third"],
    )
    assert _meets_primary_image_bar(candidate) is True
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["lower-third"]


def test_real_engadget_shape_branded_screenshot_and_tv_lower_third_together_still_passes() -> None:
    """The real, named production example: a 1600x899 Engadget image flagged BOTH
    possible_branded_screenshot and possible_tv_lower_third - neither is possible_logo, so neither
    is a hard primary-image failure this checkpoint, per the phase brief's own explicit
    instruction not to hard-reject every branding_risk > 0 candidate."""
    candidate = _fake_candidate(
        candidate_id="engadget", width=1600, height=899, quality_score=80,
        warnings=["possible_branded_screenshot", "possible_tv_lower_third"],
    )
    assert _meets_primary_image_bar(candidate) is True
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["engadget"]


# ---------------------------------------------------------------------------
# Requirement 13: SECOND/THIRD images still use the pre-existing, unchanged album bar
# ---------------------------------------------------------------------------


def test_album_bar_still_rejects_branding_risk_for_non_primary_slots() -> None:
    """A candidate carrying only possible_watermark would NOT fail the primary bar (watermark is
    not possible_logo) - but the pre-existing, unchanged album bar still requires branding_risk
    == 0, so it must still be rejected for a SECOND/THIRD slot, proving the two bars remain
    genuinely different in strictness, not merged into one."""
    primary = _fake_candidate(
        candidate_id="primary", width=1600, height=899, quality_score=95, relevance_score=95,
    )
    clean_second = _fake_candidate(
        candidate_id="clean-second", width=800, height=450, quality_score=80, relevance_score=80,
    )
    watermarked_third = _fake_candidate(
        candidate_id="watermarked-third", width=700, height=400, quality_score=75, relevance_score=75,
        warnings=["possible_watermark"],
    )
    selected = _select_top_ranked_image_candidates(
        [primary, clean_second, watermarked_third], limit=_LIMIT,
    )
    assert _ids(selected) == ["primary", "clean-second"]


# ---------------------------------------------------------------------------
# Requirement 14: duplicate filtering remains unchanged
# ---------------------------------------------------------------------------


def test_duplicate_filtering_unchanged_exact_sha256_match_excluded() -> None:
    first = _fake_candidate(
        candidate_id="first", width=1600, height=899, quality_score=90, sha256="same-hash",
    )
    duplicate = _fake_candidate(
        candidate_id="duplicate", width=1600, height=899, quality_score=90, sha256="same-hash",
    )
    selected = _select_top_ranked_image_candidates([first, duplicate], limit=_LIMIT)
    assert _ids(selected) == ["first"]


# ---------------------------------------------------------------------------
# Requirement 15: ordering remains deterministic
# ---------------------------------------------------------------------------


def test_selection_is_deterministic_across_repeated_calls() -> None:
    candidates = [
        _fake_candidate(candidate_id="a", width=1600, height=899, quality_score=90, relevance_score=90),
        _fake_candidate(candidate_id="b", width=800, height=450, quality_score=80, relevance_score=80),
        _fake_candidate(candidate_id="c", width=610, height=343, quality_score=70, relevance_score=70),
    ]
    first_call = _select_top_ranked_image_candidates(candidates, limit=_LIMIT)
    second_call = _select_top_ranked_image_candidates(candidates, limit=_LIMIT)
    assert _ids(first_call) == _ids(second_call)
    assert _ids(first_call) == ["a", "b", "c"]


# ---------------------------------------------------------------------------
# Real production-shaped regression examples (verbatim dimensions/quality from the forensic)
# ---------------------------------------------------------------------------


def test_regression_124x83_quality65_excluded() -> None:
    candidate = _fake_candidate(candidate_id="prod-weak", width=124, height=83, quality_score=65)
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_regression_328x328_possible_logo_excluded() -> None:
    candidate = _fake_candidate(
        candidate_id="prod-logo", width=328, height=328, quality_score=51,
        warnings=["possible_logo", "possible_branded_screenshot"],
    )
    assert _select_top_ranked_image_candidates([candidate], limit=_LIMIT) == []


def test_regression_610x343_clean_accepted() -> None:
    candidate = _fake_candidate(candidate_id="prod-adequate", width=610, height=343, quality_score=75)
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["prod-adequate"]


def test_regression_1200x800_clean_accepted() -> None:
    candidate = _fake_candidate(candidate_id="prod-good", width=1200, height=800, quality_score=85)
    assert _ids(_select_top_ranked_image_candidates([candidate], limit=_LIMIT)) == ["prod-good"]
