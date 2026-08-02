"""Phase 17 M4.1 - candidate generation output-budget policy tests (docs/
phase17_m4_1_reasoning_budget_fix_report.md).

Pure unit tests only - no DB, no LLM Gateway, no network. Mirrors M1-M4's own established "pure
function, pure test" tier.
"""
from services.candidate_generation_policy import (
    CANDIDATE_GENERATION_POLICY_VERSION,
    MAX_RETRIES,
    PRIMARY_REASONING_EFFORT,
    RETRY_REASONING_EFFORT,
    EmptyOutputReason,
    candidate_max_tokens,
    classify_empty_output,
)


def test_policy_version_is_v1() -> None:
    assert CANDIDATE_GENERATION_POLICY_VERSION == "v1"


def test_primary_reasoning_effort_is_low() -> None:
    """The minimal fix: reverts M4's own "medium" back to M3's proven-safe value - never a new,
    untested value."""
    assert PRIMARY_REASONING_EFFORT == "low"


def test_retry_reasoning_effort_is_none() -> None:
    """The retry fallback uses a value already proven in this project's own production traffic
    (capabilities/executor.py's "research" capability), not a speculative one."""
    assert RETRY_REASONING_EFFORT == "none"


def test_max_retries_is_one() -> None:
    assert MAX_RETRIES == 1


def test_candidate_max_tokens_matches_established_formula() -> None:
    """Identical to scripts/phase17_m3_adaptive_length_comparison.py's and
    scripts/phase17_m4_beginner_copywriting_comparison.py's own formula - no blind increase."""
    assert candidate_max_tokens(112) == min(1200, round(112 * 4) + 150)
    assert candidate_max_tokens(90) == 510
    assert candidate_max_tokens(112) == 598


def test_candidate_max_tokens_capped_at_1200() -> None:
    assert candidate_max_tokens(320) == 1200
    assert candidate_max_tokens(10_000) == 1200


def test_valid_output_accepted() -> None:
    result = classify_empty_output(
        structured_output={"title": "Real title", "body": "Real, non-blank body text.", "hashtags": ["#x"]},
        response_text='{"title": "Real title", "body": "Real, non-blank body text.", "hashtags": ["#x"]}',
        finish_reason="stop", output_tokens=200, reasoning_tokens=30,
    )
    assert result is None


def test_whitespace_only_title_rejected() -> None:
    result = classify_empty_output(
        structured_output={"title": "   ", "body": "Real body text.", "hashtags": []},
        response_text="irrelevant", finish_reason="stop", output_tokens=100, reasoning_tokens=10,
    )
    assert result is EmptyOutputReason.EMPTY_VISIBLE_OUTPUT


def test_empty_body_rejected() -> None:
    result = classify_empty_output(
        structured_output={"title": "A title", "body": "", "hashtags": []},
        response_text="irrelevant", finish_reason="stop", output_tokens=100, reasoning_tokens=10,
    )
    assert result is EmptyOutputReason.EMPTY_VISIBLE_OUTPUT


def test_empty_dict_structured_output_treated_as_no_output() -> None:
    """The real M4 shape: `response.structured_output or {}` produced `candidate={}` for all 7
    truncated cases - an empty dict must fall through to the blank-response classification, not
    be silently treated as "present but blank fields"."""
    result = classify_empty_output(
        structured_output={}, response_text=None, finish_reason="length",
        output_tokens=598, reasoning_tokens=580,
    )
    assert result is EmptyOutputReason.REASONING_BUDGET_EXHAUSTED


def test_parse_empty_detected_when_text_present_but_unparsed() -> None:
    result = classify_empty_output(
        structured_output=None, response_text="The model wrote something that was not valid JSON.",
        finish_reason="stop", output_tokens=150, reasoning_tokens=20,
    )
    assert result is EmptyOutputReason.PARSE_EMPTY


def test_output_cap_reached_when_length_and_no_reasoning_tokens() -> None:
    """finish_reason="length" with no reported reasoning_tokens (the field the real M4 script
    never saved) must not fabricate a reasoning-specific claim - falls back to the generic cap
    signal."""
    result = classify_empty_output(
        structured_output=None, response_text=None, finish_reason="length",
        output_tokens=598, reasoning_tokens=None,
    )
    assert result is EmptyOutputReason.OUTPUT_CAP_REACHED


def test_reasoning_budget_exhausted_when_ratio_high() -> None:
    result = classify_empty_output(
        structured_output=None, response_text="", finish_reason="length",
        output_tokens=600, reasoning_tokens=580,
    )
    assert result is EmptyOutputReason.REASONING_BUDGET_EXHAUSTED


def test_reasoning_budget_not_exhausted_when_ratio_low() -> None:
    """A length-truncated response where reasoning was only a small fraction of output_tokens is
    the generic cap signal, not the reasoning-specific one - the distinction must be evidence-
    based, not assumed."""
    result = classify_empty_output(
        structured_output=None, response_text=None, finish_reason="length",
        output_tokens=600, reasoning_tokens=50,
    )
    assert result is EmptyOutputReason.OUTPUT_CAP_REACHED


def test_provider_empty_response_when_stop_finish_and_blank() -> None:
    result = classify_empty_output(
        structured_output=None, response_text=None, finish_reason="stop",
        output_tokens=0, reasoning_tokens=None,
    )
    assert result is EmptyOutputReason.PROVIDER_EMPTY_RESPONSE


def test_unknown_empty_output_on_malformed_input() -> None:
    """classify_empty_output() must never raise - a malformed input shape (here, a non-string
    response_text) is caught and classified UNKNOWN_EMPTY_OUTPUT rather than propagating an
    exception into the replay loop."""
    result = classify_empty_output(
        structured_output=None, response_text=12345,  # type: ignore[arg-type]
        finish_reason="stop", output_tokens=10, reasoning_tokens=None,
    )
    assert result is EmptyOutputReason.UNKNOWN_EMPTY_OUTPUT
