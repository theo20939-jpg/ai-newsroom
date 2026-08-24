"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: bot.event_recap_review_formatting - pure
text rendering, no database, no aiogram Bot call.

Phase D.0 change from Phase C.1: renders from an `EventRecapReview` (for status) plus the recap's
own persisted result dict, never a live `EventRecapCandidate` - see bot/event_recap_review_
formatting.py's own module docstring for why.
"""
from __future__ import annotations

from uuid import uuid4

import pytest

from bot.event_recap_review_formatting import (
    SAFE_LIMIT,
    EventRecapReviewTextTooLongError,
    render_event_recap_review_text,
)
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus


def _review(status: EventRecapReviewStatus = EventRecapReviewStatus.PENDING) -> EventRecapReview:
    return EventRecapReview(id=uuid4(), recap_task_id=uuid4(), status=status)


def _recap_result(**overrides: object) -> dict:
    defaults = dict(
        recap_title="Apple Watch Ultra Unveiled",
        recap_summary="Apple introduced a new Watch Ultra model.",
        key_takeaways=["Priced at $999."],
        uncertainty_notes=["Availability date not yet confirmed."],
    )
    defaults.update(overrides)
    return defaults


def test_renders_title_summary_takeaways_and_uncertainty() -> None:
    result = _recap_result()
    text = render_event_recap_review_text(_review(), result)
    assert result["recap_title"] in text
    assert result["recap_summary"] in text
    assert "Priced at $999." in text
    assert "Availability date not yet confirmed." in text


@pytest.mark.parametrize(
    ("status", "expected_marker"),
    [
        (EventRecapReviewStatus.PENDING, "⏳ Решение не принято"),
        (EventRecapReviewStatus.APPROVED, "✅ Recap одобрен"),
        (EventRecapReviewStatus.NEEDS_REVISION, "✏️ Требуется доработка"),
    ],
)
def test_status_line(status: EventRecapReviewStatus, expected_marker: str) -> None:
    text = render_event_recap_review_text(_review(status), _recap_result())
    assert expected_marker in text


def test_always_carries_the_shadow_review_only_disclaimer() -> None:
    text = render_event_recap_review_text(_review(), _recap_result())
    assert "shadow" in text.lower()
    assert "не публикуется" in text or "автоматически не публикуется" in text


def test_missing_title_and_summary_degrade_gracefully() -> None:
    result = _recap_result(recap_title=None, recap_summary=None)
    text = render_event_recap_review_text(_review(), result)
    assert "(без заголовка)" in text


def test_too_many_takeaways_are_capped_with_a_count() -> None:
    result = _recap_result(key_takeaways=[f"Point {i}" for i in range(20)])
    text = render_event_recap_review_text(_review(), result)
    assert "Point 0" in text
    assert "и ещё" in text


def test_rendered_text_never_exceeds_safe_limit() -> None:
    result = _recap_result(
        recap_summary="x" * 1000, key_takeaways=["y" * 500] * 20, uncertainty_notes=["z" * 500] * 20,
    )
    # This deliberately pathological input either stays bounded (per-item truncation/caps) or
    # raises the explicit backstop error - never silently produces an over-limit message.
    try:
        text = render_event_recap_review_text(_review(), result)
    except EventRecapReviewTextTooLongError:
        return
    assert len(text) <= SAFE_LIMIT


def test_never_references_candidate_fact_verification_fields() -> None:
    """The persisted result dict has no fact_verification/evidence_reference_count fields at all
    (those are EventRecapCandidate-only) - a caller accidentally passing them through must not
    make them appear in the rendered text either."""
    result = _recap_result(fact_verification="pass", evidence_reference_count=5)
    text = render_event_recap_review_text(_review(), result)
    assert "fact_verification" not in text.lower()
    assert "Проверка фактов" not in text
