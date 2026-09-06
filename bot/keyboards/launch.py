"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §12: /launch proposal confirm/edit/cancel keyboard. Mirrors
bot/keyboards/telegram_surface.py's own encode/parse callback_data convention exactly."""
from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.social_launch_proposal import SocialLaunchProposal, SocialLaunchProposalStatus

_PREFIX = "launch"
_ACTIONS = ("confirm", "edit", "cancel")


def encode_callback_data(action: str, proposal_id: UUID) -> str:
    assert action in _ACTIONS, f"unknown action: {action!r}"
    return f"{_PREFIX}:{action}:{proposal_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX or parts[1] not in _ACTIONS:
        return None
    try:
        return parts[1], UUID(parts[2])
    except ValueError:
        return None


def build_proposal_keyboard(proposal: SocialLaunchProposal) -> InlineKeyboardMarkup | None:
    if proposal.status != SocialLaunchProposalStatus.PENDING:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=encode_callback_data("confirm", proposal.id)),
        InlineKeyboardButton(text="✏️ Исправить", callback_data=encode_callback_data("edit", proposal.id)),
        InlineKeyboardButton(text="❌ Отмена", callback_data=encode_callback_data("cancel", proposal.id)),
    ]])


_REFRESH_PREFIX = "directorsrefresh"


def encode_refresh_callback_data(action: str, target: str) -> str:
    """`target` is "telegram" / "instagram" / "all" - a plain string, not a DB id, since the
    refresh confirmation keyboard is built ad hoc from the /directors refresh command args, never
    from a persisted proposal row (spec §26's own example keyboard has no proposal to reference)."""
    assert action in ("confirm", "cancel")
    return f"{_REFRESH_PREFIX}:{action}:{target}"


def parse_refresh_callback_data(data: str) -> tuple[str, str] | None:
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _REFRESH_PREFIX or parts[1] not in ("confirm", "cancel"):
        return None
    return parts[1], parts[2]


def build_refresh_confirmation_keyboard(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Запустить", callback_data=encode_refresh_callback_data("confirm", target)),
        InlineKeyboardButton(text="❌ Отмена", callback_data=encode_refresh_callback_data("cancel", target)),
    ]])
