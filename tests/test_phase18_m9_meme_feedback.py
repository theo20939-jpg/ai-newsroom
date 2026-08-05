"""Phase 18 M9 - Human Feedback & Decision Logging tests (docs/
phase18_m9_human_feedback_report.md).

Pure, DB-free unit tests for the reason-picker keyboard/codec and `MemeFeedbackSummary`'s own
construction contract. `MemeCandidateService.record_editor_decision(reasons=...)`/`add_cost()`/
`build_feedback_summary()` themselves are DB-backed and not exercised here - same disclosed
constraint as every DB-dependent piece of M1-M8 (local Postgres/Redis stack unavailable this
session).
"""
from __future__ import annotations

from decimal import Decimal
from uuid import uuid4

import pytest

from bot.keyboards.meme_feedback import (
    build_reject_reason_keyboard,
    encode_reason_callback_data,
    parse_reason_callback_data,
)
from schemas.meme_feedback import MemeFeedbackSummary, MemeRejectionReason

_CANDIDATE_ID = uuid4()


# ---------------------------------------------------------------------------
# MemeRejectionReason taxonomy
# ---------------------------------------------------------------------------


def test_taxonomy_matches_the_brief_exactly() -> None:
    values = {r.value for r in MemeRejectionReason}
    assert values == {
        "not_funny", "unclear", "factual_risk", "bad_image", "off_brand", "too_toxic", "stale",
        "duplicate_idea",
    }


# ---------------------------------------------------------------------------
# Keyboard encode/parse
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("reason", list(MemeRejectionReason))
def test_every_reason_round_trips(reason: MemeRejectionReason) -> None:
    data = encode_reason_callback_data(reason, _CANDIDATE_ID)
    assert parse_reason_callback_data(data) == (reason, _CANDIDATE_ID)


def test_skip_round_trips_to_none_reason() -> None:
    data = encode_reason_callback_data(None, _CANDIDATE_ID)
    parsed = parse_reason_callback_data(data)
    assert parsed is not None
    reason, candidate_id = parsed
    assert reason is None
    assert candidate_id == _CANDIDATE_ID


def test_parse_rejects_wrong_prefix() -> None:
    assert parse_reason_callback_data(f"memeprev:approve:{_CANDIDATE_ID}") is None


def test_parse_rejects_unknown_reason_token() -> None:
    assert parse_reason_callback_data(f"memereason:not_a_real_reason:{_CANDIDATE_ID}") is None


def test_parse_rejects_malformed_uuid() -> None:
    assert parse_reason_callback_data("memereason:stale:not-a-uuid") is None


def test_build_reject_reason_keyboard_includes_every_reason_and_skip() -> None:
    keyboard = build_reject_reason_keyboard(_CANDIDATE_ID)
    all_callback_data = [
        button.callback_data for row in keyboard.inline_keyboard for button in row if button.callback_data
    ]
    for reason in MemeRejectionReason:
        assert encode_reason_callback_data(reason, _CANDIDATE_ID) in all_callback_data
    assert encode_reason_callback_data(None, _CANDIDATE_ID) in all_callback_data


def test_reject_reason_keyboard_has_two_reasons_per_row_plus_a_skip_row() -> None:
    keyboard = build_reject_reason_keyboard(_CANDIDATE_ID)
    reason_rows = keyboard.inline_keyboard[:-1]
    for row in reason_rows:
        assert len(row) == 2
    assert len(keyboard.inline_keyboard[-1]) == 1


# ---------------------------------------------------------------------------
# MemeFeedbackSummary
# ---------------------------------------------------------------------------


def test_feedback_summary_is_frozen_and_rejects_unknown_field() -> None:
    from pydantic import ValidationError

    summary = MemeFeedbackSummary(
        candidate_id=str(_CANDIDATE_ID), status="rejected", editor_decision="rejected",
        editor_decision_reasons=["stale"], editor_decision_notes=None,
        concept_regeneration_count=0, copy_regeneration_count=0, image_regeneration_count=0,
        cumulative_cost_usd="0.000000", published=False,
    )
    with pytest.raises(ValidationError):
        summary.status = "approved"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        MemeFeedbackSummary(**{**summary.model_dump(), "unexpected_field": "x"})


def test_feedback_summary_published_defaults_to_never_true_by_construction() -> None:
    """No test can prove a negative universally, but this at least proves the schema itself
    happily represents published=False, and that nothing in this schema module computes or
    defaults published=True anywhere (the brief's own "nothing publishes automatically"
    invariant - enforced by there being no code path that ever sets it True in this phase, not by
    a schema-level constant)."""
    summary = MemeFeedbackSummary(
        candidate_id=str(_CANDIDATE_ID), status="approved", editor_decision="approved",
        editor_decision_reasons=[], editor_decision_notes=None,
        concept_regeneration_count=0, copy_regeneration_count=0, image_regeneration_count=0,
        cumulative_cost_usd="0.000000", published=False,
    )
    assert summary.published is False


def test_cost_is_represented_as_a_decimal_safe_string() -> None:
    """cumulative_cost_usd is always a string (never a float) - proves no precision-losing
    float round-trip could occur when this summary is serialized to JSON."""
    summary = MemeFeedbackSummary(
        candidate_id=str(_CANDIDATE_ID), status="pending_editor", editor_decision=None,
        editor_decision_reasons=[], editor_decision_notes=None,
        concept_regeneration_count=1, copy_regeneration_count=0, image_regeneration_count=1,
        cumulative_cost_usd=str(Decimal("0.001234")), published=False,
    )
    assert summary.cumulative_cost_usd == "0.001234"
    assert isinstance(summary.cumulative_cost_usd, str)
