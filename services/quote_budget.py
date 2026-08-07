"""Phase 19 M5: pure UTF-16 budget arithmetic for whether a verified quote can be rendered in
full alongside a Telegram card (docs/phase19_m0_audit.md).

A verified quote is either rendered whole, or omitted entirely - never partially truncated. This
module is the tested guarantee behind that property; bot/formatting.py owns the actual
HTML-escaping/measurement (reusing its own established `_telegram_utf16_length()` - never a
second, divergent length calculation) and calls into this module's pure decision functions.
"""
from __future__ import annotations


def fits_within_budget(*, non_quote_blocks_length: int, quote_block_length: int, limit: int) -> bool:
    """True when header+title+quote+ (body reduced to its minimum, empty) would still fit within
    `limit` - the tightest feasible shape the truncation-squeeze loop could ever reach.
    `non_quote_blocks_length` must already reflect that minimum-body measurement - the caller is
    responsible for measuring it."""
    return non_quote_blocks_length + quote_block_length <= limit


def select_quote_or_omit(
    quote_text: str | None, quote_speaker: str | None, *, fits: bool
) -> tuple[str | None, str | None]:
    """Pure decision: the quote is included whole, or omitted entirely - never partial, never
    dependent on how much of it "would" fit."""
    if quote_text is None:
        return None, None
    if not fits:
        return None, None
    return quote_text, quote_speaker
