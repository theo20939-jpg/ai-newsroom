"""TELEGRAPH Checkpoint 6 (revised, TELEGRAPH EDITORIAL CHAT DELIVERY): pure Telegram
article-review rendering support. Mirrors bot/telegraph_shortlist_formatting.py's own "pure
functions, no aiogram/Bot type anywhere in this module" discipline exactly - testable with zero
Telegram mocking, no database access.

Product correction: the editor is the FINAL publisher, manually, wherever needed - this module
never sends anything to any external publishing surface, and never sends a bounded "preview" that
hides content behind "the full text is available in the system." The editor needs
the COMPLETE article delivered into the TELEGRAPH editorial Telegram topic, in order, with nothing
missing, so they can copy it out and publish it themselves.

Because a full long-form article routinely exceeds Telegram's 4096-UTF-16-code-unit single-message
limit (Contract §14, same constant bot/formatting.py::SAFE_LIMIT already established), delivery is
split across THREE kinds of message, all sent to the same TELEGRAPH_TOPIC_ID thread
(services/telegraph_article_review_notifier.py owns the actual sending/ordering):
  1. `render_article_review_header()` - ONE message: channel + title. Sent once, never edited
     again afterward (a `status` line would go stale the moment a decision is made on the FOOTER
     message instead, so none is shown here - see `render_article_footer_text()`'s own docstring).
  2. `build_article_body_chunks()` - the article's own full text (lead, then every section in the
     TELEGRAPH_ARTICLE result schema's own field order), packed into as many sequential messages
     as needed. Never truncates, never drops a paragraph, never splits one paragraph's own text
     across two messages (each `confirmed_facts`/`context`/etc. list item is treated as one
     indivisible unit) - see that function's own docstring for the one deliberate exception (a
     single pathological unit longer than SAFE_LIMIT on its own).
  3. `render_article_footer_text()` - ONE message: numbered sources + the CURRENT review status
     line. This is the one message re-rendered (via services/telegraph_article_review_notifier.py
     ::update_article_review_message()) after every APPROVE/NEEDS_REVISION decision, exactly
     mirroring the old single-message design's own "render once, reused for the initial send AND
     every decision re-render" discipline - just scoped to this one message instead of the whole
     article, since it is the only one worth keeping current (bot/keyboards/
     telegraph_article_review.py's review-control keyboard is attached here too).

Operator-facing text is Russian throughout, matching Checkpoint 2's own established convention.
"""
from __future__ import annotations

from typing import Any

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from schemas.editorial import EditorialChannel

# Same constant bot/telegraph_shortlist_formatting.py::SAFE_LIMIT already established - Telegram's
# own hard limit for a plain text message, in UTF-16 code units (bot/formatting.py's own frozen
# invariant - see `_telegram_utf16_length()` below for why plain `len()` is never used for this).
SAFE_LIMIT = 4096

# Editorial channel split: deterministic, no LLM - a plain display label per
# schemas.editorial.EditorialChannel value. Emoji/labels exactly as given in the original brief -
# never derived/guessed.
_CHANNEL_LABEL_RU: dict[EditorialChannel, str] = {
    EditorialChannel.NINJA_AI: "🥷 Ninja AI",
    EditorialChannel.NINJA_PULSE: "⚡ Ninja Pulse",
}

_STATUS_LINE_RU: dict[TelegraphArticleReviewStatus, str] = {
    TelegraphArticleReviewStatus.PENDING: "⏳ Решение не принято",
    TelegraphArticleReviewStatus.APPROVED: "✅ Статья одобрена",
    TelegraphArticleReviewStatus.NEEDS_REVISION: "✏️ Требуется доработка",
}

# The TELEGRAPH_ARTICLE result schema's own field order (prompts/article_generation/v2.yaml::
# output_schema) - never re-ordered by this module. `lead` and `conclusion` are handled separately
# (below) since they are single strings, not list-of-string sections like these.
_BODY_SECTION_FIELDS: tuple[tuple[str, str], ...] = (
    ("context", "Контекст"),
    ("timeline", "Хронология"),
    ("confirmed_facts", "Подтверждённые факты"),
    ("analysis", "Анализ"),
    ("implications", "Последствия"),
    ("background", "Предыстория"),
    ("risks", "Риски и оговорки"),
)


class ArticleReviewTextTooLongError(Exception):
    """Raised only for the header/footer messages, if one somehow still exceeds SAFE_LIMIT on its
    own (e.g. a pathologically long headline, or an implausibly large number of sources) - a
    defensive backstop, not the normal path. The article BODY itself never raises this; it is
    always safely chunked instead (`build_article_body_chunks()`), never truncated, never
    rejected."""


def _telegram_utf16_length(text: str) -> int:
    """Byte-for-byte the same frozen invariant bot/formatting.py::_telegram_utf16_length()
    already established - duplicated per this codebase's own established per-module-private-
    helper convention (that function is private/module-scoped there too)."""
    return len(text.encode("utf-16-le")) // 2


def render_article_review_header(article_result: dict[str, Any], editorial_channel: EditorialChannel) -> str:
    """ONE message: channel + title only - sent once by services/telegraph_article_review_
    notifier.py::send_article_review() and never edited again. Deliberately carries NO status
    line (unlike the old single-message preview's own design) - a status line embedded here would
    go stale the instant a decision is made, since only the FOOTER message
    (`render_article_footer_text()`) is ever re-rendered after APPROVE/NEEDS_REVISION."""
    headline = str(article_result.get("headline") or "(без заголовка)")
    channel_label = _CHANNEL_LABEL_RU[editorial_channel]
    text = "\n".join(["📰 TELEGRAPH ARTICLE", "", "Канал:", channel_label, "", "Тема:", headline])
    if _telegram_utf16_length(text) > SAFE_LIMIT:
        raise ArticleReviewTextTooLongError(
            f"Rendered TELEGRAPH article header is {_telegram_utf16_length(text)} UTF-16 code "
            f"units, exceeds {SAFE_LIMIT} (headline alone is implausibly long)."
        )
    return text


def _build_body_paragraph_units(article_result: dict[str, Any]) -> list[str]:
    """Flattens the article's own full content into an ordered list of indivisible text units -
    one per section heading and one per individual list item (never a whole section's items
    joined into one unit, so `build_article_body_chunks()` can always pack/split at these exact
    boundaries without ever cutting inside a single fact/paragraph). Order matches the schema's
    own field order exactly: lead, then every _BODY_SECTION_FIELDS section in order, then
    conclusion. `sources` is deliberately NOT included here - it belongs in the separate footer
    message (`render_article_footer_text()`), never mixed into the body."""
    units: list[str] = []

    lead = article_result.get("lead")
    if lead:
        units.append(str(lead))

    for field, heading_ru in _BODY_SECTION_FIELDS:
        items = article_result.get(field)
        if isinstance(items, str) and items.strip():
            items = [items]  # schema-drift degrade, mirrors this codebase's own established pattern
        if isinstance(items, list) and items:
            units.append(f"{heading_ru}:")
            units.extend(str(item) for item in items if str(item).strip())

    conclusion = article_result.get("conclusion")
    if conclusion:
        units.append("Заключение:")
        units.append(str(conclusion))

    return units


def _split_oversized_unit(unit: str, limit: int) -> list[str]:
    """Defensive fallback for the one case a single paragraph unit alone exceeds `limit` (a
    pathologically long fact/paragraph, never the expected shape) - splits at word boundaries
    only, never mid-word, never drops a single word. This is the only place this module ever cuts
    inside what was originally one paragraph; the routine path (every ordinary-length unit) never
    reaches this function at all."""
    words = unit.split(" ")
    pieces: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}" if current else word
        if _telegram_utf16_length(candidate) > limit and current:
            pieces.append(current)
            current = word
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [unit[:1]]  # unreachable in practice (limit is always >> 1 code unit)


def build_article_body_chunks(article_result: dict[str, Any], *, limit: int = SAFE_LIMIT) -> list[str]:
    """Packs the article's full body (every paragraph unit from `_build_body_paragraph_units()`,
    in order) into as many sequential Telegram messages as needed - greedy bin-packing, joining
    consecutive units with a blank line ("\\n\\n") exactly like the old single-message renderer's
    own paragraph separator. Never truncates and never drops content: a unit that would overflow
    the current chunk starts a new chunk instead of being cut, and the one pathological case where
    a SINGLE unit alone exceeds `limit` is word-boundary-split (`_split_oversized_unit()`) rather
    than silently shortened. Always returns at least one chunk (a placeholder string for the
    unreachable-in-practice all-empty-article case, never an empty list)."""
    raw_units = _build_body_paragraph_units(article_result)

    flat_units: list[str] = []
    for unit in raw_units:
        if _telegram_utf16_length(unit) > limit:
            flat_units.extend(_split_oversized_unit(unit, limit))
        else:
            flat_units.append(unit)

    chunks: list[str] = []
    current_parts: list[str] = []
    current_len = 0
    for unit in flat_units:
        unit_len = _telegram_utf16_length(unit)
        added_len = unit_len if not current_parts else unit_len + 2  # "\n\n" separator
        if current_parts and current_len + added_len > limit:
            chunks.append("\n\n".join(current_parts))
            current_parts = [unit]
            current_len = unit_len
        else:
            current_parts.append(unit)
            current_len += added_len
    if current_parts:
        chunks.append("\n\n".join(current_parts))

    return chunks or ["(текст статьи отсутствует)"]


def render_article_footer_text(article_result: dict[str, Any], review: TelegraphArticleReview) -> str:
    """ONE message: numbered sources + the CURRENT review status line. Called both for the
    initial footer send AND for every decision re-render (services/telegraph_article_review_
    notifier.py::update_article_review_message()), so it always reflects the CURRENT status,
    never a stale snapshot - mirrors the old single-message design's own identical discipline,
    just scoped to this one message. The review-control keyboard (bot/keyboards/
    telegraph_article_review.py::build_article_review_keyboard()) is attached to this same message
    by the caller, never rendered as text here."""
    sources = article_result.get("sources") or []
    lines = ["Источники:"]
    if isinstance(sources, list) and sources:
        lines.extend(f"{i}. {source}" for i, source in enumerate(sources, start=1))
    else:
        lines.append("(источники не указаны)")
    lines.append("")
    lines.append(_STATUS_LINE_RU[review.status])

    text = "\n".join(lines)
    if _telegram_utf16_length(text) > SAFE_LIMIT:
        raise ArticleReviewTextTooLongError(
            f"Rendered TELEGRAPH article footer is {_telegram_utf16_length(text)} UTF-16 code "
            f"units, exceeds {SAFE_LIMIT} (an implausibly large number of sources)."
        )
    return text
