"""TELEGRAPH Checkpoint 2: inline keyboard + callback_data codec for the shortlist review UI.
Mirrors `bot/keyboards/meme_preview.py`'s exact shape - pure, no database access, no aiogram Bot
call, only `InlineKeyboardMarkup`/`InlineKeyboardButton` construction (testable without a live
Bot or dispatcher).

All state a callback needs (which proposal, which action) is carried entirely inside
`callback_data` itself - no new state table/Redis mechanism, same discipline `bot/keyboards/
meme_preview.py` already established. The internal proposal UUID is never shown to the operator
in button TEXT (the phase brief's own explicit "do NOT expose internal UUIDs to the user") - only
the button's own `callback_data` carries it, which Telegram never displays.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from database.models.telegraph_shortlist import TelegraphProposalStatus, TelegraphTopicProposal

_PREFIX = "tgshort"
_ACTIONS = ("approve", "reject")


def encode_callback_data(action: str, proposal_id: UUID) -> str:
    """`tgshort:<action>:<proposal_id>` - well within Telegram's 64-byte callback_data limit
    (mirrors `bot/keyboards/meme_preview.py::encode_callback_data()`'s identical shape/margin)."""
    return f"{_PREFIX}:{action}:{proposal_id}"


def parse_callback_data(data: str) -> tuple[str, UUID] | None:
    """Returns `(action, proposal_id)`, or `None` if `data` is not a well-formed tgshort
    callback - callback_data is user-controllable transport, a stale/replayed/malformed payload
    must never raise or be trusted blindly (mirrors `bot/keyboards/meme_preview.py::
    parse_callback_data()`'s identical parsing discipline)."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    action, proposal_id_raw = parts[1], parts[2]
    if action not in _ACTIONS:
        return None
    try:
        proposal_id = UUID(proposal_id_raw)
    except ValueError:
        return None
    return action, proposal_id


def build_shortlist_keyboard(proposals: list[TelegraphTopicProposal]) -> InlineKeyboardMarkup | None:
    """One row of [✅ approve][❌ reject] per still-PENDING proposal, in the batch's own `rank`
    order - a decided proposal (approved/rejected) contributes no buttons at all (its outcome is
    already visible in the message text's own status line - bot/telegraph_shortlist_formatting.py
    ::render_shortlist_message_text()), mirroring `bot/keyboards/meme_preview.py::
    build_decided_keyboard()`'s own "terminal state, buttons shrink" convention, applied per-row
    instead of per-message since one shortlist message covers several independent decisions.

    Returns `None` once every proposal is decided - an empty `InlineKeyboardMarkup` is not a
    meaningful distinct state from "no keyboard at all" and aiogram/Telegram both accept `None`
    for "no keyboard" on `edit_message_text()`.
    """
    rows = [
        [
            InlineKeyboardButton(
                text=f"{p.rank} ✅", callback_data=encode_callback_data("approve", p.id),
            ),
            InlineKeyboardButton(
                text=f"{p.rank} ❌", callback_data=encode_callback_data("reject", p.id),
            ),
        ]
        for p in proposals
        if p.status == TelegraphProposalStatus.PENDING
    ]
    if not rows:
        return None
    return InlineKeyboardMarkup(inline_keyboard=rows)
