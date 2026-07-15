"""NewsEvent ORM model."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
