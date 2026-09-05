"""VISUAL-DESIGN-AUTONOMY-1/1A, spec §51-56/§21: /design - read status for every role with console
access, freeze/unfreeze/rollback/reconsider mutations for FOUNDER only via a confirm/cancel
keyboard (no raw prompt editing, spec §57's own explicit "no manual raw prompt edit command in v1"
instruction - "reconsider" only ever triggers the SAME bounded revision generator, it never accepts
replacement prompt text).

Mirrors bot/handlers/director_console.py's own shape exactly (same chat/topic gate, same
director_console_enabled flag, same role/command authorization) - opening /design never triggers
design generation and never calls the AI Gateway (spec §52's own explicit instruction). "reconsider"
still respects every existing gate (evidence/frozen/cooldown/budget) unchanged - a manual FOUNDER
request does not bypass visual_brief_auto_adaptation_enabled (spec §1A-6's own "or explicit
authorized manual request in future" - deferred, not implemented as a bypass this phase)."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, InaccessibleMessage, Message

from bot.keyboards.visual_design import build_confirm_keyboard, parse_callback_data
from bot.visual_design_formatting import render_design_scope_detail, render_design_status
from core.config import settings
from database.session import async_session_factory
from integrations.llm_gateway.boot import AIIntegrationLayer, assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from services.business_context_roles import BusinessContextRole, get_role_for_user, is_command_allowed
from services.visual_brief_revision_service import BriefRevisionStatus, request_brief_revision
from services.visual_design_console_service import build_design_scope_detail_view, build_design_view
from services.visual_designer_brief_service import find_rollback_candidate, freeze_brief, rollback_to, unfreeze_brief

logger = logging.getLogger(__name__)

router = Router(name="visual_design")

_MUTATION_ACTIONS = frozenset({"freeze", "unfreeze", "rollback", "reconsider"})

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


_RECONSIDER_RESULT_TEXT: dict[BriefRevisionStatus, str] = {
    BriefRevisionStatus.CANDIDATE_CREATED: "Кандидат брифа создан (v{version}). Не активирован автоматически.",
    BriefRevisionStatus.NOT_ELIGIBLE: "Пересмотр невозможен: {reason}",
    BriefRevisionStatus.BRIEF_FROZEN: "Scope заморожен - пересмотр недоступен.",
    BriefRevisionStatus.BUDGET_UNKNOWN: "Бюджет неизвестен - пересмотр не выполнен (fail-safe).",
    BriefRevisionStatus.BUDGET_EXHAUSTED: "Дневной бюджет исчерпан - пересмотр не выполнен.",
    BriefRevisionStatus.BRIEF_REVISION_UNAVAILABLE: "Генератор недоступен: {reason}",
    BriefRevisionStatus.REJECTED_BY_BRAND_CORE: "Кандидат отклонён (нарушение Brand Core): {reason}",
    BriefRevisionStatus.NO_BRIEF_YET: "Для этого scope ещё не создан Designer Brief.",
}


def _is_authorized_chat_and_topic(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    if message.chat.id != settings.newsroom_telegram_chat_id:
        return False
    return message.message_thread_id == settings.business_context_topic_id


async def _authorize(message: Message, command_name: str) -> BusinessContextRole | None:
    if not _is_authorized_chat_and_topic(message):
        await message.answer("🥷 Команды Director Console работают только в General теме внутреннего чата NINJA Newsroom.")
        return None
    if not settings.director_console_enabled:
        await message.answer("🥷 Director Console пока отключена.")
        return None
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, command_name):
        await message.answer(f"🥷 У вас нет доступа к команде /{command_name}.")
        return None
    role = get_role_for_user(user_id)
    assert role is not None
    return role


@router.message(Command("design"))
async def handle_design(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "design")
    if role is None:
        return

    args = (command.args or "").strip()
    now = datetime.now(timezone.utc)

    if not args:
        async with async_session_factory() as session:
            view = await build_design_view(session, now=now)
        await message.answer(render_design_status(view, role=role))
        return

    parts = args.split(maxsplit=1)
    first = parts[0].lower()

    if first in _MUTATION_ACTIONS:
        if len(parts) < 2 or not parts[1].strip():
            await message.answer(f"Использование: /design {first} <scope>")
            return
        scope = parts[1].strip().lower()
        user_id = message.from_user.id if message.from_user else None
        if user_id is None or not is_command_allowed(user_id, "directive"):
            await message.answer("🥷 Изменение визуального брифа доступно только FOUNDER.")
            return
        confirm_note = (
            " Это запустит генератор пересмотра брифа (реальный вызов AI Gateway, если evidence "
            "позволяет)." if first == "reconsider" else ""
        )
        await message.answer(
            f"Подтвердите действие: {first.upper()} для scope \"{scope}\".{confirm_note}",
            reply_markup=build_confirm_keyboard(first, scope),
        )
        return

    scope = first
    async with async_session_factory() as session:
        detail = await build_design_scope_detail_view(session, scope, now=now)
    if detail is None:
        await message.answer(f"Для scope \"{scope}\" ещё не создан Designer Brief.")
        return
    await message.answer(render_design_scope_detail(detail, role=role))


@router.callback_query(lambda c: c.data is not None and c.data.startswith("design:"))
async def handle_design_callback(callback: CallbackQuery) -> None:
    message = callback.message
    if callback.data is None or message is None or isinstance(message, InaccessibleMessage):
        await callback.answer()
        return
    parsed = parse_callback_data(callback.data)
    if parsed is None:
        await callback.answer()
        return
    action, scope = parsed

    if action == "cancel":
        await message.edit_text("Отменено.")
        await callback.answer()
        return

    user_id = callback.from_user.id if callback.from_user else None
    if user_id is None or not is_command_allowed(user_id, "directive"):
        await callback.answer("Нет прав.", show_alert=True)
        return

    async with async_session_factory() as session:
        try:
            if action == "freeze":
                await freeze_brief(session, scope, reason=f"frozen by user {user_id}")
                result_text = f"Scope \"{scope}\" заморожен."
            elif action == "unfreeze":
                await unfreeze_brief(session, scope, reason=f"unfrozen by user {user_id}")
                result_text = f"Scope \"{scope}\" разморожен."
            elif action == "rollback":
                candidate = await find_rollback_candidate(session, scope)
                if candidate is None:
                    result_text = f"Нет валидной версии для отката в scope \"{scope}\"."
                else:
                    await rollback_to(session, scope, target_version_id=candidate.id, reason=f"rolled back by user {user_id}")
                    result_text = f"Scope \"{scope}\" откачен на версию v{candidate.version}."
            else:  # reconsider
                ai_layer, prompt_repository = await _get_ai_layer()
                revision_result = await request_brief_revision(session, ai_layer.gateway, prompt_repository, scope=scope)
                template = _RECONSIDER_RESULT_TEXT.get(revision_result.status, "{reason}")
                version = revision_result.candidate.version if revision_result.candidate is not None else None
                result_text = template.format(reason=revision_result.reason, version=version)
        except ValueError as exc:
            result_text = f"Не удалось выполнить действие: {exc}"

    await message.edit_text(result_text)
    await callback.answer()
