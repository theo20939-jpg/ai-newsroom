"""Story Timeline + Editorial Memory (Phase 19 M7).

Derives a Story's event history purely from already-persisted evidence - `NewsEventStoryLink`
(Phase 18.10 M1/M2), `ContentDraftStoryLink` and `StoryTelegramDelivery` (Phase 18.10 M3). No
LLM reconstruction, no embeddings, no guessed chronology: ordering is `published_at` with
`collected_at` fallback (the same anchor `worker/content_cycle.py::_select_eligible_events()`
already established as this codebase's one authoritative freshness field), and every "what's
new" signal is a deterministic recomputation of `services.story_memory.extract_story_signature()`
against a running keyword pool built while walking the ordered event list - never a persisted
per-event signature (none exists; `NewsEvent` deliberately has no such column - see database/
models/news_event.py's own hot-path-column rule), and never an LLM's own account of what changed.

Fields with insufficient evidence stay `None`/`"unknown"` rather than being silently inferred -
`source_role` in particular is always `None` in this milestone (Source Intelligence, Phase 19 M8,
is the first thing that could ever populate it).

Split into a pure calculator (`_classify_delta`) and one thin async orchestration function
(`build_story_timeline`, bounded to 3 queries total regardless of story size - never N+1),
mirroring services/story_memory.py's own established split.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_story_link import ContentDraftStoryLink
from database.models.news_event import NewsEvent
from database.models.news_source import NewsSource
from database.models.story_link import NewsEventStoryLink
from database.models.story_telegram_delivery import DeliveryStatus, StoryTelegramDelivery
from services.story_memory import extract_story_signature

# services/story_memory.py's own outcome vocabulary, mapped to a coarser, human-readable delta
# classification - a disclosed, narrow approximation (mirrors services/editorial_planning_
# safety.py's own "coarse deterministic approximation, never a semantic claim" convention), never
# itself a new scoring signal.
_DELTA_NEW_STORY = "new_story"
_DELTA_NEW_INFORMATION = "new_information"
_DELTA_CORROBORATION = "corroboration"
_DELTA_UNKNOWN = "unknown"

_DELTA_BY_MATCH_TYPE = {
    "new_story": _DELTA_NEW_STORY,
    "story_update": _DELTA_NEW_INFORMATION,
    "supporting_source": _DELTA_CORROBORATION,
    "semantic_duplicate": _DELTA_CORROBORATION,
    "uncertain_match": _DELTA_UNKNOWN,
}


@dataclass(frozen=True)
class StoryTimelineEntry:
    event_id: UUID
    source: str | None
    published_at: datetime | None
    collected_at: datetime
    match_type: str
    match_score: float
    source_role: str | None
    content_draft_id: UUID | None
    telegram_message_id: int | None
    delta: str
    already_published: bool
    introduced_new_facts: list[str]
    confirmed_existing_facts: list[str]


def _classify_delta(match_type: str) -> str:
    return _DELTA_BY_MATCH_TYPE.get(match_type, _DELTA_UNKNOWN)


async def build_story_timeline(session: AsyncSession, story_id: UUID) -> list[StoryTimelineEntry]:
    """Read-only. Three bounded queries total (event+link+source join, content-draft links,
    telegram deliveries), never one query per event."""
    link_rows = (
        await session.execute(
            select(NewsEventStoryLink, NewsEvent, NewsSource)
            .join(NewsEvent, NewsEventStoryLink.news_event_id == NewsEvent.id)
            .join(NewsSource, NewsEvent.source_id == NewsSource.id, isouter=True)
            .where(NewsEventStoryLink.story_id == story_id)
        )
    ).all()

    draft_links = (
        await session.execute(
            select(ContentDraftStoryLink).where(ContentDraftStoryLink.story_id == story_id)
        )
    ).scalars().all()
    content_draft_id_by_event: dict[UUID, UUID] = {
        d.source_event_id: d.content_draft_id for d in draft_links
    }

    deliveries = (
        await session.execute(
            select(StoryTelegramDelivery).where(
                StoryTelegramDelivery.story_id == story_id,
                StoryTelegramDelivery.delivery_status == DeliveryStatus.SENT,
            )
        )
    ).scalars().all()
    delivery_by_draft_id: dict[UUID, StoryTelegramDelivery] = {
        d.content_draft_id: d for d in deliveries
    }

    # published_at fallback to collected_at, per worker/content_cycle.py's own established anchor.
    ordered = sorted(link_rows, key=lambda row: row[1].published_at or row[1].collected_at)

    running_keywords: set[str] = set()
    entries: list[StoryTimelineEntry] = []
    for link, event, source in ordered:
        signature = extract_story_signature(event.title, event.category)
        event_keywords = set(signature.keywords)
        introduced = sorted(event_keywords - running_keywords)
        confirmed = sorted(event_keywords & running_keywords)
        running_keywords |= event_keywords

        content_draft_id = content_draft_id_by_event.get(event.id)
        delivery = delivery_by_draft_id.get(content_draft_id) if content_draft_id else None

        entries.append(
            StoryTimelineEntry(
                event_id=event.id,
                source=source.name if source is not None else None,
                published_at=event.published_at,
                collected_at=event.collected_at,
                match_type=link.match_type,
                match_score=link.match_score,
                source_role=None,  # Phase 19 M8 (Source Intelligence) is the first thing that
                                    # could ever populate this - always unknown/absent until then.
                content_draft_id=content_draft_id,
                telegram_message_id=delivery.telegram_message_id if delivery is not None else None,
                delta=_classify_delta(link.match_type),
                already_published=delivery is not None,
                introduced_new_facts=introduced,
                confirmed_existing_facts=confirmed,
            )
        )
    return entries
