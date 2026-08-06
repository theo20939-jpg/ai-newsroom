"""Quote Verification (Phase 18.10 M5): the anti-fabrication backstop for Copywriting's optional
`quote` field.

Pure, deterministic, no LLM call - reuses services/text_normalization.py::fuzzy_phrase_contains()
directly (zero new regex needed; that function already implements exactly "does this text appear
as a contiguous, normalized word sequence inside this other text", the precise anti-fabrication
check a quote claim needs). A claimed quote that is not found verbatim (case/quote/dash-
normalized, per fuzzy_phrase_contains()'s own established rules) in the source text fails
verification and MUST be dropped, never rendered - fail closed, never fabricated.

This is a distinct, narrower-purpose, pre-persistence gate from services/fact_safety.py's own
quote-claim checking (which flags an already-generated quote as a *review*/*block* finding after
the fact) - this module runs unconditionally, before a ContentDraftQuote row is ever created, and
its only two outcomes are "keep" or "drop", never "flag for review".
"""
from __future__ import annotations

from services.text_normalization import fuzzy_phrase_contains


def verify_quote(quote_text: str, source_content: str | None) -> bool:
    """True iff `quote_text` appears verbatim (fuzzy-normalized) inside `source_content`. False
    for a missing/empty source, an empty quote, or a quote not found in the source - fail closed
    in every ambiguous case, never "innocent until proven fake"."""
    if not quote_text or not quote_text.strip():
        return False
    if not source_content:
        return False
    return fuzzy_phrase_contains(quote_text, source_content)
