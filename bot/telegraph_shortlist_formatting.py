"""TELEGRAPH Checkpoint 2: pure Telegram shortlist rendering support. Mirrors `bot/
meme_preview_formatting.py`'s own "pure functions, no aiogram/Bot type anywhere in this module"
discipline exactly - testable with zero Telegram mocking, no database access.

Operator-facing text is Russian throughout (the phase brief's own explicit requirement) - but this
module never calls an LLM to produce it. Every sentence is deterministic string formatting over
`TelegraphTopicProposal.signals_snapshot`/`rationale_snapshot`/`topic_title` - values services.
telegraph_topic_candidates.py already computed. This module only decides how to WORD them for a
human reader, never what they mean.
"""
from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal

# Telegram's own hard limit for a plain text message, in UTF-16 code units - same constant
# bot/formatting.py::SAFE_LIMIT already established for the NEWS card. The shortlist is
# text-only (no photo), so the larger 4096 limit applies, not CAPTION_SAFE_LIMIT's 1024.
SAFE_LIMIT = 4096

_STATUS_LINE_RU: dict[TelegraphProposalStatus, str] = {
    TelegraphProposalStatus.PENDING: "⏳ Решение не принято",
    TelegraphProposalStatus.APPROVED: "✅ Одобрено",
    TelegraphProposalStatus.REJECTED: "❌ Отклонено",
}


class TelegraphShortlistTextTooLongError(Exception):
    """Raised when the rendered shortlist text exceeds `SAFE_LIMIT` - never silently truncated
    (mirrors `bot/formatting.py::CardTooLongError`/`bot/meme_preview_formatting.py::
    MemePreviewCaptionTooLongError`'s identical "fail loud, let the caller decide" discipline)."""


def render_no_topics_text() -> str:
    """A weak shortlist window producing zero candidates is a valid, real outcome (services/
    telegraph_shortlist_service.py::create_telegraph_shortlist() persists no batch for it) - this
    is the one piece of text a caller MAY choose to send instead of a message, if it decides a
    "no topics today" notice is worth sending at all (this module makes no delivery decision of
    its own)."""
    return "📝 TELEGRAPH — на сегодня нет достаточно сильных тем."


def _render_rationale_ru(signals: dict[str, object]) -> str:
    """Deterministic, no LLM - a short, human phrase built only from already-computed signals,
    never the raw diagnostic `rationale_snapshot` string (the phase brief's own explicit "do not
    dump raw diagnostics")."""
    parts: list[str] = []
    event_count = signals.get("event_count")
    if isinstance(event_count, int) and event_count >= 2:
        parts.append(f"{event_count} связанных материала" if event_count < 5 else f"{event_count} связанных материалов")
    source_diversity = signals.get("source_diversity_proxy")
    if isinstance(source_diversity, int) and source_diversity >= 2:
        parts.append(f"{source_diversity} независимых источника" if source_diversity < 5 else f"{source_diversity} независимых источников")
    if signals.get("evidence_tier") == "strong":
        parts.append("подтверждённые факты")
    return ", ".join(parts) if parts else "значимая тема"


def _render_one_topic(proposal: TelegraphTopicProposal) -> str:
    signals = proposal.signals_snapshot
    significance = signals.get("normalized_significance")
    significance_text = f"{significance:.1f}/10" if isinstance(significance, (int, float)) else "н/д"
    source_count = signals.get("source_diversity_proxy")
    source_text = str(source_count) if isinstance(source_count, int) else "н/д"

    lines = [
        f"{proposal.rank}. {proposal.topic_title}",
        f"Почему стоит разобрать: {_render_rationale_ru(signals)}",
        "",
        f"Потенциал: {proposal.topic_score}/100",
        f"Источники: {source_text}",
        f"Значимость: {significance_text}",
        _STATUS_LINE_RU[proposal.status],
    ]
    return "\n".join(lines)


def render_shortlist_message_text(proposals: list[TelegraphTopicProposal]) -> str:
    """Renders the full shortlist as ONE message body (the phase brief's own explicit "prefer
    ONE Telegram message per shortlist batch"). `proposals` must already be in the batch's own
    persisted `rank` order (services/telegraph_shortlist_service.py::
    TelegraphShortlistService.list_proposals_for_batch() guarantees this) - this function does
    not sort. Called both for the initial send AND for every decision re-render, so it always
    reflects each proposal's CURRENT status line, never a stale snapshot.

    Raises `TelegraphShortlistTextTooLongError` rather than silently truncating - a shortlist
    that does not fit is a real content problem (too many/too verbose topics) the caller must
    know about, never quietly cut."""
    if not proposals:
        return render_no_topics_text()

    header = "📝 TELEGRAPH — темы для статьи"
    body = "\n\n".join(_render_one_topic(p) for p in proposals)
    text = f"{header}\n\n{body}"
    if len(text) > SAFE_LIMIT:
        raise TelegraphShortlistTextTooLongError(
            f"Rendered TELEGRAPH shortlist text is {len(text)} chars, exceeds {SAFE_LIMIT}."
        )
    return text
