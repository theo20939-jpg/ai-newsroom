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
    (the default).

    Phase 20 M10 note: database/migrations/versions/3c22be05f4e5_add_story_memory_v2_shadow_
    columns.py adds three nullable columns (delta_classification, confidence_band, would_suppress)
    for services/story_delta_engine.py, services/story_confidence.py, and services/
    story_suppression.py's outputs - created but deliberately NOT applied to any real database
    this phase (Phase 20's explicit shadow-neutrality/no-migration-application guardrail). This
    ORM class is intentionally NOT updated to declare those columns yet: SQLAlchemy includes every
    mapped column in every generated INSERT regardless of whether it was explicitly set on the
    instance (confirmed empirically - an unset nullable column still appears as a NULL parameter
    in the INSERT), so declaring them here before the migration is applied would break every real
    INSERT against this table (verified: it does, with `UndefinedColumnError`). The model and
    migration are updated together, in the same future, separately-authorized change that applies
    the migration - exactly the precedent every prior shadow-infra migration in this codebase
    follows (model + migration land and apply in the same authorized step, never split apart)."""

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
