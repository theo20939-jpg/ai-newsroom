"""StoryContextSnapshot ORM model (Phase 19 M7, Editorial Memory).

A standalone table, surrogate PK (not PK-reuse) - mirrors database/models/content_draft_
editorial_plan.py's own exact reasoning: a snapshot is computed once per content-generation
*attempt*, before a ContentDraft row necessarily exists yet, and `content_draft_id` stays
nullable/populated later for that reason.

Persists services/story_context.py::build_story_timeline()'s output (a deterministic, evidence-
only reconstruction - never LLM-generated, never a guessed chronology) as one JSON blob, for
human review only - story_context_mode="shadow" never lets this data reach Copywriting or change
any production output (see capabilities/executor.py::_attach_story_context()'s own docstring).
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class StoryContextSnapshot(Base):
    __tablename__ = "story_context_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False, index=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True)
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True, index=True
    )
    # list[dict] - one entry per services/story_context.py::StoryTimelineEntry, stored as JSON
    # exactly like ContentDraftEditorialPlan.plan's own "always read/written as one unit" pattern.
    timeline: Mapped[list] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
