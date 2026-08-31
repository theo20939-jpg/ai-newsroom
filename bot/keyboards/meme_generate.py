"""MEME PRODUCTION PIPELINE (overnight phase): inline-keyboard button + callback_data codec for
the manual "😂 Сгенерировать мем" NEWS button. Pure - no database access, no aiogram Bot call,
mirrors `bot/keyboards/telegraph_article_review.py`'s exact shape.

Bound to the canonical `NewsEvent.id` only - never inferred from visible headline text (MEME
PRODUCTION PIPELINE §2's own explicit requirement). A distinct prefix ("memegen") from every
other callback namespace in this codebase - never reused, so a stale button from an unrelated
flow can never be misrouted here.
"""
from __future__ import annotations

from uuid import UUID

from aiogram.types import InlineKeyboardButton

_PREFIX = "memegen"

MEME_GENERATE_BUTTON_LABEL = "😂 Сгенерировать мем"


def encode_callback_data(news_event_id: UUID) -> str:
    """`memegen:<news_event_id>` - well within Telegram's 64-byte callback_data limit (fixed
    8-byte prefix + a 36-character UUID, ~45 bytes worst case)."""
    return f"{_PREFIX}:{news_event_id}"


def parse_callback_data(data: str) -> UUID | None:
    """Returns the `news_event_id`, or `None` if `data` is not a well-formed memegen callback -
    callback_data is user-controllable transport, a stale/replayed/malformed payload must never
    raise or be trusted blindly (mirrors every other callback codec in this codebase)."""
    parts = data.split(":")
    if len(parts) != 2 or parts[0] != _PREFIX:
        return None
    try:
        return UUID(parts[1])
    except ValueError:
        return None


def build_meme_generate_button(news_event_id: UUID) -> InlineKeyboardButton:
    """A single button, meant to be appended as its own row alongside an existing NEWS keyboard
    (`append_meme_generate_button()` below) - never assumed to be the only button on the
    message."""
    return InlineKeyboardButton(text=MEME_GENERATE_BUTTON_LABEL, callback_data=encode_callback_data(news_event_id))


def append_meme_generate_button(keyboard, news_event_id: UUID):
    """Appends the meme-generate button as a NEW row onto an existing keyboard (or builds a
    fresh one-row keyboard if `keyboard` is `None`, e.g. a NEWS send path with no Source button at
    all) - never mutates or replaces any existing row (the Source button, wherever present, stays
    exactly as it was). Purely additive: every existing call site of `build_source_only_keyboard()`
    /`build_source_and_cta_keyboard()` stays completely unmodified; this only wraps their result.
    """
    from aiogram.types import InlineKeyboardMarkup

    button = build_meme_generate_button(news_event_id)
    if keyboard is None:
        return InlineKeyboardMarkup(inline_keyboard=[[button]])
    return InlineKeyboardMarkup(inline_keyboard=[*keyboard.inline_keyboard, [button]])
