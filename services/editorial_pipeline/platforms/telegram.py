"""UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-1 (S19/S20/S24): the Telegram platform adapter.

S24 - "transport is dumb": `send_photo_to_editorial_destination()`/`send_to_editorial_destination()`
(services/telegram_routing.py, unchanged, reused) already return exactly `sent`/`reason` - they
never decide to send text instead, change format, drop an image, or replace media. This session's
own prior TELEGRAM-TEXT-ONLY-VISUAL-FALLBACK-REPAIR-1 phase already removed the one place that
DID violate this (the old `used_text_fallback` retry-as-text-on-send-failure mechanism, now a HOLD)
- this adapter's `send()` preserves that fix exactly (a failed real send becomes a `RecoveryJob`,
never a silent text re-send).

S19 - the actual new work this phase adds: `plan_telegram_caption_budget()` replaces the remaining
architectural rule that phase left deliberately untouched (out of its own scope) - "caption too long
-> silently drop image -> finished text-only post". The new, bounded sequence:

    1. does the FULL caption (structured content's own rendered text) fit? -> send as-is.
    2. does the caption MINUS the non-factual NINJA PULSE footer fit? -> send without the footer
       (a real, bounded, well-defined compression that touches zero factual content - never
       truncates a sentence, a number, a quote, or a claim).
    3. still too long -> HOLD (RecoveryReasonCode.CAPTION_BUDGET_FAILED), never send plain text
       with a dropped image, and never blindly truncate factual copy.

This policy is implemented HERE, in the new (currently flag-off, unreachable-in-production)
pipeline only - the currently-deployed `worker/content_cycle.py` keeps its own existing, disclosed,
Phase 23.1H/23.1Q caption-too-long-degrades-to-text behavior completely unchanged (S18's own
Telegram V8 freeze), until a future, Founder-approved phase flips `unified_editorial_pipeline_
enabled` on.
"""
from __future__ import annotations

from dataclasses import dataclass

from bot.image_preview_formatting import CAPTION_SAFE_LIMIT
from services.editorial_pipeline.contracts import RecoveryReasonCode
from services.news_telegram_presentation import build_ninja_pulse_footer_html


def _utf16_length(text: str) -> int:
    """Same formula as worker.content_cycle._telegram_utf16_length() (Telegram measures caption
    length in UTF-16 code units, not Python's len()) - duplicated intentionally rather than
    importing a private, underscore-prefixed helper from the legacy module, matching that
    function's own stated precedent for why it duplicates bot/formatting.py's version."""
    return len(text.encode("utf-16-le")) // 2


@dataclass(frozen=True)
class TelegramCaptionPlan:
    fits: bool
    caption: str | None
    """The final caption to send, or None when even the footer-stripped version does not fit."""
    footer_dropped: bool
    recovery_reason: RecoveryReasonCode | None


def plan_telegram_caption_budget(html: str, *, has_visual: bool) -> TelegramCaptionPlan:
    """`has_visual` gates whether this even needs to run the photo-caption-limit check at all - a
    text-only send (system/operator/explicit-text-only, S4-C's own carve-out) uses Telegram's much
    larger 4096-unit plain-message limit, not the 1024-unit photo-caption limit, and is not this
    function's concern (the orchestrator never calls this for that case)."""
    if not has_visual:
        return TelegramCaptionPlan(fits=True, caption=html, footer_dropped=False, recovery_reason=None)

    if _utf16_length(html) <= CAPTION_SAFE_LIMIT:
        return TelegramCaptionPlan(fits=True, caption=html, footer_dropped=False, recovery_reason=None)

    footer = build_ninja_pulse_footer_html()
    if html.rstrip().endswith(footer):
        without_footer = html.rstrip()[: -len(footer)].rstrip()
        if _utf16_length(without_footer) <= CAPTION_SAFE_LIMIT:
            return TelegramCaptionPlan(fits=True, caption=without_footer, footer_dropped=True, recovery_reason=None)

    return TelegramCaptionPlan(
        fits=False, caption=None, footer_dropped=False, recovery_reason=RecoveryReasonCode.CAPTION_BUDGET_FAILED,
    )
