"""Phase 16 M5: durable audit persistence for Image Intelligence candidates (docs/
phase16_m5_persistence_and_retention_report.md). Deliberately named `ImageCandidateRecord`, not
`ImageCandidate` - that name is already the M1-M4 in-memory Pydantic contract
(`schemas.image_candidate.ImageCandidate`); this is the separate, additive, durable ORM row a
bounded subset of that contract gets converted into by `services/image_persistence.py`. One table
only (`image_candidates`) - see the M5 report §4 for why a second `image_assets` table was
evaluated and rejected in favor of a live reference-count query at cleanup time.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.news_source import SourceType


class ImageQualityStatus(str, enum.Enum):
    """Mirrors schemas.image_candidate.QualityStatus (M3) - a separate DB-native enum so the M3
    Pydantic contract can evolve independently of this durable audit row's own migration history."""

    ACCEPTED = "accepted"
    REJECTED_QUALITY = "rejected_quality"
    DUPLICATE_EXACT = "duplicate_exact"
    DUPLICATE_NEAR = "duplicate_near"
    REVIEW = "review"


class ImageRelevanceStatus(str, enum.Enum):
    """Mirrors schemas.image_candidate.RelevanceStatus (M4)."""

    RANKED = "ranked"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    INELIGIBLE = "ineligible"


class ImageStorageStatus(str, enum.Enum):
    """M5's own explicit state machine (report §18). `NOT_REQUESTED` is the default for every
    non-finalist candidate (the overwhelming majority) - storage was never attempted, which is
    distinct from `FAILED` (attempted and failed) or `MISSING` (was `STORED`, but the file is gone
    at reconciliation time, e.g. after an out-of-band deletion)."""

    NOT_REQUESTED = "not_requested"
    PENDING = "pending"
    STORED = "stored"
    FAILED = "failed"
    EXPIRED = "expired"
    MISSING = "missing"


def _enum_values(enum_cls: type[enum.Enum]) -> list[str]:
    """SQLAlchemy's `Enum(python_enum_cls)` stores each member's `.name` (e.g. "ACCEPTED") by
    default, not `.value` - but every M3/M4 Pydantic status enum this module mirrors uses
    lowercase `.value`s (e.g. `QualityStatus.ACCEPTED.value == "accepted"`). `values_callable`
    makes the DB-stored/compared string match `.value`, keeping this table's stored strings
    identical to what M1-M4's own JSON contract already uses everywhere else (logs, step_results)."""
    return [member.value for member in enum_cls]


class ImageCandidateRecord(Base):
    """One durable audit row per M1-M4 candidate that reached the bounded per-event result -
    additive, append-mostly (see report §17 for the idempotent-upsert rule). Never contains image
    bytes (`storage_key` is an internal reference only, report §7); never contains Telethon
    session/access_hash material, cookies, or authorization headers (report §21)."""

    __tablename__ = "image_candidates"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[str] = mapped_column(String, nullable=False)
    news_event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("news_events.id"), nullable=False, index=True
    )
    editorial_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=True, index=True
    )
    # Reserved for future (M6+) population once a ContentDraft exists at persistence time - always
    # NULL when written by M5's own integration point (report §3: no ContentDraft exists yet at the
    # "copywriting" step).
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=True, index=True
    )

    # --- origin (report §20's "URL sanitization" applies to every *_url column below) ---
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, name="source_type"), nullable=False)
    discovery_method: Mapped[str] = mapped_column(String, nullable=False)
    source_name: Mapped[str | None] = mapped_column(String, nullable=True)
    article_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    remote_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    final_url: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- provenance (M4) ---
    provenance_confidence: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_relationship: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- technical metadata (M2) ---
    observed_mime: Mapped[str | None] = mapped_column(String, nullable=True)
    image_format: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pixel_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    aspect_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    animated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    frame_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    perceptual_hash: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # --- quality (M3) ---
    quality_status: Mapped[ImageQualityStatus | None] = mapped_column(
        Enum(ImageQualityStatus, name="image_quality_status", values_callable=_enum_values),
        nullable=True, index=True,
    )
    quality_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    quality_hard_rejection_reasons: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_warnings: Mapped[list | None] = mapped_column(JSON, nullable=True)
    quality_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- deduplication (M3) ---
    exact_cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    near_duplicate_cluster_id: Mapped[str | None] = mapped_column(String, nullable=True)
    # Informational only, not a DB-enforced FK - candidate_id is unique only within one
    # (news_event_id, run), not globally stable across reruns (report §17).
    duplicate_of_candidate_id: Mapped[str | None] = mapped_column(String, nullable=True)
    is_representative: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- relevance (M4) ---
    relevance_status: Mapped[ImageRelevanceStatus | None] = mapped_column(
        Enum(ImageRelevanceStatus, name="image_relevance_status", values_callable=_enum_values),
        nullable=True, index=True,
    )
    relevance_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    eligible_for_editorial: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    relevance_components: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relevance_penalties: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relevance_coverage: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relevance_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- storage (M5) ---
    storage_status: Mapped[ImageStorageStatus] = mapped_column(
        Enum(ImageStorageStatus, name="image_storage_status", values_callable=_enum_values),
        nullable=False, default=ImageStorageStatus.NOT_REQUESTED, index=True,
    )
    storage_key: Mapped[str | None] = mapped_column(String, nullable=True)
    stored_byte_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    stored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    storage_error_code: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- lifecycle ---
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    # Metadata-row expiry (report §14) - independent of, and normally later than, bytes_expire_at.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    # Stored-bytes expiry - distinct from expires_at so bytes can be reclaimed while audit metadata
    # (SHA-256, provenance, scores) survives longer, per the brief's own explicit requirement.
    bytes_expire_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    __table_args__ = (
        UniqueConstraint("news_event_id", "candidate_id", name="uq_image_candidates_event_candidate"),
        CheckConstraint("rank IS NULL OR rank > 0", name="ck_image_candidates_rank_positive"),
        CheckConstraint(
            "relevance_score IS NULL OR (relevance_score >= 0 AND relevance_score <= 100)",
            name="ck_image_candidates_relevance_score_range",
        ),
        CheckConstraint(
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
            name="ck_image_candidates_quality_score_range",
        ),
        CheckConstraint("width IS NULL OR width >= 0", name="ck_image_candidates_width_non_negative"),
        CheckConstraint("height IS NULL OR height >= 0", name="ck_image_candidates_height_non_negative"),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="ck_image_candidates_byte_size_non_negative"),
        CheckConstraint(
            "stored_byte_size IS NULL OR stored_byte_size >= 0",
            name="ck_image_candidates_stored_byte_size_non_negative",
        ),
        CheckConstraint(
            "storage_status != 'stored' OR storage_key IS NOT NULL",
            name="ck_image_candidates_storage_key_required_when_stored",
        ),
        Index("ix_image_candidates_top_candidate", "news_event_id", "eligible_for_editorial", "rank"),
    )
