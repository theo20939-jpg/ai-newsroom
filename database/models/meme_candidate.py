"""Phase 18 M2: durable persistence for one meme attempt across the whole MEME_GENERATION
pipeline (docs/phase18_m0_meme_discovery_report.md §7, docs/phase18_m2_meme_concept_report.md).

The one migration this phase needs (M0 report §7's own reasoning): `EditorialTask.workflow`
(JSON) is `WorkflowRunner`'s own transient execution-state snapshot, not a durable, queryable
business record - mirrors the exact reasoning that already justified `ImageCandidateRecord`
(Phase 16 M5) over an equivalent JSON-only approach. `MemeCandidate` is that table's direct
architectural sibling: one evolving row per meme attempt, columns reserved ahead of the milestone
that populates them (mirroring `ImageCandidateRecord.content_draft_id`'s own "Reserved for future
M6+ population" precedent) rather than one migration per milestone. Every stage's columns are
documented below with which milestone populates them; only M2's own concept columns are written
as of this migration.
"""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class MemeCandidateStatus(str, enum.Enum):
    """The pipeline stage this row has reached - advanced by exactly one service call per
    milestone (never skipped, never rewound except by an explicit regenerate step). `None` is
    never a valid value once a row exists - `CONCEPT_GENERATED` is the initial status, set at
    creation (M2)."""

    CONCEPT_GENERATED = "concept_generated"
    SAFETY_BLOCKED = "safety_blocked"  # M3
    SAFETY_REVIEW = "safety_review"  # M3
    COPY_GENERATED = "copy_generated"  # M4
    IMAGE_GENERATED = "image_generated"  # M5
    IMAGE_FAILED = "image_failed"  # M5
    RENDERED = "rendered"  # M6
    QUALITY_READY = "quality_ready"  # M7
    QUALITY_REVIEW = "quality_review"  # M7
    QUALITY_REJECTED = "quality_rejected"  # M7
    PENDING_EDITOR = "pending_editor"  # M8
    APPROVED = "approved"  # M9
    REJECTED = "rejected"  # M9


class MemeCandidate(Base):
    """One row per meme attempt for one NewsEvent. Multiple rows per `news_event_id` are
    expected and valid (a regenerated concept is a new row, never an in-place rewrite of the
    concept fields - `schemas.meme_concept.MemeConcept`'s own "frozen" discipline extends to its
    persisted form). Never contains raw image bytes (`image_storage_key`/`render_storage_key` are
    references into `integrations.storage.image_storage.ImageStorage`, mirroring
    `ImageCandidateRecord.storage_key`'s identical discipline)."""

    __tablename__ = "meme_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    news_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False, index=True
    )
    # The MEME_GENERATION EditorialTask this candidate belongs to - nullable only for the
    # unreachable-in-practice case of a candidate row created before its owning task committed;
    # every real write path (services/meme_candidate_service.py) always supplies it.
    editorial_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=True, index=True
    )
    # Populated only once a human approves (M9) - mirrors ImageCandidateRecord.content_draft_id's
    # own "reserved for future population" precedent exactly.
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True, index=True
    )

    status: Mapped[MemeCandidateStatus] = mapped_column(
        Enum(MemeCandidateStatus, name="meme_candidate_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=MemeCandidateStatus.CONCEPT_GENERATED, index=True,
    )

    # --- concept (M2) ---
    concept_schema_version: Mapped[str] = mapped_column(String, nullable=False)
    concept_data: Mapped[dict] = mapped_column(JSON, nullable=False)
    concept_regeneration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- safety & originality (M3) - reserved, populated starting M3 ---
    safety_status: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    safety_reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    originality_status: Mapped[str | None] = mapped_column(String, nullable=True)
    originality_reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # --- copywriting (M4) - reserved, populated starting M4 ---
    copy_schema_version: Mapped[str | None] = mapped_column(String, nullable=True)
    copy_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    copy_regeneration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- image generation (M5) - reserved, populated starting M5 ---
    image_status: Mapped[str | None] = mapped_column(String, nullable=True)
    image_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    image_provider: Mapped[str | None] = mapped_column(String, nullable=True)
    image_model: Mapped[str | None] = mapped_column(String, nullable=True)
    image_regeneration_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # --- rendering / text overlay (M6) - reserved, populated starting M6 ---
    render_storage_key: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- quality gate (M7) - reserved, populated starting M7 ---
    quality_decision: Mapped[str | None] = mapped_column(String, nullable=True)
    quality_reason_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- human decision / feedback (M9) - reserved, populated starting M9 ---
    editor_decision: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    editor_decision_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    editor_decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    editor_decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Always False until a real autopublish capability exists (none does in this phase - docs/
    # phase18_m0_meme_discovery_report.md's own "nothing publishes automatically" invariant).
    published: Mapped[bool] = mapped_column(nullable=False, default=False)

    # --- cost (cumulative across every LLM/image call this candidate has incurred) ---
    cumulative_cost_usd: Mapped[Decimal] = mapped_column(Numeric(precision=12, scale=6), nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_meme_candidates_quality_score_range",
        ),
        CheckConstraint("concept_regeneration_count >= 0", name="ck_meme_candidates_concept_regen_non_negative"),
        CheckConstraint("copy_regeneration_count >= 0", name="ck_meme_candidates_copy_regen_non_negative"),
        CheckConstraint("image_regeneration_count >= 0", name="ck_meme_candidates_image_regen_non_negative"),
        CheckConstraint("cumulative_cost_usd >= 0", name="ck_meme_candidates_cost_non_negative"),
    )
