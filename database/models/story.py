"""Story ORM model (Phase 18.10 M1: Story Memory Layer).

A `Story` is a deterministic grouping of `NewsEvent` rows believed to describe the same
developing real-world story - never a semantic/embedding cluster (no such infrastructure exists
in this codebase, and this phase deliberately does not add one; see
services/story_memory.py's own module docstring). One `NewsEvent` belongs to at most one
`Story` (via `NewsEvent.story_id`) - no separate join table exists, since a `Story`'s full event
history is always `SELECT * FROM news_events WHERE story_id = :id ORDER BY collected_at`.
"""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.news_event import EventCategory


class Story(Base):
    """A deterministically-grouped developing story (Phase 18.10 M1)."""

    __tablename__ = "stories"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # Title of the first event that started this story - never updated afterward, so it always
    # names the original event, not the latest development (see NewsEvent.title for that).
    title: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[EventCategory] = mapped_column(
        Enum(EventCategory, name="event_category"), nullable=False, index=True
    )
    # services.story_memory.StorySignature's own fields, persisted verbatim - a list[str] each,
    # stored as JSON (mirrors ContentDraft.hashtags' own established "typed dict|None column,
    # list[str] at runtime" convention in this codebase).
    entities: Mapped[list | None] = mapped_column(JSON, nullable=True)
    keywords: Mapped[list | None] = mapped_column(JSON, nullable=True)
    topic_bucket: Mapped[str] = mapped_column(String, nullable=False)
    first_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False
    )
    # Incremented once per event matched into this story (update or semantic duplicate) - a
    # cheap, denormalized count so "how developed is this story" never requires a COUNT(*) query.
    event_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
