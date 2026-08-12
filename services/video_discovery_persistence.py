"""Phase 19 M10: the sole place that constructs/persists ContentDraftMediaItem rows.

Exists specifically so capabilities/executor.py (and any other capabilities-layer code) never
imports database.models.content_draft_media_item directly - mirrors services/editorial_plan_
persistence.py's own exact rationale and shape.

Phase 23.1Q (Media Roadmap Recovery, video shadow activation): adds the sole READ contract for
this table (`get_video_candidates_for_event`) - previously write-only. Mirrors services/
image_persistence.py::get_editorial_image_candidates()'s own established shape (a plain, frozen
dataclass return type - never the ORM row itself - ordered/filtered so callers get an
already-eligible set, not a raw dump). Read-only, no I/O beyond the one SELECT.
"""
from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_media_item import ContentDraftMediaItem
from schemas.video_candidate import (
    NativeVideoHint,
    VideoValidation,
    VideoValidationStatus,
)


async def persist_video_hint(
    session: AsyncSession,
    *,
    event_id: UUID,
    hint: NativeVideoHint,
    validation: VideoValidation,
    content_draft_id: UUID | None = None,
) -> None:
    """Adds one ContentDraftMediaItem row to `session` (does not commit - the caller's own
    SAVEPOINT/commit discipline governs that, exactly as every other Phase 19 shadow write does)."""
    row = ContentDraftMediaItem(
        event_id=event_id, content_draft_id=content_draft_id, media_type="video",
        discovery_method=hint.discovery_method.value, remote_url=hint.remote_url,
        platform=hint.platform.value, declared_width=hint.declared_width,
        declared_height=hint.declared_height, declared_mime_type=hint.declared_mime_type,
        declared_duration_seconds=hint.declared_duration_seconds,
        validation_status=validation.status.value, detected_container=validation.detected_container,
        byte_size=validation.byte_size, error_code=validation.error_code,
    )
    session.add(row)


def unvalidated_hosted_platform_result() -> VideoValidation:
    """YouTube/Vimeo candidates are validated by URL pattern only, never fetched - a fixed,
    reusable result for that case."""
    return VideoValidation(status=VideoValidationStatus.UNVALIDATED_HOSTED_PLATFORM)


@dataclass(frozen=True)
class EligibleVideoCandidate:
    """The read contract - mirrors services/image_persistence.py::EditorialImageCandidate's own
    shape/naming convention (a plain, frozen dataclass, never the ORM row itself)."""

    id: UUID
    event_id: UUID
    content_draft_id: UUID | None
    discovery_method: str
    remote_url: str
    platform: str
    declared_width: int | None
    declared_height: int | None
    declared_mime_type: str | None
    declared_duration_seconds: int | None
    validation_status: str
    detected_container: str | None
    byte_size: int | None
    error_code: str | None


async def get_video_candidates_for_event(
    session: AsyncSession, event_id: UUID, *, limit: int = 5, include_rejected: bool = False,
) -> list[EligibleVideoCandidate]:
    """The sole read contract for this table (Phase 23.1Q). Scoped to `event_id` - NOT
    `content_draft_id` - because video discovery runs during article acquisition/triage, keyed to
    the NewsEvent, typically before a ContentDraft exists yet (see this table's own model
    docstring); a `content_draft_id`-keyed query, mirroring the image path exactly, would miss
    every row discovered before content generation ran.

    `include_rejected=False` (default): excludes `validation_status == "rejected"` at the query
    level - mirrors `get_editorial_image_candidates()`'s own `eligible_for_editorial=True` filter,
    "the caller only ever sees an already-eligible set" convention. `unvalidated_hosted_platform`
    (YouTube/Vimeo) rows are NEVER excluded by this flag - they are not a validation failure, they
    are a real, intentionally-unfetched category (services/video_discovery.py's own explicit
    design) that a caller (e.g. media_ranking.py's own eligibility logic) must still be able to
    see and reason about.

    Ordered by `created_at` ascending (the only meaningful ordering available - this table has no
    `rank` column of its own, unlike `image_candidates`; ranking happens downstream via
    services/media_ranking.py::rank_media_candidates(), not here)."""
    stmt = select(ContentDraftMediaItem).where(ContentDraftMediaItem.event_id == event_id)
    if not include_rejected:
        stmt = stmt.where(ContentDraftMediaItem.validation_status != VideoValidationStatus.REJECTED.value)
    stmt = stmt.order_by(ContentDraftMediaItem.created_at.asc()).limit(limit)

    rows = (await session.execute(stmt)).scalars().all()
    return [
        EligibleVideoCandidate(
            id=row.id, event_id=row.event_id, content_draft_id=row.content_draft_id,
            discovery_method=row.discovery_method, remote_url=row.remote_url, platform=row.platform,
            declared_width=row.declared_width, declared_height=row.declared_height,
            declared_mime_type=row.declared_mime_type, declared_duration_seconds=row.declared_duration_seconds,
            validation_status=row.validation_status, detected_container=row.detected_container,
            byte_size=row.byte_size, error_code=row.error_code,
        )
        for row in rows
    ]
