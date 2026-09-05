"""NINJA Social Intelligence Foundation, Part II: the General-topic Business Context Command
Center. Router registration mirrors bot/handlers/event_recap_review.py's own shape - one Router,
one `_is_authorized_*` gate re-checked on every message/callback, fresh state re-queried from the
DB every time, never cached from an earlier render.

Two-factor gate (spec §30): chat_id AND topic. `newsroom_telegram_chat_id`/
`business_context_topic_id` (core/config.py) - a message outside this exact chat+topic pair fails
safely with a clear message; it is never silently ignored (spec §30's own "fail safely with a
clear message" requirement) NOR treated as a command in the wrong place.

AI Gateway wiring note: `bot/main.py` (this bot's own entrypoint) assembles no AI integration
layer today - only worker/content_main.py and worker/analysis_main.py do. This module lazily
constructs its own, on first use, guarded by an asyncio.Lock - a genuinely new operational
dependency this phase introduces for the telegram_bot process specifically (documented here, and
in the phase's own final report), not a change to any existing worker's own assembly."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from core.config import settings
from database.models.business_context_proposal import BusinessContextCommandType, BusinessContextProposalStatus
from database.session import async_session_factory
from bot.business_context_formatting import (
    render_help,
    render_help_detail,
    render_product_detail,
    render_proposal_preview,
    render_status,
)
from bot.keyboards.business_context import build_proposal_keyboard, parse_callback_data
from integrations.llm_gateway.boot import AIIntegrationLayer, assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from services.business_context_command_parser import build_change_set, parse_business_context_command
from services.business_context_command_registry import get_command
from services.business_context_proposal_service import cancel_proposal, confirm_proposal, create_proposal, get_proposal
from services.business_context_roles import commands_for_role, get_role_for_user, is_command_allowed
from services.business_context_snapshot_service import get_business_context_snapshot

logger = logging.getLogger(__name__)

router = Router(name="business_context")

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent.parent / "prompts"
_ai_layer: AIIntegrationLayer | None = None
_prompt_repository: FilePromptRepository | None = None
_ai_layer_lock = asyncio.Lock()

_COMMAND_TO_TYPE = {
    "product": BusinessContextCommandType.PRODUCT,
    "campaign": BusinessContextCommandType.CAMPAIGN,
    "milestone": BusinessContextCommandType.MILESTONE,
    "directive": BusinessContextCommandType.DIRECTIVE,
    "claim": BusinessContextCommandType.CLAIM,
    "context": BusinessContextCommandType.CONTEXT,
}


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
    # `business_context_topic_id` is None by default, meaning "the real General topic" (which
    # itself carries no message_thread_id at all - see core/config.py's own comment). An operator
    # override to a specific numbered topic is still honored if ever set.
    expected_topic = settings.business_context_topic_id
    return message.message_thread_id == expected_topic


async def _fail_wrong_location(message: Message) -> None:
    await message.answer(
        "🥷 Business Context команды работают только в General теме внутреннего чата NINJA "
        "Newsroom."
    )


async def _fail_no_permission(message: Message, command: str) -> None:
    await message.answer(f"🥷 У вас нет доступа к команде /{command}.")


@router.message(Command("status"))
async def handle_status(message: Message, command: CommandObject) -> None:
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, "status"):
        await _fail_no_permission(message, "status")
        return

    async with async_session_factory() as session:
        snapshot = await get_business_context_snapshot(session, now=datetime.now(timezone.utc))

    if command.args:
        slug = command.args.strip().lower()
        detail = render_product_detail(snapshot, slug)
        await message.answer(detail or f"Продукт с идентификатором \"{slug}\" не найден.")
        return
    await message.answer(render_status(snapshot))


@router.message(Command("help"))
async def handle_help(message: Message, command: CommandObject) -> None:
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return
    user_id = message.from_user.id if message.from_user else None
    role = get_role_for_user(user_id) if user_id is not None else None
    if role is None:
        await _fail_no_permission(message, "help")
        return
    allowed_names = commands_for_role(role)

    if command.args:
        target = get_command(command.args.strip().lower())
        if target is None or target.name not in allowed_names:
            await message.answer(f"Команда /{command.args.strip()} недоступна.")
            return
        await message.answer(render_help_detail(target))
        return
    await message.answer(render_help(role, allowed_names))


async def _handle_mutation_command(message: Message, command: CommandObject, command_name: str) -> None:
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, command_name):
        await _fail_no_permission(message, command_name)
        return
    if not command.args or not command.args.strip():
        await message.answer(
            f"Напишите обычным текстом после /{command_name}, что изменилось - см. /help {command_name}."
        )
        return

    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        snapshot = await get_business_context_snapshot(session, now=now)
        context_summary = "\n".join(
            f"- {s.product.slug}: {s.product.name} ({s.product.status.value})" for s in snapshot.products
        ) or "(нет продуктов в системе)"

        ai_layer, prompt_repository = await _get_ai_layer()
        try:
            extraction = await parse_business_context_command(
                ai_layer.gateway, prompt_repository, raw_text=command.args,
                context_summary_text=context_summary, now=now,
            )
        except Exception:
            logger.exception("business_context_parse_failed", extra={"command": command_name})
            await message.answer("Не удалось разобрать сообщение. Попробуйте переформулировать.")
            return

        change_set = build_change_set(extraction)
        if not change_set:
            clarification = "; ".join(extraction.clarification_needed) or "не удалось найти конкретные изменения."
            await message.answer(f"🥷 Ничего не изменено: {clarification}")
            return

        proposal = await create_proposal(
            session, command_type=_COMMAND_TO_TYPE[command_name], raw_instruction=command.args,
            proposed_change_set=change_set, created_by=user_id,
            parsed_structure={
                "products_mentioned": extraction.products_mentioned,
                "campaign_updates": extraction.campaign_updates,
                "milestones": extraction.milestones,
                "directives": extraction.directives,
                "claims": extraction.claims,
            },
            telegram_chat_id=message.chat.id, telegram_topic_id=message.message_thread_id,
        )

    preview = render_proposal_preview(proposal)
    keyboard = build_proposal_keyboard(proposal)
    sent = await message.answer(preview, reply_markup=keyboard)

    async with async_session_factory() as session:
        refreshed_proposal = await get_proposal(session, proposal.id)
        if refreshed_proposal is not None:
            refreshed_proposal.telegram_message_id = sent.message_id
            await session.commit()


@router.message(Command("product"))
async def handle_product(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "product")


@router.message(Command("campaign"))
async def handle_campaign(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "campaign")


@router.message(Command("milestone"))
async def handle_milestone(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "milestone")


@router.message(Command("directive"))
async def handle_directive(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "directive")


@router.message(Command("claim"))
async def handle_claim(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "claim")


@router.message(Command("context"))
async def handle_context(message: Message, command: CommandObject) -> None:
    await _handle_mutation_command(message, command, "context")


@router.callback_query(F.data.startswith("bizctx:"))
async def handle_proposal_callback(callback: CallbackQuery) -> None:
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
    async with async_session_factory() as session:
        proposal = await get_proposal(session, proposal_id)
        if proposal is None:
            await callback.answer("Предложение не найдено.", show_alert=True)
            return
        if proposal.created_by != user_id and not is_command_allowed(user_id, "directive"):
            # Only the original author, or a FOUNDER-tier user, may confirm/cancel someone else's
            # proposal (spec §34's own "only the original authorized user or sufficiently
            # privileged role" requirement) - reusing the "directive"-allowed check as the
            # narrowest available proxy for "FOUNDER tier" in this phase's own role matrix.
            await callback.answer("Только автор может подтвердить это изменение.", show_alert=True)
            return

        if proposal.status != BusinessContextProposalStatus.PENDING:
            await callback.answer("Уже обработано.", show_alert=True)
            return

        if action == "confirm":
            proposal = await confirm_proposal(session, proposal_id, decided_by=user_id)
            ack = "Подтверждено"
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
    new_text = render_proposal_preview(proposal) + f"\n\n{ack}."
    try:
        await message.edit_text(new_text, reply_markup=build_proposal_keyboard(proposal))
    except Exception:  # noqa: BLE001 - best-effort re-render, the decision itself already persisted
        logger.exception("business_context_proposal_rerender_failed", extra={"proposal_id": str(proposal_id)})
    await callback.answer(ack)
