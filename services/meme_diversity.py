"""MEME PRODUCTION PIPELINE (overnight phase): bounded recent-history lookback for meme concept
diversity - the smallest DB-backed mechanism that lets `capabilities/meme_concept_capability.py`
avoid repeating a recently-used format/humor mechanism, without any new persistence, vector DB, or
embedding infrastructure.

Reuses `database.models.meme_candidate.MemeCandidate` (already-existing, already-durable table) -
no new table, no new column. Reads `concept_data` (the JSON blob `MemeConcept.model_dump(mode=
"json")` produced, per `services/meme_candidate_service.py::create_from_concept()`'s own
persistence contract) directly, never re-deserializing it as a full `MemeConcept` model (only
`meme_format`/`humor_mechanism`/`punchline` are ever read here - a lighter-weight read than a full
schema round-trip, and tolerant of a row from an older `MemeConcept` schema version that may lack a
field this module doesn't need).

Bounded by `settings.meme_recent_diversity_lookback` (default 10) - never unbounded history, never
scoped to "similar stories" (no semantic search exists or is justified for this alone), just the N
most recently created candidates across every NewsEvent. This is a real, disclosed limitation: two
completely unrelated stories occurring back-to-back still count against each other's diversity
budget, and a candidate created more than `meme_recent_diversity_lookback` rows ago is invisible to
this lookback regardless of how recently it was actually created in wall-clock time (a count-based
window, not a time-based one - deliberately simpler and more predictable than a time cutoff that
would behave differently depending on how bursty meme generation happens to be).
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.meme_candidate import MemeCandidate


async def build_recent_diversity_context(session: AsyncSession, *, limit: int | None = None) -> str | None:
    """Returns a short, bounded text block listing the `meme_format`/`humor_mechanism` of the
    `limit` (default `settings.meme_recent_diversity_lookback`) most recently created
    `MemeCandidate` rows, or `None` if there are zero prior candidates at all (the common case
    before this feature has ever produced a single meme) - `None` is a valid, expected value, not
    an error, and every caller treats it as "no diversity context available yet."

    A row whose `concept_data` is missing either field (a malformed/legacy row) is skipped for
    that row's own contribution rather than aborting the whole lookback - this is a best-effort
    diversity signal, not a data-integrity check."""
    effective_limit = limit if limit is not None else settings.meme_recent_diversity_lookback

    stmt = (
        select(MemeCandidate.concept_data)
        .order_by(MemeCandidate.created_at.desc())
        .limit(effective_limit)
    )
    rows = (await session.execute(stmt)).scalars().all()

    lines: list[str] = []
    for concept_data in rows:
        if not isinstance(concept_data, dict):
            continue
        meme_format = concept_data.get("meme_format")
        humor_mechanism = concept_data.get("humor_mechanism")
        # MEME-PROD-4: visual_punchline (the Meme Director's own specific-visual-joke field,
        # schemas/meme_concept.py) is a stronger repetition signal than format/mechanism alone -
        # two concepts can share a format/mechanism label while telling a genuinely different
        # joke, but a near-identical visual_punchline is real evidence of the same protagonist/
        # metaphor being reused. Truncated (never the full sentence) - this stays a short diversity
        # hint, not a second copy of the concept's own text for the model to quote back verbatim.
        visual_punchline = concept_data.get("visual_punchline")
        if not meme_format and not humor_mechanism and not visual_punchline:
            continue
        parts = []
        if meme_format:
            parts.append(f"format={meme_format}")
        if humor_mechanism:
            parts.append(f"mechanism={humor_mechanism}")
        if visual_punchline:
            snippet = str(visual_punchline)[:60]
            parts.append(f"visual_punchline~={snippet}")
        lines.append("- " + ", ".join(parts))

    if not lines:
        return None
    return "\n".join(lines)
