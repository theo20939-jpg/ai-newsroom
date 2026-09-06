"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §12/§13/§14: /launch - cold-start social launch strategy
through the SAME General-topic Command Center. Router registration mirrors bot/handlers/
telegram_surface.py's own shape exactly - same two-factor gate, same lazily-constructed AI layer,
same propose->confirm/cancel lifecycle.

CRITICAL (spec §3, PRELAUNCH-1A): reading launch context is available to every role the
CommandRegistry grants "launch" to; SUBMITTING an instruction additionally requires FOUNDER tier -
checked via `is_command_allowed(user_id, "launch_mutate")`, /launch's OWN canonical mutation
permission (services/business_context_roles.py), never the "directive" proxy /surface and /design
still use. This deliberately decouples /launch's authorization from any other command's - changing
who may issue a strategic directive can never accidentally change who may mutate launch context.

CRITICAL (spec §5): `settings.social_launch_context_enabled` (default False) gates the WHOLE
command, mirroring bot/handlers/director_console.py's own `director_console_enabled` precedent -
checked inside the handler, never via conditional router registration, so the router itself stays
always-importable/testable."""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.launch import build_proposal_keyboard, parse_callback_data
from bot.launch_formatting import render_launch_context, render_launch_proposal_preview
from core.config import settings
from database.models.social_launch_context import SocialLaunchPlatform
from database.models.social_launch_proposal import SocialLaunchProposalStatus
from database.session import async_session_factory
from integrations.llm_gateway.boot import AIIntegrationLayer, assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from services.business_context_roles import is_command_allowed
from services.social_launch_command_parser import (
    SocialLaunchParseError,
    extraction_to_structure,
    parse_launch_command,
)
from services.social_launch_context_service import get_current_context
from services.social_launch_proposal_service import cancel_proposal, confirm_proposal, create_proposal, get_proposal

logger = logging.getLogger(__name__)

router = Router(name="launch")

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "prompts"
_ai_layer: AIIntegrationLayer | None = None
_prompt_repository: FilePromptRepository | None = None
_ai_layer_lock = asyncio.Lock()

_PLATFORM_ARGS = {"telegram": SocialLaunchPlatform.TELEGRAM, "instagram": SocialLaunchPlatform.INSTAGRAM}
_PLATFORM_LABEL = {SocialLaunchPlatform.TELEGRAM: "Telegram", SocialLaunchPlatform.INSTAGRAM: "Instagram"}


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
    await message.answer("🥷 Команда /launch работает только в General теме внутреннего чата NINJA Newsroom.")


async def _fail_no_permission(message: Message) -> None:
    await message.answer("🥷 У вас нет доступа к команде /launch.")


async def _fail_not_founder(message: Message) -> None:
    await message.answer("🥷 Настраивать launch context может только FOUNDER. Посмотреть статус: /launch")


async def _fail_disabled(message: Message) -> None:
    await message.answer("🥷 Launch context пока отключён.")


def _split_platform_and_instruction(args: str) -> tuple[SocialLaunchPlatform, str] | None:
    parts = args.strip().split(maxsplit=1)
    if not parts:
        return None
    platform = _PLATFORM_ARGS.get(parts[0].lower())
    if platform is None:
        return None
    return platform, (parts[1] if len(parts) > 1 else "")


@router.message(Command("launch"))
async def handle_launch(message: Message, command: CommandObject) -> None:
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, "launch"):
        await _fail_no_permission(message)
        return
    if not settings.social_launch_context_enabled:
        await _fail_disabled(message)
        return

    if not command.args or not command.args.strip():
        async with async_session_factory() as session:
            telegram_ctx = await get_current_context(session, SocialLaunchPlatform.TELEGRAM)
            instagram_ctx = await get_current_context(session, SocialLaunchPlatform.INSTAGRAM)
        text = (
            render_launch_context("Telegram", telegram_ctx) + "\n\n" + render_launch_context("Instagram", instagram_ctx)
        )
        await message.answer(text)
        return

    # Anything past this point is an attempted MUTATION - FOUNDER tier only, via /launch's own
    # canonical permission (spec §3, PRELAUNCH-1A) - never the "directive" proxy.
    if not is_command_allowed(user_id, "launch_mutate"):
        await _fail_not_founder(message)
        return

    parsed_args = _split_platform_and_instruction(command.args)
    if parsed_args is None:
        await message.answer("🥷 Укажите платформу: /launch telegram <инструкция> или /launch instagram <инструкция>.")
        return
    platform, instruction = parsed_args
    if not instruction.strip():
        async with async_session_factory() as session:
            context = await get_current_context(session, platform)
        await message.answer(render_launch_context(_PLATFORM_LABEL[platform], context))
        return

    ai_layer, prompt_repository = await _get_ai_layer()
    async with async_session_factory() as session:
        previous = await get_current_context(session, platform)
    previous_structure = previous.confirmed_structure if previous is not None else None

    try:
        extraction = await parse_launch_command(
            ai_layer.gateway, prompt_repository, raw_text=instruction, platform=platform.value,
            previous_structure=previous_structure,
        )
    except SocialLaunchParseError:
        logger.exception("social_launch_parse_failed")
        await message.answer("Не удалось разобрать сообщение. Попробуйте переформулировать.")
        return

    if extraction.clarification_needed:
        await message.answer("🥷 Нужны уточнения: " + "; ".join(extraction.clarification_needed))
        return

    structure = extraction_to_structure(extraction)
    async with async_session_factory() as session:
        proposal = await create_proposal(
            session, platform=platform, raw_instruction=instruction, parsed_structure=structure,
            created_by=user_id, telegram_chat_id=message.chat.id, telegram_topic_id=message.message_thread_id,
        )
        logger.info("social_launch_proposal_created", extra={"proposal_id": str(proposal.id), "platform": platform.value})

    preview = render_launch_proposal_preview(proposal)
    keyboard = build_proposal_keyboard(proposal)
    sent = await message.answer(preview, reply_markup=keyboard)

    async with async_session_factory() as session:
        refreshed = await get_proposal(session, proposal.id)
        if refreshed is not None:
            refreshed.telegram_message_id = sent.message_id
            await session.commit()


@router.callback_query(F.data.startswith("launch:"))
async def handle_launch_callback(callback: CallbackQuery) -> None:
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
    if not is_command_allowed(user_id, "launch_mutate"):
        await callback.answer("Только FOUNDER может подтвердить launch context.", show_alert=True)
        return

    async with async_session_factory() as session:
        proposal = await get_proposal(session, proposal_id)
        if proposal is None:
            await callback.answer("Предложение не найдено.", show_alert=True)
            return
        if proposal.status != SocialLaunchProposalStatus.PENDING:
            await callback.answer("Уже обработано.", show_alert=True)
            return

        if action == "confirm":
            proposal = await confirm_proposal(session, proposal_id, decided_by=user_id)
            ack = "Подтверждено"
            logger.info("social_launch_context_updated", extra={"proposal_id": str(proposal_id)})
        elif action == "cancel":
            proposal = await cancel_proposal(session, proposal_id, decided_by=user_id)
            ack = "Отменено"
        else:  # "edit"
            await callback.answer(
                "Отправьте команду заново с исправленным текстом - это создаст новое предложение.", show_alert=True,
            )
            return

    assert proposal is not None
    new_text = render_launch_proposal_preview(proposal) + f"\n\n{ack}."
    try:
        await message.edit_text(new_text, reply_markup=build_proposal_keyboard(proposal))
    except Exception:  # noqa: BLE001 - best-effort re-render, the decision itself already persisted
        logger.exception("social_launch_proposal_rerender_failed", extra={"proposal_id": str(proposal_id)})
    await callback.answer(ack)
