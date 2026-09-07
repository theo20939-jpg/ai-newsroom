"""DIRECTOR-CONTROL-PLANE-1 §8-13/§47: DirectorEditorialDecision - the persisted, explainable
output of the internal editorial gate (services/director_editorial_gate.py). INTERNAL ONLY (spec
§8's own explicit "does NOT publish publicly" instruction) - this table has no relationship to any
publication path; it only ever gates whether a Story reaches the Founder/editorial NEWS queue
inside worker/content_cycle.py, behind settings.telegram_editorial_gate_enabled (default False).

A HOLD-decision row IS the bounded HOLD queue (spec §13) - no separate table. `expires_at` bounds
it; a caller queries `decision == HOLD AND (expires_at IS NULL OR expires_at > now)` for "still
live" holds, exactly mirroring database/models/business_context_proposal.py's own established
"status column + explicit expiry field, no second queue table" convention."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class EditorialGateDecision(str, enum.Enum):
    """Spec §8's own canonical five decisions - exhaustive, no sixth value."""

    DROP = "drop"
    HOLD = "hold"
    SEND_TO_EDITOR = "send_to_editor"
    PRIORITY = "priority"
    BREAKING = "breaking"


class EditorialGateReasonCode(str, enum.Enum):
    """Spec §10's own listed examples, exhaustive for this phase - never free-form-only reasoning
    (spec's own "Do not rely only on free-form prose" instruction). `short_reason` on the decision
    row still carries a human-readable sentence, but it is always ANCHORED to at least one of these
    codes, never the sole explanation."""

    HIGH_STRATEGIC_FIT = "high_strategic_fit"
    DUPLICATE_TOPIC = "duplicate_topic"
    LOW_NOVELTY = "low_novelty"
    SOURCE_WEAK = "source_weak"
    FEED_GAP_FILL = "feed_gap_fill"
    CAMPAIGN_RELEVANT = "campaign_relevant"
    BREAKING_SIGNAL = "breaking_signal"
    TOO_NICHE = "too_niche"
    TOO_FINANCE_HEAVY = "too_finance_heavy"
    INSUFFICIENT_FACTS = "insufficient_facts"
    RECENTLY_COVERED = "recently_covered"
    MAJOR_INDUSTRY_EVENT = "major_industry_event"
    FOUNDER_DIRECTIVE_MATCH = "founder_directive_match"
    LLM_UNAVAILABLE_FALLBACK = "llm_unavailable_fallback"


class DirectorEditorialDecision(Base):
    __tablename__ = "director_editorial_decisions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    # No FK constraint (mirrors database/models/telegram_visual_failure.py's own established "this
    # table's own purpose must survive independently of whether the referenced row still exists"
    # convention) - a story_id here may reference database/models/story.py::Story.id.
    story_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)

    decision: Mapped[EditorialGateDecision] = mapped_column(
        Enum(EditorialGateDecision, name="editorial_gate_decision", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    reason_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    short_reason: Mapped[str] = mapped_column(Text, nullable=False)

    director: Mapped[str] = mapped_column(String(100), nullable=False)
    director_version: Mapped[str] = mapped_column(String(20), nullable=False, default="v1")

    context_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    launch_context_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    campaign_context_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Spec §13: bounds the HOLD queue - NULL means "no automatic expiry" (still bounded by an
    # operator/console sweep, never an unbounded background LLM loop per spec's own instruction).
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Spec §47: Founder override support - the ORIGINAL decision above is never mutated in place
    # (mirrors this codebase's own established "append-only, never silently rewritten" convention,
    # e.g. database/models/social_launch_context.py) - an override is recorded as a delta on the
    # SAME row (this table's own single-decision-per-candidate shape makes a second append-only
    # row unnecessary), never as a second competing DirectorEditorialDecision for the same story.
    founder_overridden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    founder_override_decision: Mapped[EditorialGateDecision | None] = mapped_column(
        Enum(EditorialGateDecision, name="editorial_gate_decision", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    founder_override_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    founder_override_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
