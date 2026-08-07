"""Phase 19 M7: the sole place that constructs/persists a StoryContextSnapshot row.

Exists specifically so capabilities/executor.py never imports database.models.story_context_
snapshot directly - mirrors services/editorial_plan_persistence.py's own exact rationale and
shape (Contract §7's "Capabilities MUST NOT create, update, or hold any reference to a
ContentDraft row" - this model holds a nullable content_draft_id FK, so the same indirection
applies even though its own module name would not itself trip tests/test_content_draft_service.py
::test_capabilities_never_import_content_draft()'s "content_draft" name-substring check).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.story_context_snapshot import StoryContextSnapshot
from services.story_context import StoryTimelineEntry


def _entry_to_dict(entry: StoryTimelineEntry) -> dict:
    return {
        "event_id": str(entry.event_id),
        "source": entry.source,
        "published_at": entry.published_at.isoformat() if entry.published_at else None,
        "collected_at": entry.collected_at.isoformat() if entry.collected_at else None,
        "match_type": entry.match_type,
        "match_score": entry.match_score,
        "source_role": entry.source_role,
        "content_draft_id": str(entry.content_draft_id) if entry.content_draft_id else None,
        "telegram_message_id": entry.telegram_message_id,
        "delta": entry.delta,
        "already_published": entry.already_published,
        "introduced_new_facts": entry.introduced_new_facts,
        "confirmed_existing_facts": entry.confirmed_existing_facts,
    }


async def persist_story_context_snapshot(
    session: AsyncSession,
    *,
    event_id: UUID,
    story_id: UUID,
    timeline: list[StoryTimelineEntry],
    content_draft_id: UUID | None = None,
) -> None:
    """Adds one StoryContextSnapshot row to `session` (does not commit - the caller's own
    SAVEPOINT/commit discipline governs that, exactly as services.editorial_plan_persistence.
    persist_shadow_plan() already does)."""
    row = StoryContextSnapshot(
        event_id=event_id, story_id=story_id, content_draft_id=content_draft_id,
        timeline=[_entry_to_dict(entry) for entry in timeline],
    )
    session.add(row)
