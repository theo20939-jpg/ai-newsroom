"""Phase 16 M6: inline keyboard + callback_data codec for the Telegram Editorial Preview (docs/
phase16_m6_telegram_editorial_preview_report.md §6). Pure - no database access, no aiogram Bot
call, only `aiogram.types.InlineKeyboardMarkup`/`InlineKeyboardButton` construction (testable
without a live Bot or dispatcher).

No new state table/Redis mechanism (Contract §5's own "prefer existing JSON/state mechanisms")
- all state a callback needs (which draft, which candidate index) is carried entirely inside
`callback_data` itself; `bot/handlers/image_preview.py` re-queries
`services.image_persistence.get_editorial_image_candidates()` fresh on every callback, so the
current candidate list is never trusted from a possibly-stale earlier render.
"""
from uuid import UUID

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from services.image_persistence import EditorialImageCandidate

_PREFIX = "imgprev"


def encode_callback_data(action: str, content_draft_id: UUID, index: int) -> str:
    """`imgprev:<action>:<content_draft_id>:<index>` - well within Telegram's 64-byte
    callback_data limit (fixed 8-byte prefix + a short action word + a 36-character UUID + a
    small integer, ~50 bytes total worst case)."""
    return f"{_PREFIX}:{action}:{content_draft_id}:{index}"


def parse_callback_data(data: str) -> tuple[str, UUID, int] | None:
    """Returns `(action, content_draft_id, index)`, or `None` if `data` is not a well-formed
    imgprev callback - callback_data is user-controllable transport (Telegram guarantees only that
    it echoes back exactly what this bot itself sent, but a stale/replayed/malformed payload must
    never raise or be trusted blindly, docs §9)."""
    parts = data.split(":")
    if len(parts) != 4 or parts[0] != _PREFIX:
        return None
    action, draft_id_raw, index_raw = parts[1], parts[2], parts[3]
    if action not in ("prev", "next", "use", "none"):
        return None
    try:
        content_draft_id = UUID(draft_id_raw)
        index = int(index_raw)
    except ValueError:
        return None
    if index < 0:
        return None
    return action, content_draft_id, index


def build_image_preview_keyboard(
    *, content_draft_id: UUID, index: int, total: int, candidate: EditorialImageCandidate,
) -> InlineKeyboardMarkup:
    """Navigation row omits Previous at index 0 and Next at the last index (rather than disabling
    an unusable button - Telegram inline keyboards have no native disabled state); the "Use
    image"/"No image" row is always present; "Open source" is a `url=` button (Telegram resolves
    it directly - no callback round-trip, no server-side handling, never exposes anything beyond
    the article URL the operator could already see in the preview text itself)."""
    nav_row: list[InlineKeyboardButton] = []
    if index > 0:
        nav_row.append(
            InlineKeyboardButton(text="⬅️ Previous", callback_data=encode_callback_data("prev", content_draft_id, index - 1))
        )
    if index < total - 1:
        nav_row.append(
            InlineKeyboardButton(text="➡️ Next", callback_data=encode_callback_data("next", content_draft_id, index + 1))
        )

    decision_row = [
        InlineKeyboardButton(text="✅ Use image", callback_data=encode_callback_data("use", content_draft_id, index)),
        InlineKeyboardButton(text="🚫 No image", callback_data=encode_callback_data("none", content_draft_id, index)),
    ]

    rows = []
    if nav_row:
        rows.append(nav_row)
    rows.append(decision_row)

    source_url = candidate.article_url or candidate.source_url
    if source_url:
        rows.append([InlineKeyboardButton(text="🔗 Open source", url=source_url)])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def build_source_only_keyboard(
    source_url: str | None, *, label: str = "🔗 Open source",
) -> InlineKeyboardMarkup | None:
    """Phase 16 UX fix (docs/phase16_ux_combined_preview_fix_report.md §5): the terminal state for
    every combined-preview message - no candidates at all, "No image" was chosen, or "Use image"
    was chosen (only a single source-of-truth link remains useful once the interactive
    Previous/Next/Use/No-image controls are no longer meaningful). Returns `None` (never an empty
    `InlineKeyboardMarkup`) when there is no URL at all, so the caller can pass it straight through
    as `reply_markup=` and Telegram simply shows no keyboard.

    `label` (Phase 23.1E, additive, default unchanged): every pre-existing caller (`services/
    image_preview_notifier.py`) keeps its own "🔗 Open source" label byte-for-byte, since none of
    them supply this kwarg. `worker/content_cycle.py`'s NEWS presentation profile is the one new
    caller that passes `label="🔗 Источник"`, matching the Russian-language editorial card it
    accompanies - this is a pure export/reuse of the existing Phase 16 keyboard, not a competing
    implementation (docs/phase23_1e_telegram_news_compact_profile_report.md §10)."""
    if not source_url:
        return None
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=label, url=source_url)]])


# PRESENTATION RECOVERY (2026-09-02): canonical NEWS-family editorial-send keyboard authority -
# the single builder every real production send (NEWS/BREAKING/DATA/QUOTE/RECAP) must use. A prior
# implementation (build_source_and_cta_keyboard(), removed here) always attached a subscribe
# button ("NINJA PULSE. Подписаться 🥷" -> https://t.me/nnjvpn) and was reached only for non-NEWS
# presentation types, silently losing the meme button in the same step - the exact root cause of
# both the observed unwanted-subscribe-button and missing-meme-button production symptoms. This
# function is a pure composition of the two already-correct, already-tested primitives below - no
# new keyboard logic, no new risk surface - so every content type gets byte-identical source+meme
# behavior. Never include a subscribe/channel CTA as a keyboard button here (docs: the CTA, if
# used, is a caption-text link only - services/news_telegram_presentation.py's own
# build_ninja_pulse_footer_html() - never a button, never both).
def build_editorial_send_keyboard(
    source_url: str | None, news_event_id: UUID, *, label: str = "🔗 Open source",
) -> InlineKeyboardMarkup | None:
    """Case 1 (source + meme): both buttons. Case 2 (no source): meme-only, one fresh row. Case 3
    (meme disallowed - caller simply omits calling this / uses build_source_only_keyboard directly)
    is intentionally out of this function's scope; callers that must disallow meme generation for a
    given type should call `build_source_only_keyboard()` directly instead - this function always
    appends the meme button when called, by design, mirroring `append_meme_generate_button()`'s own
    "purely additive" contract."""
    from bot.keyboards.meme_generate import append_meme_generate_button

    return append_meme_generate_button(build_source_only_keyboard(source_url, label=label), news_event_id)
