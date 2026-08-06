"""NewsEvent ORM model."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EventCategory(str, enum.Enum):
    """Topical category of a news event."""

    AI = "AI"
    GADGETS = "GADGETS"
    TECH = "TECH"
    STARTUPS = "STARTUPS"
    SOFTWARE = "SOFTWARE"
    HARDWARE = "HARDWARE"
    CYBERSECURITY = "CYBERSECURITY"
    UNKNOWN = "UNKNOWN"


class EventStatus(str, enum.Enum):
    """Processing status of a news event."""

    NEW = "NEW"
    PROCESSING = "PROCESSING"
    ANALYZED = "ANALYZED"
    REJECTED = "REJECTED"
    ARCHIVED = "ARCHIVED"


class NewsEvent(Base):
    """A single deduplicated news event collected from a source."""

    __tablename__ = "news_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sources.id"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(Text, nullable=True)
    category: Mapped[EventCategory] = mapped_column(
        Enum(EventCategory, name="event_category"), nullable=False, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    collected_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    hash: Mapped[str] = mapped_column(String, unique=True, nullable=False)
    status: Mapped[EventStatus] = mapped_column(
        Enum(EventStatus, name="event_status"), nullable=False, default=EventStatus.NEW, index=True
    )
    # Phase 15 M3: real, observed engagement metrics captured at collection time, where the
    # source exposes them. NULL means "unavailable from this source" - never conflated with a
    # real, observed 0 (see services/cleaning.py and integrations/sources/telegram_source.py).
    # RSS/web-sourced events always have all four NULL; no value is ever fabricated.
    views_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwards_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    replies_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Phase 18.10 M1/M2 (Story Memory): deliberately NOT a column on this model - see
    # database/models/story_link.py::NewsEventStoryLink. SQLAlchemy includes every mapped column
    # of a table in every generated INSERT (even with a None value), so a nullable column here
    # would make the *existing*, always-run NewsEvent insert (services/collector.py) fail against
    # a database that hasn't had the Phase 18.10 migration applied yet, regardless of
    # story_memory_mode. A separate, standalone table (only ever touched when
    # story_memory_mode != "off" explicitly creates a row) keeps this model's own schema, and
    # every existing insert into it, byte-identical to before Phase 18.10 - exactly how the
    # pre-existing, still-unapplied meme_candidates table (Phase 18 M2) has always safely
    # coexisted unapplied without breaking anything outside the meme pipeline.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
