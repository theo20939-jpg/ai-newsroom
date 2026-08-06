"""NewsEventStoryLink ORM model (Phase 18.10 M1/M2 migration-dependency fix).

A deliberately standalone table, never a column on `NewsEvent` itself - see
database/models/news_event.py's own comment for the exact reasoning: SQLAlchemy includes every
mapped column of a table in every generated INSERT, so putting story-linkage fields directly on
`NewsEvent` would make the existing, always-run NewsEvent insert (services/collector.py) depend
on the Phase 18.10 migration being applied, regardless of story_memory_mode - an unacceptable
hot-path dependency this table exists specifically to avoid.

`news_event_id` is the primary key (not a separate UUID `id`) - this declares "at most one link
per event" as a hard database constraint, not just an application-level convention.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class NewsEventStoryLink(Base):
    """Links one NewsEvent to the Story it was matched to (Phase 18.10 M1/M2, shadow mode only -
    services/story_memory.py). A row here exists if and only if story_memory_mode != "off" was
    enabled at the time the event was triaged - never created for story_memory_mode == "off"
    (the default)."""

    __tablename__ = "news_event_story_links"

    news_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), primary_key=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True
    )
    # One of "new_story"/"story_update"/"semantic_duplicate"/"uncertain_match"
    # (services/story_memory.py's own outcome constants) - free-text, not an enum, mirroring
    # ContentDraft.status's own documented "not a constrained enum" precedent, since this
    # taxonomy is expected to be refined during shadow-mode calibration.
    match_type: Mapped[str] = mapped_column(String, nullable=False)
    match_score: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
