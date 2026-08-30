"""TELEGRAPH Checkpoint 6: pure Telegram article-review rendering support. Mirrors bot/
telegraph_shortlist_formatting.py's own "pure functions, no aiogram/Bot type anywhere in this
module" discipline exactly - testable with zero Telegram mocking, no database access.

TELEGRAPH LIVE PUBLISH: when a review is APPROVED and its `published_url` column is populated
(services/telegraph_publish_orchestrator.py sets it after a real telegra.ph createPage call),
render_article_review_text() additionally shows the published link - a small, additive block after
the existing status line, never replacing "✅ Статья одобрена" (both are independently true and
independently meaningful: the human APPROVED it, and it IS live).

Operator-facing text is Russian throughout, matching Checkpoint 2's own established convention.
Unlike the shortlist message (several short topics, fits comfortably under SAFE_LIMIT), a full
long-form article routinely does NOT fit in one Telegram message - this module deliberately
renders a bounded PREVIEW (headline/lead/a few facts/conclusion/source count), never the entire
article body, and says so explicitly in the message text. The full article remains readable from
its own durable source (EditorialTask.workflow["step_results"]) - this checkpoint does not build
a "send the rest" flow (no new Telegram pipeline, per the brief's own explicit constraint).
"""
from typing import Any

from database.models.telegraph_article_review import TelegraphArticleReview, TelegraphArticleReviewStatus
from schemas.editorial import EditorialChannel

# Same constant bot/telegraph_shortlist_formatting.py::SAFE_LIMIT already established - Telegram's
# own hard limit for a plain text message.
SAFE_LIMIT = 4096

# Editorial channel split: deterministic, no LLM - a plain display label per
# schemas.editorial.EditorialChannel value, mirroring _STATUS_LINE_RU's own "one dict, one place"
# convention. Emoji/labels exactly as given in the task brief - never derived/guessed.
_CHANNEL_LABEL_RU: dict[EditorialChannel, str] = {
    EditorialChannel.NINJA_AI: "🥷 Ninja AI",
    EditorialChannel.NINJA_PULSE: "⚡ Ninja Pulse",
}

# How much of the article's own content this preview shows before summarizing the rest - a
# reasoned starting bound (this checkpoint's own first calibration), never the full article.
_MAX_PREVIEW_FACTS = 3
_MAX_FACT_CHARS = 200

_STATUS_LINE_RU: dict[TelegraphArticleReviewStatus, str] = {
    TelegraphArticleReviewStatus.PENDING: "⏳ Решение не принято",
    TelegraphArticleReviewStatus.APPROVED: "✅ Статья одобрена",
    TelegraphArticleReviewStatus.NEEDS_REVISION: "✏️ Требуется доработка",
}


class ArticleReviewTextTooLongError(Exception):
    """Raised only if the bounded preview itself still exceeds SAFE_LIMIT (e.g. a pathologically
    long headline) - the routine case (a long article body) is already handled by truncating to
    a preview before this check ever runs; this is a defensive backstop, not the normal path."""


def _truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 1].rstrip() + "…"


def render_article_review_text(
    review: TelegraphArticleReview, article_result: dict[str, Any], editorial_channel: EditorialChannel,
) -> str:
    """Renders ONE bounded preview message for a generated article - channel, headline, lead, a
    few confirmed facts, conclusion, source count, and the current review status line. Called
    both for the initial send AND for every decision re-render, so it always reflects the CURRENT
    status, never a stale snapshot (mirrors render_shortlist_message_text()'s identical
    discipline).

    `editorial_channel` is a required, explicit parameter, never looked up inside this function -
    this module stays pure/DB-free (module docstring's own "no database access" discipline); the
    caller (bot/handlers/telegraph_article_review.py, services/telegraph_article_review_notifier.py,
    scripts/telegraph_pipeline_worker.py) is responsible for fetching it from the owning
    TelegraphTopicProposal via `review.proposal_id`."""
    headline = str(article_result.get("headline") or "(без заголовка)")
    lead = str(article_result.get("lead") or "")
    facts = article_result.get("confirmed_facts") or []
    conclusion = str(article_result.get("conclusion") or "")
    sources = article_result.get("sources") or []
    channel_label = _CHANNEL_LABEL_RU[editorial_channel]

    lines = [
        "📰 TELEGRAPH ARTICLE",
        "",
        "Канал:",
        channel_label,
        "",
        "Тема:",
        headline,
        "",
        lead,
    ]
    if isinstance(facts, list) and facts:
        lines.append("")
        lines.append("Ключевые факты:")
        for fact in facts[:_MAX_PREVIEW_FACTS]:
            lines.append(f"- {_truncate(str(fact), _MAX_FACT_CHARS)}")
        if len(facts) > _MAX_PREVIEW_FACTS:
            lines.append(f"...и ещё {len(facts) - _MAX_PREVIEW_FACTS}.")
    if conclusion:
        lines.append("")
        lines.append(f"Заключение: {_truncate(conclusion, _MAX_FACT_CHARS)}")
    if isinstance(sources, list) and sources:
        lines.append("")
        lines.append(f"Источников: {len(sources)}")

    lines.append("")
    lines.append("Это предпросмотр — полный текст статьи доступен в системе.")
    lines.append(_STATUS_LINE_RU[review.status])
    if review.status == TelegraphArticleReviewStatus.APPROVED and review.published_url:
        lines.append("")
        lines.append("✅ Статья опубликована")
        lines.append(review.published_url)

    text = "\n".join(lines)
    if len(text) > SAFE_LIMIT:
        raise ArticleReviewTextTooLongError(
            f"Rendered TELEGRAPH article review text is {len(text)} chars, exceeds {SAFE_LIMIT}."
        )
    return text
