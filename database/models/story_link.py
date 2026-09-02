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

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, Text, func
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
    story_suppression.py's outputs. PHASE STORY-MEMORY-V2-2 preflight (2026-09-02) confirmed this
    migration - despite its own docstring's "deliberately NOT applied" note - is in fact already
    applied (it sits inside the linear alembic history other, later-shipped migrations already
    build on, and its three columns were confirmed present via direct information_schema
    inspection). Those three columns are still intentionally NOT declared on this ORM class here -
    out of scope for the Phase 1 change that added the block below; still governed by the same
    "model and migration land together" rule this docstring documents.

    PHASE STORY-MEMORY-V2-2 (2026-09-02), rollout step 1 of the approved Story Memory V2 design
    (PHASE STORY-MEMORY-V2-1): the seven columns below (database/migrations/versions/
    af2aeb69cf67_add_story_memory_v2_phase1_columns.py, applied together with this model change,
    per the exact same discipline the note above describes) reserve storage for the future AI
    Story Judge's final, actionable decision - distinct from `match_type` above (six legacy,
    retrieval-only values: new_story/story_update/supporting_source/semantic_duplicate/
    uncertain_match/related_story) and distinct from the three V2 shadow columns. No runtime code
    reads or writes any of these seven columns yet - `final_decision` computation, the AI Judge
    itself, and every downstream consumer are out of scope for this phase and land in a later,
    separately-authorized phase."""

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

    # --- PHASE STORY-MEMORY-V2-2 Phase 1 (2026-09-02) - reserved for the future AI Story Judge,
    # unread/unwritten by any runtime code this phase (see class docstring above). ---
    final_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_source: Mapped[str | None] = mapped_column(String, nullable=True)
    decision_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    judge_error_category: Mapped[str | None] = mapped_column(String, nullable=True)
    new_facts: Mapped[list | None] = mapped_column(JSON, nullable=True)
    material_delta: Mapped[list | None] = mapped_column(JSON, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
