"""Phase 18 M9: inline keyboard + callback_data codec for capturing a meme rejection reason
(docs/phase18_m9_human_feedback_report.md). Pure - mirrors `bot/keyboards/meme_preview.py`'s
exact shape (own prefix, own parser, no shared state beyond `candidate_id`).
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from schemas.meme_feedback import MemeRejectionReason

_PREFIX = "memereason"
_SKIP = "skip"

_LABELS: dict[MemeRejectionReason, str] = {
    MemeRejectionReason.NOT_FUNNY: "😐 Not funny",
    MemeRejectionReason.UNCLEAR: "❓ Unclear",
    MemeRejectionReason.FACTUAL_RISK: "⚠️ Factual risk",
    MemeRejectionReason.BAD_IMAGE: "🖼 Bad image",
    MemeRejectionReason.OFF_BRAND: "🚫 Off-brand",
    MemeRejectionReason.TOO_TOXIC: "☣️ Too toxic",
    MemeRejectionReason.STALE: "🕰 Stale",
    MemeRejectionReason.DUPLICATE_IDEA: "♻️ Duplicate idea",
}


def encode_reason_callback_data(reason: MemeRejectionReason | None, candidate_id: UUID) -> str:
    """`memereason:<reason-value-or-skip>:<candidate_id>`."""
    token = reason.value if reason is not None else _SKIP
    return f"{_PREFIX}:{token}:{candidate_id}"


def parse_reason_callback_data(data: str) -> tuple[MemeRejectionReason | None, UUID] | None:
    """Returns `(reason, candidate_id)` - `reason=None` means "skip, no reason given." `None`
    (the whole tuple) if `data` is not a well-formed memereason callback."""
    parts = data.split(":")
    if len(parts) != 3 or parts[0] != _PREFIX:
        return None
    token, candidate_id_raw = parts[1], parts[2]
    try:
        candidate_id = UUID(candidate_id_raw)
    except ValueError:
        return None
    if token == _SKIP:
        return None, candidate_id
    try:
        reason = MemeRejectionReason(token)
    except ValueError:
        return None
    return reason, candidate_id


def build_reject_reason_keyboard(candidate_id: UUID) -> InlineKeyboardMarkup:
    """One button per `MemeRejectionReason` (2 per row) plus a trailing "skip" row - a single-tap
    selection, not a multi-select-then-confirm flow (MVP simplicity, mirrors this phase's own
    "не устраивай бесконечную generation"/keep-it-simple discipline elsewhere)."""
    reasons = list(MemeRejectionReason)
    rows = [
        [
            InlineKeyboardButton(text=_LABELS[a], callback_data=encode_reason_callback_data(a, candidate_id)),
            InlineKeyboardButton(text=_LABELS[b], callback_data=encode_reason_callback_data(b, candidate_id)),
        ]
        for a, b in zip(reasons[::2], reasons[1::2])
    ]
    rows.append([
        InlineKeyboardButton(text="Skip (no reason)", callback_data=encode_reason_callback_data(None, candidate_id)),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
