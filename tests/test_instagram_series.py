"""INSTAGRAM GROWTH ENGINE v2, spec §68: Series/franchise lifecycle tests."""
from __future__ import annotations

from services.instagram_content_brain import EvidenceStage
from services.instagram_series import ContentSeries, SeriesStatus, evaluate_series_promotion, is_recommendable_as_active


def _series(**overrides: object) -> ContentSeries:
    defaults: dict[str, object] = dict(id="s1", name="Myth Monday", description="d", objective="saves")
    defaults.update(overrides)
    return ContentSeries(**defaults)  # type: ignore[arg-type]


def test_new_series_starts_as_hypothesis() -> None:
    series = _series()
    assert series.status == SeriesStatus.SERIES_HYPOTHESIS


def test_single_winner_cannot_become_active() -> None:
    series = _series(episode_count=1)
    status = evaluate_series_promotion(series, evidence_stage=EvidenceStage.STABLE_WORKING_RULE)
    assert status == SeriesStatus.SERIES_HYPOTHESIS


def test_repeated_evidence_may_promote_to_active() -> None:
    series = _series(episode_count=5, status=SeriesStatus.SERIES_TESTING)
    status = evaluate_series_promotion(series, evidence_stage=EvidenceStage.REPEATED_PATTERN)
    assert status == SeriesStatus.SERIES_ACTIVE


def test_weak_evidence_with_enough_episodes_stays_testing() -> None:
    series = _series(episode_count=3, status=SeriesStatus.SERIES_TESTING)
    status = evaluate_series_promotion(series, evidence_stage=EvidenceStage.POSSIBLE_SIGNAL)
    assert status == SeriesStatus.SERIES_TESTING


def test_active_series_can_become_fatigued() -> None:
    series = _series(episode_count=10, status=SeriesStatus.SERIES_ACTIVE)
    status = evaluate_series_promotion(series, evidence_stage=EvidenceStage.STABLE_WORKING_RULE, is_fatigued=True)
    assert status == SeriesStatus.SERIES_FATIGUED


def test_retired_series_stays_retired() -> None:
    series = _series(episode_count=20, status=SeriesStatus.SERIES_RETIRED)
    status = evaluate_series_promotion(series, evidence_stage=EvidenceStage.STABLE_WORKING_RULE)
    assert status == SeriesStatus.SERIES_RETIRED


def test_retired_series_not_recommended_as_active_by_default() -> None:
    assert is_recommendable_as_active(_series(status=SeriesStatus.SERIES_RETIRED)) is False
    assert is_recommendable_as_active(_series(status=SeriesStatus.SERIES_ACTIVE)) is True
