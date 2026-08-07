"""Phase 19 M10: the sole place that constructs/persists ContentDraftMediaItem rows.

Exists specifically so capabilities/executor.py (and any other capabilities-layer code) never
imports database.models.content_draft_media_item directly - mirrors services/editorial_plan_
persistence.py's own exact rationale and shape.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from database.models.content_draft_media_item import ContentDraftMediaItem
from schemas.video_candidate import NativeVideoHint, VideoValidation, VideoValidationStatus


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
