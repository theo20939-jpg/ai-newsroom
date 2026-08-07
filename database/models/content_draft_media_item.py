"""ContentDraftMediaItem ORM model (Phase 19 M10).

A standalone table, surrogate PK (not PK-reuse) - a media item is discovered once per content-
generation attempt, before a ContentDraft row necessarily exists yet (mirrors database/models/
content_draft_editorial_plan.py's own exact reasoning), and `content_draft_id` stays nullable/
populated later for that reason. `event_id` is the primary linkage during shadow-mode discovery
(video discovery happens during article acquisition, which is keyed to a NewsEvent, not yet a
ContentDraft).

`media_type` is a plain string (not yet an enum) scoped to `"video"` for Phase 19 M10 - named
generically because this table is the shared home for both discovered images and videos going
forward (M11 ranks rows from this table), not because M10 itself discovers images too (it does
not - the existing `image_candidates` table, unmodified, remains the source of image candidates;
unifying that data into this table is explicitly out of M10's own narrow scope).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentDraftMediaItem(Base):
    __tablename__ = "content_draft_media_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False, index=True
    )
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True, index=True
    )
    media_type: Mapped[str] = mapped_column(String(16), nullable=False, default="video")
    discovery_method: Mapped[str] = mapped_column(String(64), nullable=False)
    remote_url: Mapped[str] = mapped_column(String, nullable=False)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    declared_width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    declared_height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    declared_mime_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    declared_duration_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    detected_container: Mapped[str | None] = mapped_column(String(16), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
