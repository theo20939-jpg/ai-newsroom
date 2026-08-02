"""Phase 17 M4.1 - candidate generation output-budget policy and empty-output classification
(docs/phase17_m4_1_reasoning_budget_fix_report.md).

Fixes M4's own disclosed truncation defect (docs/phase17_m4_beginner_friendly_copywriting_report.md
§22): 7/32 candidates returned empty visible output because `reasoning_effort="medium"` let
internal reasoning tokens consume the entire `max_output_tokens` cap before any visible-answer
token could be written. Root-caused with certainty, not assumed: M3's own real 32-case run used
the identical `max_tokens` formula (`candidate_max_tokens()` below) with `reasoning_effort="low"`
and had zero truncations - the only variable M4 changed was `reasoning_effort` itself.

The OpenAI Responses API this project's Gateway calls
(`integrations/llm_gateway/providers/openai_adapter.py`) exposes exactly one output budget,
`max_output_tokens` - reasoning and visible-answer tokens are drawn from the SAME pool
(`usage.output_tokens_details.reasoning_tokens` is a subcategory of `output_tokens`, never a
separate counter, per `openai_adapter.py`'s own `_translate_response()`). There is no real
"reserve headroom for reasoning" lever this Gateway/provider contract supports - the only genuine
lever available is `reasoning_effort` itself. This module never claims a separate visible-output
budget exists when the API does not actually expose one.

Scoped only to the M4/M4.1 candidate-generation comparison/replay path
(`scripts/phase17_m4_1_failed_case_replay.py`) - production `CopywritingCapability`'s own
`reasoning_effort` ("low", `capabilities/executor.py`'s `_REASONING_EFFORT_BY_CAPABILITY`) is a
completely separate code path, never imported or touched by this module.
"""
from __future__ import annotations

from enum import Enum
from typing import Literal

CANDIDATE_GENERATION_POLICY_VERSION = "v1"

# Primary attempt: reverts M4's own "medium" back to M3's real, proven-safe value - zero
# truncations across M3's own 32-case real run using the identical max_tokens formula below. The
# minimal fix, not a redesign.
PRIMARY_REASONING_EFFORT: Literal["none", "low", "medium", "high"] = "low"

# Retry attempt (used at most once, only when the primary attempt itself still returns an empty
# visible output - see classify_empty_output()): a further-reduced fallback already proven to
# work in this project's own production traffic (capabilities/executor.py's own
# reasoning_effort="none" for the "research" capability) - not a speculative, untested value.
RETRY_REASONING_EFFORT: Literal["none", "low", "medium", "high"] = "none"

MAX_RETRIES = 1

# The fraction of output_tokens that must be reasoning_tokens for a length-truncated, empty
# response to be classified as specifically REASONING_BUDGET_EXHAUSTED rather than the more
# generic OUTPUT_CAP_REACHED - a conservative threshold, only applied when the provider actually
# reports reasoning_tokens (never inferred when that field is absent).
_REASONING_EXHAUSTION_THRESHOLD = 0.9


def candidate_max_tokens(safe_max_words: int) -> int:
    """Unchanged from M3's/M4's own formula (`scripts/phase17_m3_adaptive_length_comparison.py`,
    `scripts/phase17_m4_beginner_copywriting_comparison.py`) - no blind budget increase; M3's own
    real run already proved this cap is sufficient at `reasoning_effort="low"`."""
    return min(1200, round(safe_max_words * 4) + 150)


class EmptyOutputReason(str, Enum):
    """Every path `classify_empty_output()` can return - never a bare `None`/"unknown" without a
    named cause, and an empty-output candidate must never be silently counted as a normal
    result (M4.1's own explicit requirement)."""

    EMPTY_VISIBLE_OUTPUT = "empty_visible_output"
    REASONING_BUDGET_EXHAUSTED = "reasoning_budget_exhausted"
    OUTPUT_CAP_REACHED = "output_cap_reached"
    PARSE_EMPTY = "parse_empty"
    PROVIDER_EMPTY_RESPONSE = "provider_empty_response"
    UNKNOWN_EMPTY_OUTPUT = "unknown_empty_output"


def _is_blank(text: str | None) -> bool:
    return text is None or text.strip() == ""


def _candidate_fields_blank(structured_output: dict) -> bool:
    return _is_blank(structured_output.get("title")) or _is_blank(structured_output.get("body"))


def classify_empty_output(
    *,
    structured_output: dict | None,
    response_text: str | None,
    finish_reason: str,
    output_tokens: int | None,
    reasoning_tokens: int | None,
) -> EmptyOutputReason | None:
    """Pure. Returns `None` only when `structured_output` is a real, non-blank candidate (a
    non-empty dict with non-blank `title` and `body`) - every other path returns a specific,
    named `EmptyOutputReason`. Never raises: any unexpected input shape is classified
    `UNKNOWN_EMPTY_OUTPUT` rather than propagating an exception into the replay loop - a single
    malformed response must not abort the whole batch."""
    try:
        if isinstance(structured_output, dict) and structured_output:
            if not _candidate_fields_blank(structured_output):
                return None
            return EmptyOutputReason.EMPTY_VISIBLE_OUTPUT

        if _is_blank(response_text):
            if finish_reason == "length":
                if (
                    reasoning_tokens is not None
                    and output_tokens is not None
                    and output_tokens > 0
                    and reasoning_tokens >= output_tokens * _REASONING_EXHAUSTION_THRESHOLD
                ):
                    return EmptyOutputReason.REASONING_BUDGET_EXHAUSTED
                return EmptyOutputReason.OUTPUT_CAP_REACHED
            return EmptyOutputReason.PROVIDER_EMPTY_RESPONSE

        # Non-blank response_text but no valid structured_output: the model wrote something, but
        # it didn't parse as the requested JSON schema (openai_adapter.py's own
        # `_translate_response()` leaves `structured_output=None` on a JSONDecodeError).
        return EmptyOutputReason.PARSE_EMPTY
    except Exception:  # noqa: BLE001 - classification itself must never raise
        return EmptyOutputReason.UNKNOWN_EMPTY_OUTPUT
