"""NINJA PULSE RECAP Phase R2 integration, Phase D.0: pure EVENT_RECAP review-preview rendering.
Mirrors bot/telegraph_article_review_formatting.py's own "pure functions, no aiogram/Bot type
anywhere in this module, no database access" discipline exactly - testable with zero Telegram
mocking, zero DB access.

Operator-facing text is Russian throughout, matching every other TELEGRAPH review surface's own
established convention.

Phase D.0 change from Phase C.1: renders from the durable `EventRecapReview` row (for the current
decision status) plus the recap's own persisted result dict (`recap_title`/`recap_summary`/
`key_takeaways`/`uncertainty_notes` - the exact `EditorialTask.workflow["step_results"]` shape
`EventRecapCapability.execute()` already produces), never a live `services.event_recap.
EventRecapCandidate` object - mirrors `render_article_review_text(review, article_result: dict,
...)`'s own identical shape exactly. This is what lets the SAME function render both the initial
send and every later decision re-render from the SAME source of truth (the persisted task result),
so the message can never regress or go stale between the two (`fact_verification`/
`evidence_reference_count` are `EventRecapCandidate`-only fields, never part of the persisted
result dict - they are therefore not shown here, exactly like Telegraph's own quality-gate/
fact-safety signals are never shown in its review text either).

Never renders raw source URLs/external links in the message text - mirrors
render_article_review_text()'s own identical "источников: N, никогда сырых ссылок" precedent for
this exact same internal-review-message class (moot here, since the result dict carries no source
URLs at all, only the four fields above).
"""
from database.models.event_recap_review import EventRecapReview, EventRecapReviewStatus

# Same constant bot/telegraph_article_review_formatting.py::SAFE_LIMIT already established -
# Telegram's own hard limit for a plain text message.
SAFE_LIMIT = 4096

# How much of the recap's own key_takeaways/uncertainty_notes this preview shows - a reasoned
# starting bound (Phase C.1's own first calibration, carried forward unchanged), mirrors
# _MAX_PREVIEW_FACTS's identical role in the TELEGRAPH review formatter.
_MAX_PREVIEW_ITEMS = 8
_MAX_ITEM_CHARS = 300

_STATUS_LINE_RU: dict[EventRecapReviewStatus, str] = {
    EventRecapReviewStatus.PENDING: "⏳ Решение не принято",
    EventRecapReviewStatus.APPROVED: "✅ Recap одобрен",
    EventRecapReviewStatus.NEEDS_REVISION: "✏️ Требуется доработка",
}


class EventRecapReviewTextTooLongError(Exception):
    """Raised only if the bounded preview itself still exceeds SAFE_LIMIT (e.g. a pathologically
    long title/summary) - the routine case is already handled by the per-list item caps above;
    this is a defensive backstop, not the normal path."""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def render_event_recap_review_text(review: EventRecapReview, recap_result: dict) -> str:
    """Renders ONE bounded preview message for a synthesized EVENT_RECAP - title, summary, a few
    key takeaways, uncertainty notes, and the current review status line. Called both for the
    initial send AND for every decision re-render, so it always reflects the CURRENT status, never
    a stale snapshot (mirrors render_article_review_text()'s identical discipline).

    `recap_result` is the recap's own persisted result dict (see this module's own docstring) -
    this function does not read `EventRecapCandidate.publishable` or any other field of that
    object; it never even imports that type."""
    title = str(recap_result.get("recap_title") or "(без заголовка)")
    summary = str(recap_result.get("recap_summary") or "")
    takeaways = recap_result.get("key_takeaways") or []
    uncertainty_notes = recap_result.get("uncertainty_notes") or []

    lines = [
        "🗞 EVENT RECAP (shadow — только для ревью)",
        "",
        "Заголовок:",
        title,
        "",
        summary,
    ]
    if isinstance(takeaways, list) and takeaways:
        lines.append("")
        lines.append("Ключевые пункты:")
        for takeaway in takeaways[:_MAX_PREVIEW_ITEMS]:
            lines.append(f"- {_truncate(str(takeaway), _MAX_ITEM_CHARS)}")
        if len(takeaways) > _MAX_PREVIEW_ITEMS:
            lines.append(f"...и ещё {len(takeaways) - _MAX_PREVIEW_ITEMS}.")
    if isinstance(uncertainty_notes, list) and uncertainty_notes:
        lines.append("")
        lines.append("Что остаётся неопределённым:")
        for note in uncertainty_notes[:_MAX_PREVIEW_ITEMS]:
            lines.append(f"- {_truncate(str(note), _MAX_ITEM_CHARS)}")
        if len(uncertainty_notes) > _MAX_PREVIEW_ITEMS:
            lines.append(f"...и ещё {len(uncertainty_notes) - _MAX_PREVIEW_ITEMS}.")

    lines.append("")
    lines.append("Это черновик для внутреннего ревью — автоматически не публикуется.")
    lines.append(_STATUS_LINE_RU[review.status])

    text = "\n".join(lines)
    if len(text) > SAFE_LIMIT:
        raise EventRecapReviewTextTooLongError(
            f"Rendered EVENT_RECAP review text is {len(text)} chars, exceeds {SAFE_LIMIT}."
        )
    return text
