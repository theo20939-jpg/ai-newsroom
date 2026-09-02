"""ContentDraftStoryLink ORM model (Phase 18.10 M3).

A deliberately standalone table, never a column on `ContentDraft` itself - mirrors
database/models/story_link.py::NewsEventStoryLink's own exact reasoning: SQLAlchemy includes
every mapped column in every generated INSERT, so putting this data directly on `ContentDraft`
would make the existing, always-run draft insert (services/content_draft_service.py) depend on
this phase's migration being applied, regardless of whether story linkage is even in use.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentDraftStoryLink(Base):
    """Links one ContentDraft to the Story its underlying NewsEvent was matched to (Phase 18.10
    M1/M3). A row here exists if and only if the source NewsEvent had a NewsEventStoryLink at the
    time this draft was created - never created otherwise."""

    __tablename__ = "content_draft_story_links"

    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), primary_key=True
    )
    story_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("stories.id"), nullable=False, index=True)
    # True for story_update/supporting_source/semantic_duplicate match types - i.e. "this draft's
    # underlying event refers to an existing story, so its Telegram delivery should be a reply,
    # not a fresh root post." False for new_story/uncertain_match (uncertainty is deliberately
    # never treated as a confirmed update - services/story_memory.py's own conservative design).
    is_story_update: Mapped[bool] = mapped_column(Boolean, nullable=False)
    source_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # PHASE STORY-MEMORY-V2-2 Phase 1 (2026-09-02, database/migrations/versions/
    # af2aeb69cf67_add_story_memory_v2_phase1_columns.py): reserved for a future, separately-
    # authorized phase - whether this draft was generated with Story.published_facts empty (no
    # prior reader-visible coverage), which drives which candidate fact set that future phase's
    # publish-time extraction step compares against (PHASE STORY-MEMORY-V2-1 §H correction).
    # services/content_draft_service.py does not set this yet - stays NULL for every row this
    # phase.
    generated_as_standalone: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
