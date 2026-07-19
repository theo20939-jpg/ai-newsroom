"""Tests for services.triage. Pure unit tests - no DB, no network, no LLM."""
from datetime import datetime, timedelta, timezone

import pytest

from database.models.editorial_task import TaskPriority
from services.triage import TASK_PRIORITY_ORDINAL, decide_triage

UTC = timezone.utc
NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)


def _at(hours_ago: float) -> datetime:
    return NOW - timedelta(hours=hours_ago)


def test_fresh_and_reliable_event_gets_s_priority() -> None:
    result = decide_triage(_at(0.5), _at(0.5), 1.0, NOW)

    assert result.priority == TaskPriority.S
    assert result.explanation["priority"] == "S"


def test_reliability_score_present_is_reflected_in_combined_score() -> None:
    low = decide_triage(_at(3), _at(3), 0.0, NOW)
    high = decide_triage(_at(3), _at(3), 1.0, NOW)

    assert low.explanation["combined_score"] < high.explanation["combined_score"]
    assert low.explanation["reliability_score"] == 0.0
    assert high.explanation["reliability_score"] == 1.0


def test_published_at_none_falls_back_and_is_flagged_in_explanation() -> None:
    result = decide_triage(None, _at(3), 0.5, NOW)

    assert result.explanation["used_collected_at_fallback"] is True


def test_future_published_at_clamps_to_zero_no_raise() -> None:
    result = decide_triage(NOW + timedelta(hours=10), _at(1), 0.5, NOW)

    assert result.explanation["freshness_age_seconds"] == 0.0
    assert result.priority in TaskPriority


def test_naive_datetime_raises_value_error() -> None:
    naive = datetime(2026, 1, 1, 11, 0, 0)
    with pytest.raises(ValueError, match="timezone-aware"):
        decide_triage(naive, _at(1), 0.5, NOW)


def test_reliability_none_uses_default_and_still_returns_a_priority() -> None:
    result = decide_triage(_at(1), _at(1), None, NOW)

    assert result.explanation["used_reliability_default"] is True
    assert result.explanation["reliability_score"] == 0.5
    assert result.priority is not None


@pytest.mark.parametrize("reliability_score", [0.0, 1.0])
def test_reliability_score_boundaries(reliability_score: float) -> None:
    result = decide_triage(_at(1), _at(1), reliability_score, NOW)

    assert result.explanation["reliability_score"] == reliability_score
    assert result.priority in TaskPriority


def test_zero_age_boundary_is_deterministic() -> None:
    result = decide_triage(NOW, NOW, 0.5, NOW)

    assert result.explanation["freshness_age_seconds"] == 0.0
    assert result.priority == TaskPriority.S


@pytest.mark.parametrize(
    ("hours_ago", "reliability_score", "expected_priority"),
    [
        (0.5, 1.0, TaskPriority.S),
        (3.0, 0.5, TaskPriority.A),
        (15.0, 0.5, TaskPriority.B),
        (30.0, 0.5, TaskPriority.C),
        (60.0, 0.0, TaskPriority.C),
    ],
)
def test_every_reachable_priority_has_a_covering_case(
    hours_ago: float, reliability_score: float, expected_priority: TaskPriority
) -> None:
    result = decide_triage(_at(hours_ago), _at(hours_ago), reliability_score, NOW)

    assert result.priority == expected_priority


@pytest.mark.parametrize(
    ("published_at", "reliability_score"),
    [
        (None, None),
        (NOW - timedelta(hours=0), 0.0),
        (NOW - timedelta(hours=1), 1.0),
        (NOW - timedelta(hours=10), 0.5),
        (NOW - timedelta(hours=100), None),
        (NOW + timedelta(hours=5), 0.9),
    ],
)
def test_no_hard_drop_every_input_yields_a_valid_task_priority(
    published_at: datetime | None, reliability_score: float | None
) -> None:
    result = decide_triage(published_at, _at(1), reliability_score, NOW)

    assert result.priority in {TaskPriority.S, TaskPriority.A, TaskPriority.B, TaskPriority.C}


def test_ordinal_mapping_proves_canonical_business_order_via_the_dict_directly() -> None:
    assert (
        TASK_PRIORITY_ORDINAL[TaskPriority.S]
        > TASK_PRIORITY_ORDINAL[TaskPriority.A]
        > TASK_PRIORITY_ORDINAL[TaskPriority.B]
        > TASK_PRIORITY_ORDINAL[TaskPriority.C]
    )


def test_native_string_comparison_would_have_inverted_the_order_documented_negative() -> None:
    """Documents the exact hazard Contract §3 found, empirically, rather than merely
    avoiding it: TaskPriority's inherited str ordering is NOT the business order."""
    assert (TaskPriority.S < TaskPriority.A) is False
    assert sorted([TaskPriority.S, TaskPriority.A, TaskPriority.B, TaskPriority.C]) == [
        TaskPriority.A,
        TaskPriority.B,
        TaskPriority.C,
        TaskPriority.S,
    ]


def test_deterministic_repeated_calls_are_byte_identical() -> None:
    first = decide_triage(_at(5), _at(5), 0.7, NOW)
    second = decide_triage(_at(5), _at(5), 0.7, NOW)

    assert first == second
