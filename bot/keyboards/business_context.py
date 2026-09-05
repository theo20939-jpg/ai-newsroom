"""NINJA Social Intelligence Foundation, Part II §34: proposal confirm/edit/cancel keyboard.
Mirrors bot/keyboards/event_recap_review.py's own encode/parse callback_data convention exactly -
callback_data is untrusted transport, `parse_callback_data()` never raises."""
from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.business_context_proposal import BusinessContextProposal, BusinessContextProposalStatus

_PREFIX = "bizctx"
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


def build_proposal_keyboard(proposal: BusinessContextProposal) -> InlineKeyboardMarkup | None:
    """`None` once the proposal is no longer PENDING - the keyboard disappears on final decision,
    mirroring build_..._keyboard()'s own established convention for every review-style row."""
    if proposal.status != BusinessContextProposalStatus.PENDING:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=encode_callback_data("confirm", proposal.id)),
        InlineKeyboardButton(text="✏️ Исправить", callback_data=encode_callback_data("edit", proposal.id)),
        InlineKeyboardButton(text="❌ Отмена", callback_data=encode_callback_data("cancel", proposal.id)),
    ]])
