"""NINJA PULSE RECAP Phase R2 integration, Phase C.1: pure EVENT_RECAP review-preview rendering.
Mirrors bot/telegraph_article_review_formatting.py's own "pure functions, no aiogram/Bot type
anywhere in this module, no database access" discipline exactly - testable with zero Telegram
mocking, zero DB access.

Operator-facing text is Russian throughout, matching every other TELEGRAPH review surface's own
established convention. Renders directly from an already-built `services.event_recap.
EventRecapCandidate` (no separate durable review row exists for EVENT_RECAP yet, unlike
TELEGRAPH_ARTICLE's own `TelegraphArticleReview` - Phase C.1 deliberately does not add one) - a
bounded PREVIEW (title/summary/a few takeaways/uncertainty notes/fact-verification status/source
count), never claims to be the final publishable text. `EventRecapCandidate.publishable` is never
read or referenced here at all - it stays exactly what services/event_recap.py already returns
(unconditionally False); this module has no publishing opinion of its own.

Never renders raw source URLs/external links in the message text (candidate.source_refs is shown
only as a bare count) - mirrors render_article_review_text()'s own identical "источников: N,
никогда сырых ссылок" precedent for this exact same internal-review-message class.
"""
from services.event_recap import EventRecapCandidate

# Same constant bot/telegraph_article_review_formatting.py::SAFE_LIMIT already established -
# Telegram's own hard limit for a plain text message.
SAFE_LIMIT = 4096

# How much of the candidate's own key_takeaways/uncertainty_notes this preview shows - a reasoned
# starting bound (this checkpoint's own first calibration), mirrors _MAX_PREVIEW_FACTS's identical
# role in the TELEGRAPH review formatter.
_MAX_PREVIEW_ITEMS = 8
_MAX_ITEM_CHARS = 300

_FACT_VERIFICATION_LABEL_RU: dict[str, str] = {
    "pass": "✅ пройдена",
    "review": "⚠️ требует внимания",
    "block": "⛔ заблокировано",
    "not_run": "— не выполнялась",
}


class EventRecapReviewTextTooLongError(Exception):
    """Raised only if the bounded preview itself still exceeds SAFE_LIMIT (e.g. a pathologically
    long title/summary) - the routine case is already handled by the per-list item caps above;
    this is a defensive backstop, not the normal path."""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def render_event_recap_review_text(candidate: EventRecapCandidate) -> str:
    """Renders ONE bounded preview message for a synthesized EVENT_RECAP candidate - title,
    summary, a few key takeaways, uncertainty notes, fact-verification status, and a bare source
    count. Always the SHADOW/review-only framing - this is never rendered as if it were a
    finished, publishable post."""
    title = candidate.recap_title or "(без заголовка)"
    summary = candidate.recap_summary or ""
    fact_status = candidate.fact_verification.status
    fact_label = _FACT_VERIFICATION_LABEL_RU.get(fact_status, fact_status)

    lines = [
        "🗞 EVENT RECAP (shadow — только для ревью)",
        "",
        "Заголовок:",
        title,
        "",
        summary,
    ]
    if candidate.key_takeaways:
        lines.append("")
        lines.append("Ключевые пункты:")
        for takeaway in candidate.key_takeaways[:_MAX_PREVIEW_ITEMS]:
            lines.append(f"- {_truncate(takeaway, _MAX_ITEM_CHARS)}")
        if len(candidate.key_takeaways) > _MAX_PREVIEW_ITEMS:
            lines.append(f"...и ещё {len(candidate.key_takeaways) - _MAX_PREVIEW_ITEMS}.")
    if candidate.uncertainty_notes:
        lines.append("")
        lines.append("Что остаётся неопределённым:")
        for note in candidate.uncertainty_notes[:_MAX_PREVIEW_ITEMS]:
            lines.append(f"- {_truncate(note, _MAX_ITEM_CHARS)}")
        if len(candidate.uncertainty_notes) > _MAX_PREVIEW_ITEMS:
            lines.append(f"...и ещё {len(candidate.uncertainty_notes) - _MAX_PREVIEW_ITEMS}.")

    lines.append("")
    lines.append(f"Проверка фактов: {fact_label}")
    if candidate.evidence_reference_count:
        lines.append(f"Источников: {candidate.evidence_reference_count}")

    lines.append("")
    lines.append("Это черновик для внутреннего ревью — автоматически не публикуется.")

    text = "\n".join(lines)
    if len(text) > SAFE_LIMIT:
        raise EventRecapReviewTextTooLongError(
            f"Rendered EVENT_RECAP review text is {len(text)} chars, exceeds {SAFE_LIMIT}."
        )
    return text
