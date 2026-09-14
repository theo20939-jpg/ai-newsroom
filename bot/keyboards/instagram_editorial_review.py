"""INSTAGRAM-TELEGRAM-EDITORIAL-DELIVERY-1 §9/§14: inline keyboard + callback_data codec for the
Instagram editorial-review control message. Mirrors `bot/keyboards/telegraph_article_review.py`'s
exact shape (a distinct prefix - "igrev", never reused elsewhere - encoding `action:delivery_id:
version`; `version` is the stale-callback guard `services.instagram_editorial_delivery_state.
InstagramEditorialDeliveryService.is_actionable()` checks against the row's current version).

No "🚀 Опубликовать" action exists anywhere in this codec - by construction, no callback_data this
module can produce or parse is capable of triggering a publish (§9's own hard requirement)."""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_PREFIX = "igrev"
_ACTIONS = ("approve", "regen_full", "regen_text", "regen_visual")


def encode_callback_data(action: str, delivery_id: UUID, version: int) -> str:
    """`igrev:<action>:<delivery_id>:<version>` - well within Telegram's 64-byte limit for the
    short UUID hex + a one/two-digit version."""
    assert action in _ACTIONS
    return f"{_PREFIX}:{action}:{delivery_id}:{version}"


def parse_callback_data(data: str) -> tuple[str, UUID, int] | None:
    """Returns `(action, delivery_id, version)`, or `None` for anything malformed - callback_data
    is user-controllable transport, never trusted blindly."""
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != _PREFIX:
        return None
    action, delivery_id_raw, version_raw = parts[1], parts[2], parts[3]
    if action not in _ACTIONS:
        return None
    try:
        delivery_id = UUID(delivery_id_raw)
        version = int(version_raw)
    except ValueError:
        return None
    return action, delivery_id, version


def build_review_keyboard(delivery_id: UUID, version: int, *, source_url: str | None = None) -> InlineKeyboardMarkup:
    """One row of the four editorial actions, plus an OPTIONAL second row with a plain URL button
    (§14 "🔗 Источник") when a real source exists - never fabricated, `None` simply omits the row.
    Never includes any publish-capable button (§9)."""
    rows = [
        [
            InlineKeyboardButton(text="✅ Принять", callback_data=encode_callback_data("approve", delivery_id, version)),
            InlineKeyboardButton(text="🔄 Переделать", callback_data=encode_callback_data("regen_full", delivery_id, version)),
        ],
        [
            InlineKeyboardButton(text="📝 Текст", callback_data=encode_callback_data("regen_text", delivery_id, version)),
            InlineKeyboardButton(text="🎨 Визуал", callback_data=encode_callback_data("regen_visual", delivery_id, version)),
        ],
    ]
    if source_url:
        rows.append([InlineKeyboardButton(text="🔗 Источник", url=source_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)
