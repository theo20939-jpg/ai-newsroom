"""Phase 18 M8: Telegram Meme Editorial Preview callback handler (docs/
phase18_m8_telegram_editorial_preview_report.md). Thin orchestration only, mirroring
`bot/handlers/image_preview.py`'s own "no query construction, no AI/workflow call, no mutation
logic of its own" discipline - every DB read/write goes through
`services/meme_candidate_service.py::MemeCandidateService`.

State is re-queried fresh from the database on every single callback - never cached, never
trusted from an earlier render, so a stale/deleted candidate is always detected against current
state (mirrors `bot/handlers/image_preview.py`'s identical discipline).

Not exercised against a live Telegram Bot or database in this session (the local Postgres/Redis
stack is unavailable - same disclosed constraint as every DB-dependent piece of Phases 18 M1-M7).
Written to mirror `bot/handlers/image_preview.py`'s already-proven shape as closely as possible,
so the risk of a structural mistake is minimized even without a live run.

"Regenerate concept/image/text" and "fallback to normal news" are recognized and acknowledged
(`callback.answer(...)`) but do NOT yet re-run any generation step - no live MEME_GENERATION
task-spawning/regeneration orchestrator exists as of M8 (disclosed in the M8 report §6; building
one is future work, not silently faked here).
"""
import logging
from uuid import UUID

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, InaccessibleMessage, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.meme_preview import build_decided_keyboard, parse_callback_data
from bot.meme_preview_formatting import (
    MemePreviewCaptionTooLongError,
    render_expired_candidate_alert_text,
    render_meme_preview_caption,
    render_unavailable_candidate_alert_text,
)
from database.models.meme_candidate import MemeCandidate, MemeCandidateStatus
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from schemas.meme_copy import MemeCopy
from schemas.meme_preview import MemePreviewCard
from services.meme_candidate_service import MemeCandidateService

logger = logging.getLogger(__name__)

router = Router(name="meme_preview")

_REGENERATE_ACTIONS = {"regen_concept", "regen_image", "regen_text"}
_TERMINAL_STATUSES = {MemeCandidateStatus.APPROVED, MemeCandidateStatus.REJECTED}


def _card_from_candidate(candidate: MemeCandidate, event: NewsEvent) -> MemePreviewCard | None:
    """`None` if the candidate has no copy yet (M4 hasn't run for it) - a preview cannot be
    rendered without final text; the caller treats this exactly like "unavailable"."""
    if candidate.copy_data is None:
        return None
    copy = MemeCopy.model_validate(candidate.copy_data)
    return MemePreviewCard(
        candidate_id=candidate.id,
        news_title=event.title,
        news_url=event.url,
        news_category=event.category.value,
        top_text=copy.top_text,
        bottom_text=copy.bottom_text,
        telegram_caption=copy.telegram_caption,
        editor_explanation=copy.editor_explanation,
        alt_text=copy.alt_text,
        image_storage_key=candidate.render_storage_key or candidate.image_storage_key,
        safety_summary=f"Safety: {candidate.safety_status or 'unknown'}",
        quality_summary=f"Quality: {candidate.quality_decision or 'unknown'}",
    )


@router.callback_query(F.data.startswith("memeprev:"))
async def handle_meme_preview_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer()
        return
    action, candidate_id = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
        return

    async with async_session_factory() as session:
        candidate, event = await _load_candidate_and_event(session, candidate_id)
        if candidate is None or event is None:
            await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
            return
        if candidate.status in _TERMINAL_STATUSES:
            await callback.answer(render_expired_candidate_alert_text(), show_alert=True)
            return

        card = _card_from_candidate(candidate, event)
        if card is None:
            await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
            return

        if action in _REGENERATE_ACTIONS or action == "fallback":
            # Recognized, acknowledged, not yet orchestrated (module docstring §"Regenerate...").
            logger.info(
                "meme_preview_action_acknowledged_not_orchestrated",
                extra={"candidate_id": str(candidate_id), "action": action},
            )
            await callback.answer(f"Recorded: {action.replace('_', ' ')}. Regeneration is not yet automated.")
            return

        decision = "approved" if action == "approve" else "rejected"
        service = MemeCandidateService(session)
        updated = await service.record_editor_decision(candidate_id, decision)
        if updated is None:
            await callback.answer(render_unavailable_candidate_alert_text(), show_alert=True)
            return

        await _finalize_decision(message, card=card, source_url=event.url)
        await callback.answer("Approved." if decision == "approved" else "Rejected.")


async def _load_candidate_and_event(
    session: AsyncSession, candidate_id: UUID,
) -> tuple[MemeCandidate | None, NewsEvent | None]:
    service = MemeCandidateService(session)
    candidate = await service.get_by_id(candidate_id)
    if candidate is None:
        return None, None
    event = await session.get(NewsEvent, candidate.news_event_id)
    return candidate, event


async def _finalize_decision(message: Message, *, card: MemePreviewCard, source_url: str | None) -> None:
    """Terminal state for the message once a decision has been made - shrinks the keyboard to
    just the Source button, mirrors `bot/handlers/image_preview.py::_finalize_decision()`'s own
    established shape."""
    keyboard = build_decided_keyboard(source_url)
    bot = message.bot
    assert bot is not None
    try:
        caption = render_meme_preview_caption(card)
    except MemePreviewCaptionTooLongError:
        logger.error("meme_preview_finalize_render_failed", extra={"candidate_id": str(card.candidate_id)})
        return
    try:
        if message.photo:
            await bot.edit_message_caption(
                chat_id=message.chat.id, message_id=message.message_id, caption=caption, reply_markup=keyboard,
            )
        else:
            await bot.edit_message_text(
                chat_id=message.chat.id, message_id=message.message_id, text=caption, reply_markup=keyboard,
            )
    except TelegramAPIError:
        logger.exception("meme_preview_finalize_failed", extra={"candidate_id": str(card.candidate_id)})
