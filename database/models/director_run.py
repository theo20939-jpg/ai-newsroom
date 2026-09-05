"""SOCIAL-INTELLIGENCE-OPS-1, spec §29-§34: DirectorRun - a durable record of what a director
decided and why, so `/directors` can render the LATEST PERSISTED run (spec §32's own "must not
trigger a new run from a read command" instruction) and so staleness against a Business Context
that has since moved can be detected without re-deriving the original decision.

Different director types intentionally keep different `result_payload` shapes (spec §31's own
"must NOT force identical schemas for different director types" instruction) - one flexible JSON
column, not one detail table per director type, matches this phase's SHADOW/ADVISORY scope: nothing
in this codebase yet enforces or acts on a persisted DirectorRun, it is read-only observability.

`model_provider`/`model_name`/`cost_usd` stay nullable and are only ever populated when a run
actually called an LLM with a real, known cost - a deterministic run (e.g. INSTAGRAM_FORMAT's
current heuristic evaluator) leaves all three `None`, never a fabricated zero."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DirectorType(str, enum.Enum):
    TELEGRAM_CHANNEL = "telegram_channel"
    TELEGRAM_ART = "telegram_art"
    TELEGRAM_GROWTH = "telegram_growth"
    TELEGRAM_STRATEGY = "telegram_strategy"
    INSTAGRAM_GROWTH = "instagram_growth"
    INSTAGRAM_FORMAT = "instagram_format"
    INSTAGRAM_CREATIVE = "instagram_creative"
    CAMPAIGN_DIRECTOR = "campaign_director"


class DirectorRunStatus(str, enum.Enum):
    OK = "ok"
    WAITING_FOR_DATA = "waiting_for_data"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    BLOCKED = "blocked"


class DirectorRunEvidenceStage(str, enum.Enum):
    """Mirrors database/models/instagram_shared.py::IntelligenceEvidenceStage's own values exactly
    (evidence maturity from a single observation to a stable working rule) - kept as its own enum
    rather than imported from that Instagram-named module, per the established "deliberate
    duplication over cross-platform coupling" boundary (this run may just as well be a Telegram
    director's)."""

    OBSERVATION = "observation"
    HYPOTHESIS = "hypothesis"
    POSSIBLE_SIGNAL = "possible_signal"
    REPEATED_PATTERN = "repeated_pattern"
    STABLE_WORKING_RULE = "stable_working_rule"


class DirectorRun(Base):
    __tablename__ = "director_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    director_type: Mapped[DirectorType] = mapped_column(
        Enum(DirectorType, name="director_run_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    # Polymorphic subject reference (e.g. subject_type="story", subject_id=<Story.id>) - no FK,
    # mirrors database/models/telegram_content_calendar_item.py's own "no FK on a reference that
    # must survive independently of the referenced row" convention.
    subject_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    # The campaign's status/phase AT THE TIME this run was generated - the same targeted
    # "planned_against_*" comparison services/telegram_calendar_service.py/instagram_calendar_
    # service.py already use for staleness, applied here to a director decision instead of a
    # calendar item.
    campaign_status_at_run: Mapped[str | None] = mapped_column(String(30), nullable=True)
    campaign_phase_at_run: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # A coarse fingerprint of the whole BusinessContextSnapshot at run time (directives/claims/
    # campaign statuses) - a catch-all staleness signal beyond just this run's own campaign_id,
    # e.g. a NEW directive appearing should be able to mark even a campaign-less run stale.
    business_context_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # A fingerprint of the actual inputs this run's decision was computed from (e.g. story ids +
    # feed-state counters) - lets a future caller detect "same inputs, no need to recompute" too,
    # though nothing in this phase acts on that yet.
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    status: Mapped[DirectorRunStatus] = mapped_column(
        Enum(DirectorRunStatus, name="director_run_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DirectorRunStatus.OK,
    )
    decision: Mapped[str | None] = mapped_column(String(100), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    evidence_stage: Mapped[DirectorRunEvidenceStage | None] = mapped_column(
        Enum(DirectorRunEvidenceStage, name="director_run_evidence_stage", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )

    result_payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    model_provider: Mapped[str | None] = mapped_column(String(50), nullable=True)
    model_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)

    stale_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stale_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
