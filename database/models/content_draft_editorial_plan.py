"""ContentDraftEditorialPlan ORM model (Phase 19 M3).

A standalone table, surrogate PK (not PK-reuse) - a plan is produced once per content-generation
*attempt*, before a ContentDraft row necessarily exists yet, mirroring database/models/
ai_execution.py's own surrogate-PK-plus-indexed-FK convention for pre-draft, per-attempt data
(the same reasoning services/story_context.py's story_context_snapshots table already
established for Phase 19 M7).

`content_draft_id` is nullable and populated later, once the resulting draft exists (or stays
null for a shadow-mode row, since shadow never creates a real production draft dependency).
`is_deterministic_scaffold` distinguishes a real, AI-generated plan (comparison-script-only, this
phase) from the live shadow hook's zero-cost, zero-LLM-call scaffold
(services/editorial_planning_deterministic.py) - both share the same 16-field shape, so they
remain directly comparable.
"""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ContentDraftEditorialPlan(Base):
    __tablename__ = "content_draft_editorial_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False, index=True
    )
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True, index=True
    )
    # The 16-field plan (prompts/editorial_planning/v1.yaml's output shape), stored as one JSON
    # blob - mirrors how EditorialTask.workflow already stores structured step output as JSON,
    # rather than 16 individual columns for data that is always read/written as one unit.
    plan: Mapped[dict] = mapped_column(JSON, nullable=False)
    is_deterministic_scaffold: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # services/editorial_planning_safety.py's PlanSafetyReport, persisted for review - never
    # re-derived from the plan alone without also knowing what evidence it was checked against.
    safety_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    safety_failed_checks: Mapped[list | None] = mapped_column(JSON, nullable=True)
    selected_editorial_text_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
