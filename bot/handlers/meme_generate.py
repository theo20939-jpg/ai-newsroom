"""MEME PRODUCTION PIPELINE (overnight phase): manual "😂 Сгенерировать мем" NEWS-button callback
handler. Thin orchestration only, mirroring `bot/handlers/telegraph_article_review.py`'s own "no
query construction, no AI/workflow call, no mutation logic of its own [beyond the one orchestration
entry point]" discipline - every DB read/write past the initial existence check goes through
`services/meme_generation_orchestrator.py::trigger_meme_generation()`.

Authorization: the SAME two-factor shape every other editorial-action callback in this codebase
already established (newsroom chat scope + a fail-closed per-feature allowlist -
`settings.meme_manual_approver_user_ids`, deliberately its own setting, never
`telegraph_approver_user_ids` - see that setting's own docstring in core/config.py for why).

The button is bound to the durable `NewsEvent.id` carried inside `callback_data` itself
(`bot/keyboards/meme_generate.py`) - never inferred from the visible message text. A stale/
deleted event is detected by a fresh DB read on every callback, exactly like every other handler
in this codebase.

Acknowledges the callback FIRST (`callback.answer(...)`), before ever starting the (potentially
several-second, LLM/image-calling) orchestration - never risks a Telegram callback timeout.
Generation happens synchronously in this same handler coroutine afterward (no separate queue/
worker exists for this in the codebase yet; mirrors `bot/handlers/telegraph_article_review.py`'s
own identical "await the orchestration inline, after acking" pattern for
`publish_approved_telegraph_article()`). The result is delivered to the MEMES editorial topic by
`trigger_meme_generation()` itself - never back into the NEWS chat/message this callback came
from.
"""
from __future__ import annotations

import logging
from pathlib import Path
from uuid import UUID

from aiogram import F, Router
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.meme_generate import parse_callback_data
from core.config import settings
from database.models.news_event import NewsEvent
from database.session import async_session_factory
from integrations.storage.image_storage import ImageStorage, LocalImageStorage
from services.meme_generation_orchestrator import trigger_meme_generation

logger = logging.getLogger(__name__)

router = Router(name="meme_generate")

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "prompts"

# Mirrors services/image_persistence.py::_get_storage()'s own private, module-scoped singleton
# pattern exactly - duplicated rather than imported (that function is private there too, matching
# this codebase's own established per-module-private-helper convention).
_storage_singleton: ImageStorage | None = None


def _get_storage() -> ImageStorage:
    global _storage_singleton
    if _storage_singleton is None:
        _storage_singleton = LocalImageStorage(settings.image_storage_root)
    return _storage_singleton


def _is_authorized_chat(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    return message.chat.id == settings.newsroom_telegram_chat_id


def _is_authorized_approver(callback: CallbackQuery) -> bool:
    if not settings.meme_manual_approver_user_ids:
        return False
    return callback.from_user.id in settings.meme_manual_approver_user_ids


@router.callback_query(F.data.startswith("memegen:"))
async def handle_meme_generate_callback(callback: CallbackQuery) -> None:
    news_event_id: UUID | None = parse_callback_data(callback.data or "")
    if news_event_id is None:
        await callback.answer()
        return

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return

    if not _is_authorized_chat(message):
        logger.warning(
            "meme_generate_unauthorized_chat",
            extra={"chat_id": message.chat.id, "news_event_id": str(news_event_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    if not _is_authorized_approver(callback):
        logger.warning(
            "meme_generate_unauthorized_user",
            extra={"user_id": callback.from_user.id, "news_event_id": str(news_event_id)},
        )
        await callback.answer("Недостаточно прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        event = await session.get(NewsEvent, news_event_id)
        if event is None:
            await callback.answer("Событие больше недоступно.", show_alert=True)
            return

    # Acknowledge quickly, BEFORE the (potentially multi-second) orchestration below - never risk
    # a Telegram callback timeout.
    await callback.answer("Мем отправлен в генерацию")

    from integrations.llm_gateway.boot import assemble_ai_integration_layer
    from integrations.llm_gateway.models.catalog import build_model_registry
    from integrations.prompts.file_repository import FilePromptRepository
    from services.pricing_catalog import ModelRegistryPricingCatalog

    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    assert message.bot is not None
    async with async_session_factory() as session:
        outcome = await trigger_meme_generation(
            session,
            news_event_id=news_event_id,
            trigger_source="manual",
            capability_registry=ai_layer.capability_registry,
            # image_gateway omitted - trigger_meme_generation() lazily constructs a
            # MockImageAdapter by default (no real, paid image-generation provider is wired
            # anywhere in this codebase yet, per that function's own module docstring). It is
            # only ever actually CALLED when settings.meme_image_generation_mode != "off"
            # (generate_meme_image()'s own gate).
            storage=_get_storage(),
            bot=message.bot,
            cost_tracker=ai_layer.cost_tracker,
            pricing_catalog=pricing_catalog,
        )

    logger.info(
        "meme_generate_handler_outcome",
        extra={"news_event_id": str(news_event_id), "status": outcome.status, "task_id": str(outcome.task_id) if outcome.task_id else None},
    )
