"""INSTAGRAM GROWTH ENGINE v2, spec §24/§25: ContentSeries/franchise lifecycle - a series never
becomes SERIES_ACTIVE off one winning post (spec §25's own explicit "one successful post != a
permanent franchise" instruction). Promotion reuses services/instagram_content_brain.py's own
EvidenceStage anti-overfit gate rather than a series-specific threshold, so a series and any other
performance claim in this codebase are held to the identical evidentiary bar."""
from __future__ import annotations

import enum
from dataclasses import dataclass, field
from datetime import datetime, timezone

from services.instagram_content_brain import EvidenceStage


class SeriesStatus(str, enum.Enum):
    SERIES_HYPOTHESIS = "series_hypothesis"
    SERIES_TESTING = "series_testing"
    SERIES_ACTIVE = "series_active"
    SERIES_FATIGUED = "series_fatigued"
    SERIES_RETIRED = "series_retired"


@dataclass(frozen=True)
class ContentSeries:
    id: str
    name: str
    description: str
    objective: str
    preferred_formats: list[str] = field(default_factory=list)
    topic_scope: str = ""
    target_audience: str = ""
    cadence: str = ""
    status: SeriesStatus = SeriesStatus.SERIES_HYPOTHESIS
    episode_count: int = 0
    performance_summary: str = ""
    fatigue: str = "fresh"
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


_MIN_EPISODES_FOR_TESTING = 2
_EVIDENCE_STAGES_ALLOWING_ACTIVE = (EvidenceStage.REPEATED_PATTERN, EvidenceStage.STABLE_WORKING_RULE)


def evaluate_series_promotion(
    series: ContentSeries, *, evidence_stage: EvidenceStage, is_fatigued: bool = False,
) -> SeriesStatus:
    """Spec §25: a single episode/winner (episode_count<2, or evidence_stage still ANOMALY/
    POSSIBLE_SIGNAL) can NEVER resolve to SERIES_ACTIVE, regardless of how strong that one result
    looked. A retired series is never silently reactivated by this function - a caller must build
    a fresh ContentSeries (or a deliberate un-retire decision outside this evidence-driven path)."""
    if series.status == SeriesStatus.SERIES_RETIRED:
        return SeriesStatus.SERIES_RETIRED
    if is_fatigued and series.status == SeriesStatus.SERIES_ACTIVE:
        return SeriesStatus.SERIES_FATIGUED
    if series.episode_count < _MIN_EPISODES_FOR_TESTING:
        return SeriesStatus.SERIES_HYPOTHESIS
    if evidence_stage in _EVIDENCE_STAGES_ALLOWING_ACTIVE:
        return SeriesStatus.SERIES_ACTIVE
    return SeriesStatus.SERIES_TESTING


def is_recommendable_as_active(series: ContentSeries) -> bool:
    """Spec §68's own required test: "retired series not recommended as active by default"."""
    return series.status in (SeriesStatus.SERIES_TESTING, SeriesStatus.SERIES_ACTIVE)
