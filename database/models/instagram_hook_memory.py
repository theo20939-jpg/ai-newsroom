"""INSTAGRAM-GROWTH-3, item 2/10: persisted Hook Intelligence evidence + Creative Fatigue history.

Two separate tables, matching two separate accepted concepts:
- `InstagramHookEvidenceRecord` persists a `services/instagram_content_brain.py::PerformancePattern`
  per (dimension, value) pair, so `advance_evidence_stage()` (the accepted anti-overfit gate) can be
  re-run as more samples accumulate over time, instead of being recomputed from scratch each call
  with no memory of prior samples.
- `InstagramFatigueObservation` is an APPEND-ONLY history of
  `services/instagram_content_brain.py::evaluate_fatigue_state()` results - "history" means every
  observation is kept, not just the latest.

CRITICAL (item 10): `dimension` is a plain string ("hook_family" | "format" | "objective" |
"audience_segment" | "topic" | ...) - each row tracks exactly ONE dimension's evidence, mirroring
`CreativeFatigueSignal.dimension`'s own established "never blend dimensions" discipline. A causal
hook-family rule and a causal topic rule are always two separate rows, never combined into one."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Float, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EvidenceStage(str, enum.Enum):
    """Mirrors services/instagram_content_brain.py::EvidenceStage's values exactly (that module
    stays the single accepted, non-persisted definition - database/models/*.py never imports from
    services/*.py in this codebase, so this Postgres-column-facing copy exists the same way
    database/models/competitor.py::ObservationSource has its own copy rather than a service-layer
    import; services/instagram_hook_memory.py converts by `.value` at the persistence boundary)."""

    ANOMALY = "anomaly"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"
    STABLE_WORKING_RULE = "stable_working_rule"


class FatigueState(str, enum.Enum):
    """Mirrors services/instagram_content_brain.py::FatigueState's values exactly - see
    `EvidenceStage` above for why this is a deliberate persistence-layer copy, not an import."""

    FRESH = "fresh"
    NORMAL = "normal"
    REPEATED = "repeated"
    FATIGUED = "fatigued"
    OVERUSED = "overused"


class InstagramHookEvidenceRecord(Base):
    __tablename__ = "instagram_hook_evidence_records"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dimension: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False, index=True)

    sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    effect_size: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    repeatability: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    recency_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    evidence_stage: Mapped[EvidenceStage] = mapped_column(
        Enum(EvidenceStage, name="instagram_hook_evidence_stage", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=EvidenceStage.ANOMALY,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("dimension", "value", name="uq_instagram_hook_evidence_dimension_value"),
    )


class InstagramFatigueObservation(Base):
    __tablename__ = "instagram_fatigue_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    dimension: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    repetition_count: Mapped[int] = mapped_column(Integer, nullable=False)
    window_days: Mapped[int] = mapped_column(Integer, nullable=False)
    fatigue_state: Mapped[FatigueState] = mapped_column(
        Enum(FatigueState, name="instagram_fatigue_state", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
