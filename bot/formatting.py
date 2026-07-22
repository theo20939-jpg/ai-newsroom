"""Phase 11 Telegram HTML card renderer (docs/
phase11_telegram_editorial_inbox_architecture_contract.md §12/§13/§14).

Pure functions - no aiogram/Bot/Message type appears anywhere in this module, so it is testable
with zero Telegram mocking.

The single most important invariant in this module: `telegram_utf16_length(rendered) <= SAFE_LIMIT`
is the sole authoritative Telegram-length safety check. Python's built-in `len()` MUST NOT be used
as that check (it counts Unicode code points, not the UTF-16 code units Telegram's own 4096-
character limit is measured in - `len("\U0001F4F0") == 1` but its real UTF-16 length is 2; the
card's own static newspaper emoji below is itself such a character, so this is not a theoretical
concern, it is triggered on every card).
"""
import html

from schemas.editorial_inbox import EditorialInboxCard

SAFE_LIMIT = 4096  # Telegram's own hard limit, in UTF-16 code units (Contract §14).

_TITLE_PLACEHOLDER = "(no title generated)"
_BODY_PLACEHOLDER = "(no body generated)"
_TRUNCATION_MARKER = "…"  # a single ellipsis character

# Fixed-step shrink (Contract §14 step 4 explicitly permits either a fixed step or a binary
# search - a fixed step is the simplest to test deterministically, per
# docs/phase11_telegram_editorial_inbox_implementation_plan.md §8).
_SHRINK_STEP = 200


class CardTooLongError(Exception):
    """Raised when a card cannot be rendered within SAFE_LIMIT even after draft_body is fully
    exhausted (Contract §14 terminal fallback -> §16 Case E, corrected per finding N-2)."""


def _telegram_utf16_length(text: str) -> int:
    """The frozen semantic invariant (Contract §14): the number of UTF-16 code units required to
    encode `text` - NOT Python's `len()`, which counts Unicode code points instead."""
    return len(text.encode("utf-16-le")) // 2


def _escape(value: str) -> str:
    """HTML-escape `&`, `<`, `>` (Contract §13's binding minimum). `quote=False`: no card field is
    ever interpolated into an HTML attribute (news_url is plain text, never an `<a href>`, §12), so
    quote-escaping `"`/`'` would only add unnecessary transformation of visible text."""
    return html.escape(value, quote=False)


def _truncate_at_word_boundary(text: str, budget: int) -> str:
    """Cut `text` to at most `budget` raw characters, backing up to the last complete word
    boundary if one exists within that prefix. Ordinary Python string slicing operates on whole
    Unicode code points, so this can never split a code point or produce invalid Unicode."""
    if budget <= 0:
        return ""
    prefix = text[:budget]
    if len(prefix) == len(text):
        return prefix  # nothing was actually cut
    last_space = prefix.rfind(" ")
    if last_space > 0:
        return prefix[:last_space]
    return prefix  # no word boundary available - hard cut, still valid Unicode


def _render_once(card: EditorialInboxCard, body: str | None) -> str:
    """Render the full card (Contract §12's frozen template) with every field HTML-escaped.

    `body`: the raw (pre-escape) body text to render - `None` means "use the placeholder"
    (card.draft_body was never generated), any other string (including just the truncation marker
    alone) is escaped and rendered as-is (used by the shrink loop below).
    """
    published_suffix = ""
    if card.news_published_at is not None:
        published_suffix = f"  ·  {card.news_published_at:%Y-%m-%d}"

    header_lines = [
        f"\U0001F4F0 <b>{_escape(card.news_category)}</b>{published_suffix}",
        _escape(card.news_title),
    ]
    if card.news_url is not None:
        header_lines.append(_escape(card.news_url))
    header_block = "\n".join(header_lines)

    title_text = _TITLE_PLACEHOLDER if card.draft_title is None else _escape(card.draft_title)
    title_block = f"<b>{title_text}</b>"

    body_text = _BODY_PLACEHOLDER if body is None else _escape(body)

    blocks = [header_block, title_block, body_text]

    if card.hashtags:
        blocks.append(" ".join(_escape(tag) for tag in card.hashtags))

    return "\n\n".join(blocks)


def render_editorial_card(card: EditorialInboxCard) -> str:
    """Render one EditorialInboxCard to a fully-escaped, ready-to-send HTML string, truncating
    `draft_body` (and only `draft_body`) as needed to stay within SAFE_LIMIT (Contract §14).

    Algorithm: render -> measure (UTF-16 code units) -> if oversized, shrink the raw draft_body ->
    re-render -> re-measure -> repeat until it fits or draft_body is fully exhausted. Truncation
    always operates on the raw, pre-escape body, never on already-escaped HTML, so an HTML entity
    can never be split. Raises CardTooLongError (-> Contract §16 Case E) if the card still exceeds
    SAFE_LIMIT even with draft_body reduced to nothing - a defensive last resort, not an
    anticipated path.
    """
    rendered = _render_once(card, card.draft_body)
    if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
        return rendered

    raw_body = card.draft_body or ""
    budget = len(raw_body)
    while budget > 0:
        budget = max(0, budget - _SHRINK_STEP)
        truncated = _truncate_at_word_boundary(raw_body, budget)
        candidate_body = (truncated + _TRUNCATION_MARKER) if truncated else _TRUNCATION_MARKER
        rendered = _render_once(card, candidate_body)
        if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
            return rendered

    # draft_body fully exhausted (or was already None) - one final attempt with just the
    # truncation marker alone, then the terminal fallback.
    rendered = _render_once(card, _TRUNCATION_MARKER)
    if _telegram_utf16_length(rendered) <= SAFE_LIMIT:
        return rendered

    raise CardTooLongError(
        f"draft_id={card.draft_id} exceeds SAFE_LIMIT ({SAFE_LIMIT} UTF-16 code units) even with "
        "draft_body fully exhausted"
    )
