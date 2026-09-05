"""VISUAL-DESIGN-AUTONOMY-1, spec §55: /design freeze/unfreeze/rollback confirm/cancel keyboard.
Mirrors bot/keyboards/telegram_surface.py's own encode/parse callback_data convention - scope is a
short plain string (no proposal row exists to key off of, unlike /surface's AI-parsed proposal),
so it is embedded directly in callback_data."""
from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_PREFIX = "design"
_ACTIONS = ("freeze", "unfreeze", "rollback", "cancel")


def encode_callback_data(action: str, scope: str) -> str:
    assert action in _ACTIONS, f"unknown action: {action!r}"
    return f"{_PREFIX}:{action}:{scope}"


def parse_callback_data(data: str) -> tuple[str, str] | None:
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != _PREFIX or parts[1] not in _ACTIONS:
        return None
    return parts[1], parts[2]


def build_confirm_keyboard(action: str, scope: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Подтвердить", callback_data=encode_callback_data(action, scope)),
        InlineKeyboardButton(text="❌ Отмена", callback_data="design:cancel:_"),
    ]])
