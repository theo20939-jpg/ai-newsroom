"""DIRECTOR-CONTROL-PLANE-1 §14-15: DirectorEditorialTask - a provenance-aware editorial
opportunity a Director proposes, distinct from an ingestion-originated EditorialTask (database/
models/editorial_task.py). NOT a reuse of EditorialTask (schema-reuse report, this phase's own
final report): EditorialTask.event_id is a REQUIRED, non-nullable FK to news_events - a Director-
proposed idea has no NewsEvent until Research actually produces one (spec §15's own "no unsupported
facts from advisory prose" rule), so reusing EditorialTask would force fabricating a synthetic
NewsEvent, a worse violation of the no-invented-facts principle than one small new table.

Spec §15's own hard requirement is enforced by STATUS, not by code that could be bypassed: a
DirectorEditorialTask can only ever reach CONVERTED_TO_DRAFT after `research_event_id` is set (see
services/director_editorial_task_service.py::mark_researched() - the only function allowed to set
it) - there is no status transition anywhere that reaches CONVERTED_TO_DRAFT without first passing
through RESEARCH_REQUIRED -> RESEARCHED."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DirectorTaskReason(str, enum.Enum):
    """Spec §14's own exhaustive reason vocabulary."""

    FEED_GAP = "feed_gap"
    CAMPAIGN = "campaign"
    TREND = "trend"
    SERIES = "series"
    FOLLOW_UP = "follow_up"
    PRODUCT = "product"
    EXPLAINER = "explainer"
    OTHER = "other"


class DirectorTaskStatus(str, enum.Enum):
    PROPOSED = "proposed"
    RESEARCH_REQUIRED = "research_required"
    RESEARCHED = "researched"
    CONVERTED_TO_DRAFT = "converted_to_draft"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class DirectorEditorialTask(Base):
    __tablename__ = "director_editorial_tasks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    platform: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    proposed_topic: Mapped[str] = mapped_column(Text, nullable=False)
    why_now: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[DirectorTaskReason] = mapped_column(
        Enum(DirectorTaskReason, name="director_task_reason", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    desired_format: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Spec §14: "source/research requirement" - explicit, never assumed true by default (a Director
    # idea is presumed to need Research/fact support unless a caller explicitly states otherwise -
    # see services/director_editorial_task_service.py::create_task()'s own default=True).
    requires_research: Mapped[bool] = mapped_column(nullable=False, default=True)
    # Set ONLY by mark_researched() once a real NewsEvent/research bundle exists to back this
    # proposal - the one field the RESEARCHED/CONVERTED_TO_DRAFT status transition is gated on.
    research_event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    campaign_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    directive_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    director: Mapped[str] = mapped_column(String(100), nullable=False)
    director_run_context_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[DirectorTaskStatus] = mapped_column(
        Enum(DirectorTaskStatus, name="director_task_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DirectorTaskStatus.PROPOSED, index=True,
    )
    # spec §14 provenance requirement, also spec §45's own internal-only Founder-visible label -
    # always "director" for this table (every row here IS a Director-originated idea by
    # construction), kept as an explicit column anyway so a queue-formatting caller never has to
    # special-case "which table did this row come from" - both EditorialTask-derived and
    # DirectorEditorialTask-derived queue entries can expose the same `origin` field name.
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="director")

    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
