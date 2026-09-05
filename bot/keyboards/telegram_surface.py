"""SOCIAL-INTELLIGENCE-OPS-1, spec §4: /surface proposal confirm/edit/cancel keyboard. Mirrors
bot/keyboards/business_context.py's own encode/parse callback_data convention exactly."""
from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.telegram_surface_proposal import TelegramSurfaceProposal, TelegramSurfaceProposalStatus

_PREFIX = "tgsurface"
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


def build_proposal_keyboard(proposal: TelegramSurfaceProposal) -> InlineKeyboardMarkup | None:
    if proposal.status != TelegramSurfaceProposalStatus.PENDING:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=encode_callback_data("confirm", proposal.id)),
        InlineKeyboardButton(text="✏️ Исправить", callback_data=encode_callback_data("edit", proposal.id)),
        InlineKeyboardButton(text="❌ Отмена", callback_data=encode_callback_data("cancel", proposal.id)),
    ]])
