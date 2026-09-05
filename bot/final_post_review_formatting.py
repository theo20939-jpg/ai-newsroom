"""Phase I.2: pure Final Post Preview rendering. No aiogram/Bot type appears anywhere in this
module - testable with zero Telegram mocking, mirrors bot/event_recap_review_formatting.py's own
"pure functions, no database access" discipline exactly.

Two, deliberately distinct render functions for the two-message contract (services/
final_post_review_notifier.py's own module docstring documents the full contract):

MESSAGE 1 (`render_final_post_preview_caption()`): the PUBLIC-LIKE artifact the editor is actually
reviewing - reuses `services.news_telegram_presentation.render_v81_news_card_html()` VERBATIM
(never a second, competing public-post formatter - Phase I.2's own explicit "Не делать
FinalPostPreview-specific public text formatter, если existing renderer подходит" instruction).
That function already produces exactly `<b>title</b>\\n\\nbody` with no internal/recap framing, no
category header, no NewsEvent title - byte-identical to what a real NEWS delivery using the V8.1
presentation profile would send today. This module contributes only the tiny adapter shape
(`ContentDraft.title`/`.body` -> `{"title": ..., "main_body": ...}`, the schema
`render_v81_news_card_html()` expects) and the shared UTF-16 length measurement
(`telegram_utf16_length()`) services/final_post_review_notifier.py uses to enforce Phase I.2's own
"NO SILENT TRUNCATION" rule (Part G) - this module itself never truncates or shrinks anything.

MESSAGE 2 (`render_final_post_review_control_text()`): a short, INTERNAL-only control message -
deliberately NOT built from the public renderer, and deliberately minimal (Phase I.2's own "editor
is reviewing the POST, not the pipeline" instruction) - no raw workflow JSON, no source bundle, no
token count, no cost, no internal IDs.
"""
from __future__ import annotations

from database.models.final_post_review import FinalPostReview, FinalPostReviewStatus
from services.news_telegram_presentation import render_v81_news_card_html

# Telegram's own hard limit for a photo caption, in UTF-16 code units - mirrors
# bot/image_preview_formatting.py::CAPTION_SAFE_LIMIT exactly (duplicated, not imported, per this
# codebase's own established "small, single-purpose constants are duplicated across independent
# presentation modules" convention - see services/news_telegram_presentation.py's own identical
# duplication of bot/formatting.py::SAFE_LIMIT for the same precedent).
CAPTION_SAFE_LIMIT = 1024


def telegram_utf16_length(text: str) -> int:
    """Duplicated from bot/formatting.py's own private `_telegram_utf16_length()` intentionally -
    the exact same one-line UTF-16 code-unit formula (Telegram's length limits are measured in
    UTF-16 code units, not Python's `len()`)."""
    return len(text.encode("utf-16-le")) // 2


def render_final_post_preview_caption(title: str, body: str) -> str:
    """MESSAGE 1's exact caption text - the complete, untruncated future public post. Never
    truncates, never shrinks: the caller (services/final_post_review_notifier.py) measures the
    result via `telegram_utf16_length()` against `CAPTION_SAFE_LIMIT` itself and returns
    `presentation_too_long` (sending nothing) rather than ever silently cutting this string - Phase
    I.2's own explicit "editor must never approve a truncated version of what publication would
    actually send" invariant. `include_ninja_pulse_footer=True` (PRESENTATION RECOVERY, 2026-09-02):
    this exact function is also the one real publication (services/final_post_publication.py) calls
    - the same canonical caption/footer contract worker/content_cycle.py's own NEWS send already
    uses, never a second, independent RECAP caption implementation."""
    return render_v81_news_card_html({"title": title, "main_body": body}, include_ninja_pulse_footer=True)


_PENDING_CONTROL_TEXT = "Финальный пост готов к проверке."
_STATUS_LINE_RU: dict[FinalPostReviewStatus, str] = {
    FinalPostReviewStatus.PENDING: _PENDING_CONTROL_TEXT,
    FinalPostReviewStatus.APPROVED_FOR_PUBLICATION: "✅ Пост одобрен к публикации",
    FinalPostReviewStatus.NEEDS_REVISION: "✏️ Пост требует доработки",
}


def render_final_post_review_control_text(
    review: FinalPostReview, *, authoring_prompt_version: str | None = None, fact_safety_status: str | None = None,
    source_event_recap_review_id: str | None = None,
) -> str:
    """MESSAGE 2's exact control text - called both for the initial PENDING send and for every
    later decision re-render, so it always reflects the CURRENT status, never a stale snapshot
    (mirrors render_event_recap_review_text()'s identical discipline). `authoring_prompt_version`/
    `fact_safety_status` are shown ONLY while `review.status == PENDING` (Phase I.2's own "minimal,
    only if genuinely useful to the deciding editor" instruction) - the terminal-state text
    (APPROVED_FOR_PUBLICATION/NEEDS_REVISION) is exactly the short line Phase I.2's own instructions
    specify, with no additional metadata.

    R2.10-FINALIZATION-2 `source_event_recap_review_id` (also PENDING-only, same "minimal, only if
    genuinely useful to the editor" instruction): the REAL RECAP distinction this pipeline's own
    product contract requires (see services/final_post_review_eligibility.py's own H/I gate, which
    already requires `final_post_source.source_event_recap_review_id` to exist and resolve to an
    APPROVED EventRecapReview for a recap-derived draft - never fabricated, always sourced from
    that same real, already-persisted field). Deliberately NOT added to `render_final_post_preview_
    caption()` (MESSAGE 1, the public-like preview / real publish payload) - that function's own
    docstring already documents the deliberate PRESENTATION RECOVERY decision that the PUBLIC post
    must stay byte-identical to an ordinary NEWS delivery, with no internal/recap framing bleeding
    into what a reader sees. The distinction belongs to the EDITOR doing the review, not the public
    post - so it lives here, in the internal-only control message, never touching MESSAGE 1's own
    WYSIWYG-critical caption."""
    if review.status != FinalPostReviewStatus.PENDING:
        return _STATUS_LINE_RU[review.status]

    lines = [_STATUS_LINE_RU[review.status]]
    if source_event_recap_review_id is not None:
        lines.append(f"📋 Источник: EVENT_RECAP-ревью {source_event_recap_review_id}")
    if authoring_prompt_version is not None or fact_safety_status is not None:
        lines.append("")
        meta_parts = []
        if authoring_prompt_version is not None:
            meta_parts.append(f"промпт v{authoring_prompt_version}")
        if fact_safety_status is not None:
            meta_parts.append(f"fact-safety: {fact_safety_status}")
        lines.append(" · ".join(meta_parts))
    return "\n".join(lines)
