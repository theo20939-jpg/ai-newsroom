"""SOCIAL-INTELLIGENCE-OPS-1, spec §3/§4/§5/§7: /surface - Telegram Surface configuration through
the SAME General-topic Command Center. Router registration mirrors bot/handlers/business_context
.py's own shape exactly - same two-factor gate (duplicated per this codebase's established
convention), same lazily-constructed AI layer, same propose->confirm/cancel lifecycle.

CRITICAL (spec §5): reading surface status is available to every role the CommandRegistry grants
"surface" to, but SUBMITTING a configuration change additionally requires FOUNDER tier - checked
via the exact same `is_command_allowed(user_id, "directive")` proxy
bot/handlers/business_context.py's own callback handler already uses for "is this a FOUNDER-tier
user" (only FOUNDER has "directive" in its command set - see services/business_context_roles.py)."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.telegram_surface import build_proposal_keyboard, parse_callback_data
from bot.telegram_surface_formatting import render_surface_proposal_preview, render_surface_status
from core.config import settings
from database.models.telegram_surface import TelegramSurfaceRole
from database.models.telegram_surface_proposal import TelegramSurfaceProposalStatus
from database.session import async_session_factory
from integrations.llm_gateway.boot import AIIntegrationLayer, assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from services.business_context_roles import is_command_allowed
from services.telegram_surface_command_parser import (
    TelegramSurfaceParseError,
    parse_surface_command,
    resolve_chat_id,
)
from services.telegram_surface_proposal_service import cancel_proposal, confirm_proposal, create_proposal, get_proposal
from services.telegram_surface_registry import list_surfaces

logger = logging.getLogger(__name__)

router = Router(name="telegram_surface")

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "prompts"
_ai_layer: AIIntegrationLayer | None = None
_prompt_repository: FilePromptRepository | None = None
_ai_layer_lock = asyncio.Lock()


async def _get_ai_layer() -> tuple[AIIntegrationLayer, FilePromptRepository]:
    global _ai_layer, _prompt_repository
    if _ai_layer is not None and _prompt_repository is not None:
        return _ai_layer, _prompt_repository
    async with _ai_layer_lock:
        if _ai_layer is None or _prompt_repository is None:
            _prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
            _ai_layer = assemble_ai_integration_layer(settings, _prompt_repository)
    return _ai_layer, _prompt_repository


def _is_authorized_chat_and_topic(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    if message.chat.id != settings.newsroom_telegram_chat_id:
        return False
    return message.message_thread_id == settings.business_context_topic_id


async def _fail_wrong_location(message: Message) -> None:
    await message.answer("🥷 Команда /surface работает только в General теме внутреннего чата NINJA Newsroom.")


async def _fail_no_permission(message: Message) -> None:
    await message.answer("🥷 У вас нет доступа к команде /surface.")


async def _fail_not_founder(message: Message) -> None:
    await message.answer("🥷 Настраивать поверхности может только FOUNDER. Вы можете посмотреть текущий статус: /surface")


@router.message(Command("surface"))
async def handle_surface(message: Message, command: CommandObject) -> None:
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, "surface"):
        await _fail_no_permission(message)
        return

    if not command.args or not command.args.strip():
        async with async_session_factory() as session:
            surfaces = await list_surfaces(session)
        await message.answer(render_surface_status(surfaces))
        return

    # Anything past this point is an attempted MUTATION - FOUNDER tier only (spec §5).
    if not is_command_allowed(user_id, "directive"):
        await _fail_not_founder(message)
        return

    current_chat_name_hint = message.chat.title or message.chat.full_name or "текущий чат"
    ai_layer, prompt_repository = await _get_ai_layer()
    try:
        extraction = await parse_surface_command(
            ai_layer.gateway, prompt_repository, raw_text=command.args, current_chat_name_hint=current_chat_name_hint,
        )
    except TelegramSurfaceParseError:
        logger.exception("telegram_surface_parse_failed")
        await message.answer("Не удалось разобрать сообщение. Попробуйте переформулировать.")
        return

    if extraction.clarification_needed:
        await message.answer("🥷 Нужны уточнения: " + "; ".join(extraction.clarification_needed))
        return

    chat_id = resolve_chat_id(extraction, current_chat_id=message.chat.id)
    if chat_id is None:
        await message.answer(
            "🥷 Не удалось однозначно определить чат. Если это не текущий чат, укажите @username канала."
        )
        return

    try:
        role = TelegramSurfaceRole(extraction.role)
    except ValueError:
        role = TelegramSurfaceRole.OTHER

    async with async_session_factory() as session:
        proposal = await create_proposal(
            session, chat_id=chat_id, role=role, name=extraction.name, username=extraction.username,
            active=extraction.active, analytics_enabled=extraction.analytics_enabled, raw_instruction=command.args,
            created_by=user_id, telegram_chat_id=message.chat.id, telegram_topic_id=message.message_thread_id,
        )
        logger.info(
            "telegram_surface_proposal_created", extra={"proposal_id": str(proposal.id), "role": extraction.role},
        )

    preview = render_surface_proposal_preview(proposal)
    keyboard = build_proposal_keyboard(proposal)
    sent = await message.answer(preview, reply_markup=keyboard)

    async with async_session_factory() as session:
        refreshed = await get_proposal(session, proposal.id)
        if refreshed is not None:
            refreshed.telegram_message_id = sent.message_id
            await session.commit()


@router.callback_query(F.data.startswith("tgsurface:"))
async def handle_surface_callback(callback: CallbackQuery) -> None:
    parsed = parse_callback_data(callback.data or "")
    if parsed is None:
        await callback.answer("Некорректные данные кнопки.", show_alert=True)
        return
    action, proposal_id = parsed

    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        await callback.answer("Сообщение недоступно.", show_alert=True)
        return
    if not _is_authorized_chat_and_topic(message):
        await callback.answer("Недоступно вне General.", show_alert=True)
        return

    user_id = callback.from_user.id
    if not is_command_allowed(user_id, "directive"):
        await callback.answer("Только FOUNDER может подтвердить настройку поверхности.", show_alert=True)
        return

    async with async_session_factory() as session:
        proposal = await get_proposal(session, proposal_id)
        if proposal is None:
            await callback.answer("Предложение не найдено.", show_alert=True)
            return

        if proposal.status != TelegramSurfaceProposalStatus.PENDING:
            await callback.answer("Уже обработано.", show_alert=True)
            return

        if action == "confirm":
            proposal = await confirm_proposal(session, proposal_id, decided_by=user_id)
            ack = "Подтверждено"
            logger.info("telegram_surface_updated", extra={"proposal_id": str(proposal_id)})
        elif action == "cancel":
            proposal = await cancel_proposal(session, proposal_id, decided_by=user_id)
            ack = "Отменено"
        else:  # "edit"
            await callback.answer(
                "Отправьте команду заново с исправленным текстом - это создаст новое предложение.",
                show_alert=True,
            )
            return

    assert proposal is not None
    new_text = render_surface_proposal_preview(proposal) + f"\n\n{ack}."
    try:
        await message.edit_text(new_text, reply_markup=build_proposal_keyboard(proposal))
    except Exception:  # noqa: BLE001 - best-effort re-render, the decision itself already persisted
        logger.exception("telegram_surface_proposal_rerender_failed", extra={"proposal_id": str(proposal_id)})
    await callback.answer(ack)
