"""INSTAGRAM GROWTH ENGINE v2, spec §26: Original Format Lab - a structured experiment record for
a genuinely new format idea. No autonomous publication anywhere (spec's own explicit instruction) -
`OriginalFormatExperiment` never carries a "publish now" action, only a testable hypothesis and its
lifecycle state."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field


class OriginalFormatStatus(str, enum.Enum):
    DRAFT = "draft"
    READY_TO_TEST = "ready_to_test"
    TESTING = "testing"
    PROMISING = "promising"
    FAILED = "failed"
    RETEST = "retest"
    ADOPTED = "adopted"


_TERMINAL_STATUSES = (OriginalFormatStatus.FAILED, OriginalFormatStatus.ADOPTED)


@dataclass(frozen=True)
class OriginalFormatExperiment:
    idea: str
    novelty_hypothesis: str
    intentional_difference: str
    target_objective: str
    target_audience: str
    format: str
    test_conditions: str
    success_criteria: str
    evaluation_window: str
    references: list[str] = field(default_factory=list)
    status: OriginalFormatStatus = OriginalFormatStatus.DRAFT
    result: str | None = None
    confidence: float = 0.2

    def __post_init__(self) -> None:
        if self.status in _TERMINAL_STATUSES and not self.result:
            raise ValueError(f"status={self.status.value} requires a `result` - a terminal status needs its outcome recorded")
