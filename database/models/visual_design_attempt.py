"""VISUAL-DESIGN-AUTONOMY-1, spec §14/§47: VisualDesignAttempt - one row per real attempt inside
the per-post design loop (services/visual_design_loop.py). Deliberately serves BOTH roles the spec
names separately (§14 VisualDesignMemory and §47 VisualDesignAttempt) - the two required field sets
are identical (story/platform/presentation, brief version, creative direction, prompt, model,
render reference, Art Director outcome, issue codes, revision count via `attempt_number` itself,
cost, publication/performance relationship once known), and this codebase's own established
"deliberate duplication over cross-platform coupling" boundary only applies across PLATFORMS, never
within one already-cohesive concept - a second, overlapping table here would just be two competing
sources of truth for the same rows.

No FK on story_id/final_post_review_id (mirrors database/models/telegram_visual_failure.py's own
identical "no FK, this table's own purpose must survive independently of whether the referenced row
still exists" convention); brief_version_id DOES carry a real FK since a brief version row is never
deleted (spec §20)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class VisualDesignAttemptStatus(str, enum.Enum):
    CREATED = "created"
    RENDERED = "rendered"
    PASSED = "passed"
    REWORK = "rework"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"
    HUMAN_REVIEW = "human_review"


class VisualFailureRootCause(str, enum.Enum):
    """Spec §23: light, routing-only taxonomy - never a creative constraint. See
    services/visual_root_cause.py::classify_root_cause() for the real classifier."""

    DESIGN_DIRECTION = "design_direction"
    SOURCE_MEDIA = "source_media"
    GENERATION_MODEL = "generation_model"
    RENDERER = "renderer"
    OVERLAY = "overlay"
    FACTUAL = "factual"
    UNKNOWN = "unknown"


class VisualDesignAttempt(Base):
    __tablename__ = "visual_design_attempts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    story_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    final_post_review_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    presentation_type: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    brief_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visual_designer_brief_versions.id"), nullable=True, index=True,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    creative_direction: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    prompt_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_media_decision: Mapped[str | None] = mapped_column(String(50), nullable=True)

    generation_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    generation_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    art_director_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    creative_reasoning_cost: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_cost: Mapped[float | None] = mapped_column(Float, nullable=True)

    render_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    art_decision: Mapped[str | None] = mapped_column(String(30), nullable=True)
    issue_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    root_cause: Mapped[VisualFailureRootCause | None] = mapped_column(
        Enum(VisualFailureRootCause, name="visual_failure_root_cause", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    status: Mapped[VisualDesignAttemptStatus] = mapped_column(
        Enum(VisualDesignAttemptStatus, name="visual_design_attempt_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=VisualDesignAttemptStatus.CREATED, index=True,
    )

    publication_outcome: Mapped[str | None] = mapped_column(String(50), nullable=True)
    performance_relationship: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
