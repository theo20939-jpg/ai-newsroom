"""INSTAGRAM GROWTH ENGINE v2, spec §46: Experiment system tests."""
from __future__ import annotations

import pytest

from services.instagram_experiments import (
    Experiment,
    ExperimentDimension,
    ExperimentStatus,
    evaluate_experiment_readiness,
)


def _experiment(**overrides: object) -> Experiment:
    defaults: dict[str, object] = dict(
        hypothesis="question hooks outperform statement hooks for comments",
        dimension=ExperimentDimension.HOOK, control="statement hook", variant="question hook",
        objective="comments", sample_target=20,
    )
    defaults.update(overrides)
    return Experiment(**defaults)  # type: ignore[arg-type]


def test_experiment_requires_positive_sample_target() -> None:
    with pytest.raises(ValueError):
        _experiment(sample_target=0)


def test_terminal_status_requires_result() -> None:
    with pytest.raises(ValueError):
        _experiment(status=ExperimentStatus.COMPLETE)
    experiment = _experiment(status=ExperimentStatus.COMPLETE, result="variant won")
    assert experiment.result == "variant won"


def test_readiness_reflects_sample_target_only() -> None:
    experiment = _experiment(sample_target=20)
    assert evaluate_experiment_readiness(experiment, actual_sample_size=10) is False
    assert evaluate_experiment_readiness(experiment, actual_sample_size=20) is True
