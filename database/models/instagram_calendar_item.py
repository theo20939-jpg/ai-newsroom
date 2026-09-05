"""INSTAGRAM GROWTH ENGINE v2, spec §39/§40/§41: InstagramContentCalendarItem - real persistence
for what the previous foundation left as an enum-only `CalendarItemStatus`
(services/instagram_growth_strategist.py). `depends_on_campaign_phase` is the field that makes
context invalidation possible without re-deriving intent from scratch: a countdown/launch item
sets it to the exact-date-dependent phase it assumes (e.g. "COUNTDOWN"/"LAUNCH"/"FEATURE_REVEAL");
a generic awareness item leaves it `None` - spec §41's own delay example ("generic AI
problem-awareness content may remain ACTIVE") is exactly what a `None` here protects."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class CalendarItemStatus(str, enum.Enum):
    ACTIVE = "active"
    STALE = "stale"
    INVALIDATED = "invalidated"
    RESCHEDULED = "rescheduled"
    DONE = "done"
    CANCELLED = "cancelled"


class InstagramContentCalendarItem(Base):
    __tablename__ = "instagram_content_calendar_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    planned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    status: Mapped[CalendarItemStatus] = mapped_column(
        Enum(CalendarItemStatus, name="instagram_calendar_item_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=CalendarItemStatus.ACTIVE, index=True,
    )

    opportunity_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    creative_concept_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # INSTAGRAM-GROWTH-3 item 8: a REAL reference to the generated proposal
    # (database/models/instagram_creative_plan.py::InstagramCreativePlan), additive alongside the
    # older free-text `creative_concept_id` above (kept for backward compatibility, never removed).
    creative_plan_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instagram_creative_plans.id"), nullable=True, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True, index=True
    )

    objective: Mapped[str] = mapped_column(String(50), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)

    # The exact-date-dependent phase this item assumes will hold true (e.g. "COUNTDOWN") - None
    # means "generic, phase-independent content" (spec §41's own required survivor).
    depends_on_campaign_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Snapshot of the campaign's own state AT PLANNING TIME - the one thing context invalidation
    # actually diffs against (spec §40's own "future content must know which Business Context
    # version it was planned against" requirement).
    planned_against_campaign_status: Mapped[str | None] = mapped_column(String(50), nullable=True)
    planned_against_campaign_phase: Mapped[str | None] = mapped_column(String(50), nullable=True)

    invalidation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
