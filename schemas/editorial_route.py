"""Phase 22 - Telegram Editorial Routing Foundation.

`EditorialDestination` names *where* an already-produced piece of Newsroom output should be
delivered (which Telegram topic in the single NINJA NEWSROOM supergroup) - a different dimension
from `database/models/content_draft.py::ContentType` (POST/SHORT/ANALYSIS/MEME/VIDEO_SCRIPT),
which names *what format* a draft is. The two are not interchangeable and this module performs no
automatic mapping between them - which destination a given draft goes to is supplied explicitly
by the caller, never inferred (docs/phase22_telegram_editorial_routing_report.md §3: "no automatic
decision making" is explicitly out of scope for this phase).

Kept intentionally small - exactly the five topics named in the target NINJA NEWSROOM structure,
no speculative additions.
"""
from __future__ import annotations

import enum


class EditorialDestination(str, enum.Enum):
    """A Telegram topic destination within the NINJA NEWSROOM supergroup."""

    NEWS = "NEWS"
    MEME = "MEME"
    TELEGRAPH = "TELEGRAPH"
    INSTAGRAM = "INSTAGRAM"
    REELS = "REELS"


def parse_editorial_destination(value: str) -> EditorialDestination | None:
    """Best-effort string -> `EditorialDestination` lookup for callers that only have a raw
    string (e.g. a future `ContentDraft.destination` column, not added this phase - see the
    report's own §3/§11). Returns `None` for anything that isn't one of the five known values -
    never raises, so an unrecognized/mistyped destination degrades to the routing layer's own
    explicit "unknown destination -> safe failure, no Telegram call" behavior (services/
    telegram_routing.py) rather than an uncaught `ValueError` from `EditorialDestination(value)`.
    """
    try:
        return EditorialDestination(value)
    except ValueError:
        return None
