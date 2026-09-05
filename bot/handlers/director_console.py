"""SOCIAL-INTELLIGENCE-INTEGRATION-1: the NINJA Director Console - `/directors`, `/plan`,
`/opportunities`, `/calendar`, `/performance`, all inside the same internal General topic Business
Context lives in. Router registration mirrors bot/handlers/business_context.py's own shape - one
Router, the SAME two-factor chat_id+topic gate (duplicated here per this codebase's established
"small adapter-local helpers are duplicated, not cross-coupled" convention -
services/telegram_performance_collection.py's own docstring states this explicitly), fresh state
re-queried from the DB every time.

CRITICAL (spec §28/§29): gated by `settings.director_console_enabled` (default False) ON TOP OF
the existing role/command gate - console commands are additionally off by default even for an
otherwise-permitted role. Every handler below is READ-ONLY: it authorizes, parses the optional
platform filter, calls a DirectorConsoleService/DirectorStatusService function, renders the pure
result, and sends it - NO service call here ever writes to a table, calls the AI Gateway, or
touches a platform API (spec §13/§18/§29)."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from bot.director_console_formatting import (
    render_calendar,
    render_directors_status,
    render_opportunities,
    render_performance,
    render_plan,
)
from core.config import settings
from database.session import async_session_factory
from services.business_context_roles import BusinessContextRole, get_role_for_user, is_command_allowed
from services.director_console_service import (
    build_calendar_view,
    build_opportunities_view,
    build_performance_view,
    build_plan_view,
)
from services.director_status_service import get_director_console_status

logger = logging.getLogger(__name__)

router = Router(name="director_console")

_VALID_PLATFORM_FILTERS = {"telegram", "instagram"}
_TELEGRAM_MESSAGE_LIMIT = 4000


def _is_authorized_chat_and_topic(message: Message) -> bool:
    if settings.newsroom_telegram_chat_id is None:
        return False
    if message.chat.id != settings.newsroom_telegram_chat_id:
        return False
    expected_topic = settings.business_context_topic_id
    return message.message_thread_id == expected_topic


async def _fail_wrong_location(message: Message) -> None:
    await message.answer(
        "🥷 Команды Director Console работают только в General теме внутреннего чата NINJA Newsroom."
    )


async def _fail_no_permission(message: Message, command: str) -> None:
    await message.answer(f"🥷 У вас нет доступа к команде /{command}.")


async def _fail_console_disabled(message: Message) -> None:
    await message.answer("🥷 Director Console пока отключена.")


def _parse_platform_filter(command: CommandObject) -> tuple[str | None, str | None]:
    """Returns (platform, error_message) - spec §24's own "no complex DSL" instruction: exactly
    one optional bare word, "telegram" or "instagram", nothing else."""
    if not command.args or not command.args.strip():
        return None, None
    raw = command.args.strip().lower()
    if raw not in _VALID_PLATFORM_FILTERS:
        return None, f"Неизвестный фильтр \"{raw}\". Используйте: telegram или instagram."
    return raw, None


async def _send_possibly_long(message: Message, text: str) -> None:
    """Spec §23: paginate rather than send one giant message - a plain length-based split, never
    truncating mid-sentence silently without indicating more content follows."""
    if len(text) <= _TELEGRAM_MESSAGE_LIMIT:
        await message.answer(text)
        return
    remaining = text
    while remaining:
        chunk, remaining = remaining[:_TELEGRAM_MESSAGE_LIMIT], remaining[_TELEGRAM_MESSAGE_LIMIT:]
        await message.answer(chunk)


async def _authorize(message: Message, command_name: str) -> BusinessContextRole | None:
    """Returns the caller's resolved role on success (never None on success - a permitted command
    always has a real role behind it), or None on any failure (already answered to the user).
    Callers thread this role straight into their renderer so DirectorConsoleAccessPolicy (spec
    §54) always sees who is actually asking, never a second, separately-resolved role."""
    if not _is_authorized_chat_and_topic(message):
        await _fail_wrong_location(message)
        return None
    if not settings.director_console_enabled:
        await _fail_console_disabled(message)
        return None
    user_id = message.from_user.id if message.from_user else None
    if user_id is None or not is_command_allowed(user_id, command_name):
        await _fail_no_permission(message, command_name)
        return None
    role = get_role_for_user(user_id)
    assert role is not None  # is_command_allowed() already required a real role
    return role


@router.message(Command("directors"))
async def handle_directors(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "directors")
    if role is None:
        return
    async with async_session_factory() as session:
        status = await get_director_console_status(session, now=datetime.now(timezone.utc))
    await _send_possibly_long(message, render_directors_status(status, role=role))


@router.message(Command("plan"))
async def handle_plan(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "plan")
    if role is None:
        return
    platform, error = _parse_platform_filter(command)
    if error:
        await message.answer(error)
        return
    async with async_session_factory() as session:
        view = await build_plan_view(session, now=datetime.now(timezone.utc), platform=platform)
    await _send_possibly_long(message, render_plan(view, role=role, platform=platform))


@router.message(Command("opportunities"))
async def handle_opportunities(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "opportunities")
    if role is None:
        return
    platform, error = _parse_platform_filter(command)
    if error:
        await message.answer(error)
        return
    async with async_session_factory() as session:
        view = await build_opportunities_view(session, now=datetime.now(timezone.utc), platform=platform)
    await _send_possibly_long(message, render_opportunities(view, role=role, platform=platform))


@router.message(Command("calendar"))
async def handle_calendar(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "calendar")
    if role is None:
        return
    platform, error = _parse_platform_filter(command)
    if error:
        await message.answer(error)
        return
    async with async_session_factory() as session:
        view = await build_calendar_view(session, now=datetime.now(timezone.utc), platform=platform)
    await _send_possibly_long(message, render_calendar(view, role=role, platform=platform))


@router.message(Command("performance"))
async def handle_performance(message: Message, command: CommandObject) -> None:
    role = await _authorize(message, "performance")
    if role is None:
        return
    platform, error = _parse_platform_filter(command)
    if error:
        await message.answer(error)
        return
    async with async_session_factory() as session:
        view = await build_performance_view(session, now=datetime.now(timezone.utc), platform=platform)
    await _send_possibly_long(message, render_performance(view, role=role, platform=platform))
