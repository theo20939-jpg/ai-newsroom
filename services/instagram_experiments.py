"""INSTAGRAM GROWTH ENGINE v2, spec §46: Experiment system - upgrades
services/instagram_content_brain.py::ExperimentRecord (bare hypothesis/variant/control/objective)
into a real structured/lifecycle-aware record. No automatic production assignment (spec's own
explicit instruction) - `evaluate_experiment_readiness()` only ever reports whether enough sample
has accumulated, it never triggers anything."""
from __future__ import annotations

import enum
from dataclasses import dataclass
from datetime import datetime


class ExperimentDimension(str, enum.Enum):
    HOOK = "hook"
    FORMAT = "format"
    COVER = "cover"
    LENGTH = "length"
    CTA = "cta"
    SERIES = "series"
    TIMING = "timing"
    ANGLE = "angle"
    VISUAL_STYLE = "visual_style"


class ExperimentStatus(str, enum.Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETE = "complete"
    INCONCLUSIVE = "inconclusive"
    ADOPTED = "adopted"
    ABANDONED = "abandoned"


_TERMINAL_STATUSES = (
    ExperimentStatus.COMPLETE, ExperimentStatus.INCONCLUSIVE, ExperimentStatus.ADOPTED, ExperimentStatus.ABANDONED,
)


@dataclass(frozen=True)
class Experiment:
    hypothesis: str
    dimension: ExperimentDimension
    control: str
    variant: str
    objective: str
    sample_target: int
    start_at: datetime | None = None
    end_at: datetime | None = None
    status: ExperimentStatus = ExperimentStatus.PLANNED
    result: str | None = None
    confidence: float = 0.2

    def __post_init__(self) -> None:
        if self.sample_target <= 0:
            raise ValueError("sample_target must be positive - an experiment with no target sample size is not testable")
        if self.status in _TERMINAL_STATUSES and not self.result:
            raise ValueError(f"status={self.status.value} requires a recorded `result`")


def evaluate_experiment_readiness(experiment: Experiment, *, actual_sample_size: int) -> bool:
    """Never assigns production traffic - purely reports whether `sample_target` has been reached
    (spec §46's own "no automatic production assignment yet" instruction)."""
    return actual_sample_size >= experiment.sample_target
