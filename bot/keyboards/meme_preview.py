"""Phase 18 M8: inline keyboard + callback_data codec for the Telegram Meme Editorial Preview
(docs/phase18_m8_telegram_editorial_preview_report.md). Pure - no database access, no aiogram
Bot call, only `aiogram.types.InlineKeyboardMarkup`/`InlineKeyboardButton` construction (testable
without a live Bot or dispatcher) - mirrors `bot/keyboards/image_preview.py`'s exact shape.

All state a callback needs (which candidate, which action) is carried entirely inside
`callback_data` itself - no new state table/Redis mechanism, same discipline
`bot/keyboards/image_preview.py` already established.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

_PREFIX = "memeprev"

_ACTIONS = ("approve", "reject", "regen_concept", "regen_image", "regen_text", "fallback")

# MEME PRODUCTION PIPELINE: RU label, matching the exact "🔗 Источник" text used throughout this
# phase's other buttons (NEWS keyboard, spec's own preferred MEMES delivery keyboard) - was
# "🔗 Open source" (EN) prior to this phase.
_SOURCE_BUTTON_LABEL = "🔗 Источник"


def encode_callback_data(action: str, candidate_id: UUID) -> str:
    """`memeprev:<action>:<candidate_id>` - well within Telegram's 64-byte callback_data limit."""
    return f"{_PREFIX}:{action}:{candidate_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, candidate_id)`, or `None` if `data` is not a well-formed memeprev
    callback - callback_data is user-controllable transport, a stale/replayed/malformed payload
    must never raise or be trusted blindly (mirrors `bot/keyboards/image_preview.py`'s identical
    parsing discipline)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    action, candidate_id_raw = parts[1], parts[2]
    if action not in _ACTIONS:
        return None
    try:
        candidate_id = UUID(candidate_id_raw)
    except ValueError:
        return None
    return action, candidate_id


def build_meme_preview_keyboard(candidate_id: UUID, *, source_url: str | None = None) -> InlineKeyboardMarkup:
    """Every button is always present (unlike `build_image_preview_keyboard`'s Previous/Next,
    which depend on position in a list) - a meme preview is always exactly one candidate, no
    pagination state to reflect."""
    # MEME-PROD-2.1: RU labels, matching this module's own already-localized `_SOURCE_BUTTON_LABEL`
    # ("🔗 Источник") - callback_data (action string) is untouched, so `parse_callback_data()` and
    # every existing handler dispatch keeps working unmodified; only the visible button text changes.
    rows = [
        [
            InlineKeyboardButton(text="✅ Одобрить", callback_data=encode_callback_data("approve", candidate_id)),
            InlineKeyboardButton(text="❌ Отклонить", callback_data=encode_callback_data("reject", candidate_id)),
        ],
        [
            InlineKeyboardButton(
                text="🔄 Концепция", callback_data=encode_callback_data("regen_concept", candidate_id)
            ),
            InlineKeyboardButton(
                text="🔄 Изображение", callback_data=encode_callback_data("regen_image", candidate_id)
            ),
            InlineKeyboardButton(
                text="🔄 Текст", callback_data=encode_callback_data("regen_text", candidate_id)
            ),
        ],
        [
            InlineKeyboardButton(
                text="📰 В обычную новость", callback_data=encode_callback_data("fallback", candidate_id)
            ),
        ],
    ]
    if source_url:
        rows.append([InlineKeyboardButton(text=_SOURCE_BUTTON_LABEL, url=source_url)])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_decided_keyboard(source_url: str | None) -> InlineKeyboardMarkup | None:
    """Terminal state once a decision has been made - only a source link remains useful, mirrors
    `bot/keyboards/image_preview.py::build_source_only_keyboard()`'s identical convention."""
    if not source_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=_SOURCE_BUTTON_LABEL, url=source_url)]])
