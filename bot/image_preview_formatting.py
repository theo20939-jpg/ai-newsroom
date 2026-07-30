"""Phase 16 M6: pure Telegram Editorial Preview renderer (docs/
phase16_m6_telegram_editorial_preview_report.md §5). Mirrors bot/formatting.py's own "pure
functions, no aiogram/Bot type anywhere in this module" discipline exactly - testable with zero
Telegram mocking. A deliberately separate module from bot/formatting.py: `render_editorial_card()`
(the public/internal news-delivery card) is never touched, never reused, never replaced by this
one (Contract - M6 task brief §3).

Never claims or fabricates editorial judgment beyond what Phase 16 M1-M4 already computed:
`relevance_reason` is displayed verbatim (M4's own fixed, already-audited template string, see
docs/phase16_m4_relevance_ranking_report.md §16/§22) - no new bullet-point heuristic is invented
here.
"""
import html
from urllib.parse import urlsplit

from services.image_persistence import EditorialImageCandidate

# Telegram's own hard limit for a photo caption, in UTF-16 code units - distinct from (and much
# smaller than) bot/formatting.py's SAFE_LIMIT (4096), which applies to plain text messages only.
CAPTION_SAFE_LIMIT = 1024

_NO_REASON_TEXT = "no relevance evidence recorded"


def _telegram_utf16_length(text: str) -> int:
    """Identical semantic to bot/formatting.py::_telegram_utf16_length() - Python's `len()` counts
    Unicode code points, not the UTF-16 code units Telegram's own limits are measured in."""
    return len(text.encode("utf-16-le")) // 2


def _escape(value: str) -> str:
    return html.escape(value, quote=False)


def _display_source(candidate: EditorialImageCandidate) -> str:
    """A short, human-readable site label derived from the article's own URL - never a new stored
    field (docs §5: `ImageCandidateRecord.source_name` stays reserved/unused, per the M5 report's
    own documented design). `None` (never a blank string) when no URL is available at all."""
    url = candidate.article_url or candidate.source_url
    if not url:
        return "unknown"
    netloc = urlsplit(url).netloc
    return netloc[4:] if netloc.startswith("www.") else netloc or "unknown"


def _dimensions(candidate: EditorialImageCandidate) -> str | None:
    if candidate.width and candidate.height:
        return f"{candidate.width}×{candidate.height}"
    return None


def _truncate(text: str, max_chars: int) -> str:
    """Deterministic, simple hard cut at a raw-character budget - the reason string is a single
    short sentence (M4's own fixed template), never long enough in practice to need
    bot/formatting.py's own word-boundary/shrink-loop machinery."""
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "…"


def render_image_preview_caption(
    candidate: EditorialImageCandidate, *, draft_title: str | None, index: int, total: int,
) -> str:
    """Renders one candidate's preview caption/text - HTML, escaped, capped at CAPTION_SAFE_LIMIT.
    Used both as a `send_photo` caption (when bytes are available) and as the body of a
    text-only fallback message (when they are not, §9) - the same content either way, only the
    Telegram send method differs."""
    title_line = _escape(draft_title) if draft_title else "(untitled draft)"
    lines = [
        f"\U0001F5BC <b>Image preview</b> — {title_line}",
        f"Image {index + 1}/{total}",
        "",
        f"Source: {_escape(_display_source(candidate))}",
    ]
    if candidate.quality_score is not None:
        lines.append(f"Quality: {candidate.quality_score}/100")
    if candidate.relevance_score is not None:
        lines.append(f"Relevance: {candidate.relevance_score}/100")
    dimensions = _dimensions(candidate)
    if dimensions is not None:
        lines.append(f"Size: {dimensions}")
    reason = candidate.relevance_reason or _NO_REASON_TEXT
    lines.append(f"Reason: {_escape(_truncate(reason, 200))}")
    if candidate.is_expired:
        lines.append("")
        lines.append("⚠️ This candidate has expired and cannot be selected.")
    elif candidate.storage_status != "stored":
        lines.append("")
        lines.append("ℹ️ Preview image not stored - metadata only.")

    rendered = "\n".join(lines)
    if _telegram_utf16_length(rendered) <= CAPTION_SAFE_LIMIT:
        return rendered

    # Defensive fallback - the reason line is already capped at 200 chars above, so this should
    # not normally trigger; if it somehow still overflows, drop the reason line entirely rather
    # than raise (mirrors bot/formatting.py's own "never crash the send" discipline, simplified
    # since this content is short and structurally bounded, unlike a free-form draft body).
    trimmed = [line for line in lines if not line.startswith("Reason:")]
    return "\n".join(trimmed)


def render_no_candidates_text(draft_title: str | None) -> str:
    title_line = _escape(draft_title) if draft_title else "(untitled draft)"
    return f"\U0001F5BC <b>Image preview</b> — {title_line}\n\nNo image candidates are available for this draft."


def render_decision_confirmation_text(*, selected: bool, candidate: EditorialImageCandidate | None) -> str:
    """Replaces the interactive caption/text once a decision has been made (§8) - the keyboard is
    removed at the same time by the caller, ending the interactive flow for that message."""
    if selected and candidate is not None:
        return f"✅ Image selected for this draft (source: {_escape(_display_source(candidate))})."
    return "\U0001F6AB No image will be used for this draft."


def render_expired_candidate_alert_text() -> str:
    """Shown as a Telegram callback-query alert (`show_alert=True`), not a message edit - the
    candidate being acted on has already expired per M5's own retention policy (§8/§9)."""
    return "This image candidate has expired and can no longer be selected."


def render_unavailable_candidate_alert_text() -> str:
    """Shown when the referenced candidate row no longer exists at all (deleted, or a tampered/
    stale callback from an old message) - distinct from the expired case above."""
    return "This image candidate is no longer available."
