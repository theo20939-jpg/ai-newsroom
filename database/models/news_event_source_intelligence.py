"""NewsEventSourceIntelligence ORM model (Phase 19 M8).

A standalone table, PK reuses `news_event_id` (1:1 extension - mirrors `news_event_article_
acquisitions`/`news_event_story_links`' own convention): at most one source-role classification
per event, since services/source_intelligence.py::classify_source_role() is a pure, single-
decision function evaluated once per event.

Stores only the hedged label (`POSSIBLE_ORIGINAL`/`POSSIBLE_CONFIRMATION`/`POSSIBLE_AGGREGATION`/
`POSSIBLE_ANALYSIS`/`UNKNOWN`) plus the inputs it was computed from, for review - never a
definitive attribution claim, never consumed by Copywriting.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class NewsEventSourceIntelligence(Base):
    __tablename__ = "news_event_source_intelligence"

    news_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    is_first_in_story: Mapped[bool] = mapped_column(Boolean, nullable=False)
    match_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    reliability_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
