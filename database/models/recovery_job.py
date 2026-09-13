"""RecoveryJob ORM model (UNIFIED-EDITORIAL-PRODUCTION-PIPELINE-CUTOVER-1, §9).

The durable backing for `services.editorial_pipeline.recovery_service.RecoveryService` - the prior
phase's own `services.editorial_pipeline.contracts.RecoveryJob` was an in-process-only dataclass
with no persistence at all (disclosed explicitly in that phase's own report and confirmed by the
Founder review: "do not pretend an in-memory state machine is durable"). This table is the real
persistence: one row per (content_draft_id, platform) recovery lifecycle, surviving a worker
restart/process death.

Never stores secrets or full raw payloads (§9's own explicit instruction) - `last_error_summary` is
bounded to 500 characters (the exception's own `str()`, never a full traceback or request/response
body), and `candidate_diagnostics` (a short list of human-readable rejection reasons, already the
shape `services.editorial_pipeline.contracts.RecoveryJob.candidate_diagnostics` used) is stored as
plain JSON strings, never raw candidate objects.

Surrogate PK, one row per attempt-cycle (not reused across a fresh recovery for the same draft) -
mirrors `database/models/content_draft_editorial_plan.py`'s own established convention for
per-attempt data. `content_draft_id` is NOT unique alone (a draft can accumulate more than one
RecoveryJob row over its lifetime, e.g. one for a render failure and, if that resolves, a later one
for a caption-budget failure) - `(content_draft_id, state)` is the meaningful lookup for "does this
draft have an open recovery" (services/editorial_pipeline/recovery_service.py's own query).
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class RecoveryPlatform(str, enum.Enum):
    TELEGRAM = "telegram"
    INSTAGRAM = "instagram"


class RecoveryReasonCode(str, enum.Enum):
    """Mirrors `services.editorial_pipeline.contracts.RecoveryReasonCode` exactly - kept as an
    independent enum here (not imported from that module) so this DB model has no import-time
    dependency on the in-process package, matching `database/models/`'s own established
    "models never import from services/" convention (confirmed by inspecting every other model in
    this directory - none imports from `services.*`)."""

    NO_SUITABLE_MEDIA = "NO_SUITABLE_MEDIA"
    MEDIA_RESEARCH_TIMEOUT = "MEDIA_RESEARCH_TIMEOUT"
    MEDIA_SEND_FAILED = "MEDIA_SEND_FAILED"
    AMBIGUOUS_TRANSPORT_RESULT = "AMBIGUOUS_TRANSPORT_RESULT"
    CAPTION_BUDGET_FAILED = "CAPTION_BUDGET_FAILED"
    RENDER_FAILED = "RENDER_FAILED"
    QUALITY_GATE_FAILED = "QUALITY_GATE_FAILED"


class RecoveryJobState(str, enum.Enum):
    """The real, live states (cutover phase §8) - `PENDING` is the initial state for a job that has
    not yet had its first retry attempt scheduled (distinct from `RETRYING`, which means at least
    one retry has actually been scheduled/attempted)."""

    PENDING = "PENDING"
    RETRYING = "RETRYING"
    RECOVERED = "RECOVERED"
    TERMINAL_HOLD = "TERMINAL_HOLD"


class RecoveryJob(Base):
    __tablename__ = "recovery_jobs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_draft_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("content_drafts.id"), nullable=False, index=True
    )
    platform: Mapped[RecoveryPlatform] = mapped_column(Enum(RecoveryPlatform, name="recovery_platform"), nullable=False)
    reason_code: Mapped[RecoveryReasonCode] = mapped_column(Enum(RecoveryReasonCode, name="recovery_reason_code"), nullable=False)
    failed_stage: Mapped[str] = mapped_column(String(100), nullable=False)
    state: Mapped[RecoveryJobState] = mapped_column(
        Enum(RecoveryJobState, name="recovery_job_state"), nullable=False, default=RecoveryJobState.PENDING, index=True
    )
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_summary: Mapped[str | None] = mapped_column(String(500), nullable=True)
    candidate_diagnostics: Mapped[list | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
