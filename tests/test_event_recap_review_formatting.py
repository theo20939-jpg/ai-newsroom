"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: bot.event_recap_review_formatting - pure
text rendering, no database, no aiogram Bot call. Mirrors the bounded-preview discipline tested
implicitly by tests/test_event_recap_review_notifier.py's own end-to-end message assertions, at
the pure-function level.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from bot.event_recap_review_formatting import (
    SAFE_LIMIT,
    EventRecapReviewTextTooLongError,
    render_event_recap_review_text,
)
from services.event_recap import FactVerificationResult
from tests.test_event_recap import _candidate_from_titles


def _synthesized_candidate(**overrides):
    candidate = _candidate_from_titles(
        ["Apple unveils new Watch Ultra priced at $999"], "Apple unveils new Watch Ultra",
    )
    defaults = dict(
        recap_title="Apple Watch Ultra Unveiled",
        recap_summary="Apple introduced a new Watch Ultra model.",
        key_takeaways=["Priced at $999."],
        uncertainty_notes=["Availability date not yet confirmed."],
        fact_verification=FactVerificationResult(
            status="pass", claims_checked=1, supported=1, uncertain=0, unsupported=0, flagged_claims=[],
        ),
    )
    defaults.update(overrides)
    return replace(candidate, **defaults)


def test_renders_title_summary_takeaways_and_uncertainty() -> None:
    candidate = _synthesized_candidate()
    text = render_event_recap_review_text(candidate)
    assert candidate.recap_title in text
    assert candidate.recap_summary in text
    assert "Priced at $999." in text
    assert "Availability date not yet confirmed." in text


@pytest.mark.parametrize(
    ("status", "expected_label"),
    [("pass", "пройдена"), ("review", "требует внимания"), ("block", "заблокировано"), ("not_run", "не выполнялась")],
)
def test_fact_verification_status_label(status: str, expected_label: str) -> None:
    candidate = _synthesized_candidate(
        fact_verification=FactVerificationResult(
            status=status, claims_checked=0, supported=0, uncertain=0, unsupported=0, flagged_claims=[],
        )
    )
    text = render_event_recap_review_text(candidate)
    assert expected_label in text


def test_shows_source_count_never_raw_urls() -> None:
    candidate = _synthesized_candidate()
    text = render_event_recap_review_text(candidate)
    for ref in candidate.source_refs:
        assert ref not in text
    if candidate.evidence_reference_count:
        assert str(candidate.evidence_reference_count) in text


def test_always_carries_the_shadow_review_only_disclaimer() -> None:
    text = render_event_recap_review_text(_synthesized_candidate())
    assert "shadow" in text.lower()
    assert "не публикуется" in text or "автоматически не публикуется" in text


def test_missing_title_and_summary_degrade_gracefully() -> None:
    candidate = _synthesized_candidate(recap_title=None, recap_summary=None)
    text = render_event_recap_review_text(candidate)
    assert "(без заголовка)" in text


def test_too_many_takeaways_are_capped_with_a_count() -> None:
    candidate = _synthesized_candidate(key_takeaways=[f"Point {i}" for i in range(20)])
    text = render_event_recap_review_text(candidate)
    assert "Point 0" in text
    assert "и ещё" in text


def test_rendered_text_never_exceeds_safe_limit() -> None:
    candidate = _synthesized_candidate(
        recap_summary="x" * 1000, key_takeaways=["y" * 500] * 20, uncertainty_notes=["z" * 500] * 20,
    )
    # This deliberately pathological input either stays bounded (per-item truncation/caps) or
    # raises the explicit backstop error - never silently produces an over-limit message.
    try:
        text = render_event_recap_review_text(candidate)
    except EventRecapReviewTextTooLongError:
        return
    assert len(text) <= SAFE_LIMIT
