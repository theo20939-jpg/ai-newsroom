"""Phase 19 M2: EvidencePackage - the canonical editorial input for Research, Editorial Planning,
Copywriting, and quote verification (docs/phase19_m0_audit.md).

Four explicitly-separated layers, enforced by field naming, not just documentation:
1. Raw source material - `rss_excerpt` (verbatim NewsEvent.content), `full_text` (verbatim M1
   extraction, pre-cleaning, audit-only - never given to a prompt directly).
2. Cleaned source material - `selected_editorial_text` (M2's cleaned output, or `rss_excerpt`
   unchanged when no usable full article exists - the explicit, required fallback).
3. Structured extracted evidence - `quote_candidates`, `media_candidates`, `known_evidence_gaps`.
4. Editorial context derived from Story Memory - `story_id`, `story_match_type`,
   `previous_coverage_summary` (populated only when available; never fabricated).

`NewsEvent.content` is never overwritten anywhere in this module. `selected_editorial_text` comes
exclusively from the persisted `news_event_article_acquisitions.cleaned_text` (via
services.article_acquisition.get_effective_acquisition(), one hop max) when non-null, else the
`rss_excerpt` fallback - never any other derivation path, never recomputed inline (Correction 4).

`quote_candidates`/`media_candidates` are empty in this phase - their extraction is Phase 19
M5(quotes)/M9-M11(media) scope, not yet implemented; the fields exist now so this schema does not
need to change shape when those milestones land. `previous_coverage_summary`/`story_match_type`
read only the Phase 18.10 story-link table already shipped (gated identically to
services/editorial_scoring.py's own established story_memory_mode != "off" gate) - Phase 19 M7's
own Story Timeline digest is not yet built, so this field stays a thin pointer, never fabricated.
`author`/`detected_language` are disclosed gaps this phase - no metadata/language extraction was
built in M1/M2 - both stay None, never guessed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from database.models.news_event import NewsEvent
from database.models.news_event_article_acquisition import (
    ACQUISITION_STATUS_FULL_TEXT,
    ACQUISITION_STATUS_HEADLINE_ONLY,
    ACQUISITION_STATUS_PARTIAL_TEXT,
)
from database.models.news_source import NewsSource
from services.article_acquisition import compute_text_hash, get_effective_acquisition
from services.article_cleaning import clean_extracted_text

# NEWS Stability Acceptance follow-up (docs/post_acceptance_followup_checkpoint.md §C): the
# original Phase 19 M2 design (services/article_cleaning.py's own module docstring) intended
# `cleaned_text` to be computed once and persisted directly on the news_event_article_acquisitions
# row - but that persistence step was never actually wired into the acquisition write path
# (confirmed empirically: 0 of 210 real rows have cleaned_text populated, despite 109 having
# raw_extracted_text). `article_acquisition_mode == "enforce"`'s own documented purpose ("Research/
# quote-verification read the persisted evidence via services.evidence_package instead") was
# therefore silently a no-op even when enabled - build_evidence_package()'s `acquisition.
# cleaned_text` check could never be true. Mirrors capabilities/executor.py's own already-proven,
# already-shadow-active `quote_source_text` workaround (clean_extracted_text() computed on the fly
# from `raw_extracted_text`) rather than depending on the never-populated column - same function,
# same completeness-tier gate ("FULL_TEXT"/"PARTIAL_TEXT" only - a HEADLINE_ONLY/REDIRECT_
# UNRESOLVED/FETCH_FAILED/PAYWALLED acquisition's raw text, if any, is never trusted as "full
# article" evidence), reused verbatim, never a second, divergent cleaning rule. This is not a new
# transport path - still the same already-persisted `raw_extracted_text` column, read via the same
# already-existing get_effective_acquisition() call.
#
# NEWS Reuse/Enforce Interaction Fix (docs/research_reuse_entity_normalization_checkpoint.md §A):
# now also imported by services/analysis_reuse.py's own reuse-freshness check, for the identical
# reason - a public name since it now has two real consumers, never a second, divergent
# "trusted enough" definition.
TRUSTED_FULL_ARTICLE_STATUSES = frozenset({ACQUISITION_STATUS_FULL_TEXT, ACQUISITION_STATUS_PARTIAL_TEXT})

_COMPLETENESS_EXCERPT_ONLY = "excerpt_only"
_EXTRACTION_METHOD_FULL_ARTICLE = "full_article_acquisition"
_EXTRACTION_METHOD_RSS_FALLBACK = "rss_excerpt_fallback"


@dataclass(frozen=True)
class EvidencePackage:
    news_event_id: UUID
    original_headline: str
    rss_excerpt: str | None
    full_text: str | None
    selected_editorial_text: str
    selected_editorial_text_hash: str
    source_name: str | None
    source_type: str | None
    source_url: str | None
    canonical_url: str | None
    author: str | None
    published_at: datetime | None
    fetched_at: datetime | None
    detected_language: str | None
    article_char_count: int
    article_word_count: int
    acquisition_status: str | None
    completeness_level: str
    extraction_method: str
    quote_candidates: list[str] = field(default_factory=list)
    media_candidates: list[str] = field(default_factory=list)
    known_evidence_gaps: list[str] = field(default_factory=list)
    story_id: UUID | None = None
    story_match_type: str | None = None
    previous_coverage_summary: str | None = None


def _known_evidence_gaps(
    *, acquisition_status: str | None, author: str | None, detected_language: str | None
) -> list[str]:
    """Pure. Deterministic only - never an LLM guess (module docstring)."""
    gaps: list[str] = []
    if acquisition_status is None:
        gaps.append("full_article_unavailable")
    elif acquisition_status == "PAYWALLED":
        gaps.append("paywalled_beyond_excerpt")
    elif acquisition_status == ACQUISITION_STATUS_HEADLINE_ONLY:
        gaps.append("full_article_unavailable")
    if author is None:
        gaps.append("no_author_metadata")
    if detected_language is None:
        gaps.append("no_language_detection")
    gaps.append("single_source_only")  # cross-source corroboration not yet tracked (Phase 19 M8)
    return gaps


async def _story_link_context(
    session: AsyncSession, news_event_id: UUID
) -> tuple[UUID | None, str | None]:
    """Reads only the already-shipped Phase 18.10 NewsEventStoryLink table, gated identically to
    services/editorial_scoring.py's own established story_memory_mode != "off" gate - never
    fabricated, never populated from any Phase 19 M7/M8 mechanism (not yet built)."""
    if settings.story_memory_mode == "off":
        return None, None
    from database.models.story_link import NewsEventStoryLink

    link = await session.get(NewsEventStoryLink, news_event_id)
    if link is None:
        return None, None
    return link.story_id, link.match_type


async def build_evidence_package(session: AsyncSession, news_event: NewsEvent) -> EvidencePackage:
    """The sole entry point.

    CONTRACT (binding on every caller, current and future):
    1. This function ASSUMES the Phase 19 M1 `news_event_article_acquisitions` table already
       exists. It does not probe for the table's existence and does not catch a schema-level
       failure - it will raise (typically `sqlalchemy.exc.ProgrammingError` /
       `UndefinedTableError`) if that table is missing.
    2. Every hot-path/production caller MUST use guarded fallback behavior around this call -
       specifically a SAVEPOINT (`async with session.begin_nested():`) plus a broad `except
       Exception` that degrades to the pre-Phase-19 `news_event.content` path, exactly as
       `capabilities/executor.py` and `services/content_draft_service.py` already do. A bare,
       unguarded `await build_evidence_package(...)` on a production call path is a bug, not an
       acceptable simplification - it would let a mode flipped to "enforce" before the migration
       is applied crash Copywriting/draft persistence instead of degrading.
    3. This function MUST NOT be called directly from any unguarded production code path. New
       callers must add themselves to the "only two callers" list immediately below and must
       replicate the same SAVEPOINT+broad-except guard - never assume the table is present.
       `tests/test_evidence_package_call_sites.py` is a regression guard enforcing exactly this:
       it fails if a new, unguarded call site is ever introduced.

    A missing/failed *acquisition* (no row for this event, or a fetch that failed) degrades to
    the rss_excerpt fallback without raising - the ordinary, expected case whenever
    article_acquisition_mode != "enforce" for this event. This is a *data*-level degradation,
    distinct from the *schema*-level failure described in point 1 above.

    This module's only two current, guarded callers are `capabilities/executor.py` and
    `services/content_draft_service.py` - both wrap their call in a SAVEPOINT
    (`session.begin_nested()`) and catch broadly, degrading to the pre-Phase-19
    `news_event.content` path - mirrors services/story_memory.py's own established
    "caller catches the missing-table case" convention."""
    source: NewsSource | None = await session.get(NewsSource, news_event.source_id)

    acquisition = await get_effective_acquisition(session, news_event.id)
    rss_excerpt = news_event.content

    full_text: str | None
    canonical_url: str | None
    acquisition_status: str | None
    fetched_at: datetime | None

    # `acquisition.cleaned_text` is checked first (the originally-designed, never-actually-
    # populated persisted path - see this module's own import-block comment) - if a future change
    # does start persisting it, this branch starts using that direct value for free, with zero
    # further changes needed here. Until then, the `elif` below is what actually fires: the same
    # on-the-fly clean_extracted_text() computation capabilities/executor.py's own quote_source_
    # text mechanism already proves out, applied only for a trusted completeness tier.
    if acquisition is not None and acquisition.cleaned_text:
        selected_text = acquisition.cleaned_text
        completeness_level = acquisition.effective_completeness_status
        extraction_method = _EXTRACTION_METHOD_FULL_ARTICLE
        full_text = acquisition.raw_extracted_text
        canonical_url = acquisition.canonical_url
        acquisition_status = acquisition.acquisition_status
        fetched_at = acquisition.created_at
    elif (
        acquisition is not None
        and acquisition.effective_completeness_status in TRUSTED_FULL_ARTICLE_STATUSES
        and acquisition.raw_extracted_text
    ):
        selected_text = clean_extracted_text(acquisition.raw_extracted_text, title=news_event.title).cleaned_text
        completeness_level = acquisition.effective_completeness_status
        extraction_method = _EXTRACTION_METHOD_FULL_ARTICLE
        full_text = acquisition.raw_extracted_text
        canonical_url = acquisition.canonical_url
        acquisition_status = acquisition.acquisition_status
        fetched_at = acquisition.created_at
    else:
        selected_text = rss_excerpt or ""
        completeness_level = _COMPLETENESS_EXCERPT_ONLY
        extraction_method = _EXTRACTION_METHOD_RSS_FALLBACK
        full_text = None
        canonical_url = None
        acquisition_status = acquisition.acquisition_status if acquisition is not None else None
        fetched_at = None

    story_id, story_match_type = await _story_link_context(session, news_event.id)

    return EvidencePackage(
        news_event_id=news_event.id,
        original_headline=news_event.title,
        rss_excerpt=rss_excerpt,
        full_text=full_text,
        selected_editorial_text=selected_text,
        selected_editorial_text_hash=compute_text_hash(selected_text),
        source_name=source.name if source is not None else None,
        source_type=source.type.value if source is not None else None,
        source_url=news_event.url,
        canonical_url=canonical_url,
        author=None,
        published_at=news_event.published_at,
        fetched_at=fetched_at,
        detected_language=None,
        article_char_count=len(selected_text),
        article_word_count=len(selected_text.split()),
        acquisition_status=acquisition_status,
        completeness_level=completeness_level,
        extraction_method=extraction_method,
        quote_candidates=[],
        media_candidates=[],
        known_evidence_gaps=_known_evidence_gaps(
            acquisition_status=acquisition_status, author=None, detected_language=None
        ),
        story_id=story_id,
        story_match_type=story_match_type,
        previous_coverage_summary=None,
    )
