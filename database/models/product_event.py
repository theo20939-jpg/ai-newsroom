"""NINJA Social Intelligence Foundation, Part I §7: structured product events (milestones,
launches, incidents, ...). A ProductEvent is context, never an instruction to publish anything -
`visibility` (database/models/business_context_shared.py::Visibility) is the explicit safety
field preventing an internal-only event from leaking into public social output merely because
directors can see it exists."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.business_context_shared import Visibility


class ProductEventType(str, enum.Enum):
    """Spec §7's own suggested taxonomy, preserved verbatim."""

    DEVELOPMENT_STARTED = "development_started"
    MILESTONE_REACHED = "milestone_reached"
    PRIVATE_BETA = "private_beta"
    PUBLIC_BETA = "public_beta"
    FEATURE_READY = "feature_ready"
    PRICING_APPROVED = "pricing_approved"
    LAUNCH_DATE_CONFIRMED = "launch_date_confirmed"
    LAUNCH_DELAYED = "launch_delayed"
    PRODUCT_LAUNCHED = "product_launched"
    MAJOR_UPDATE = "major_update"
    PARTNERSHIP = "partnership"
    PROMOTION = "promotion"
    INCIDENT = "incident"


class ProductEvent(Base):
    """One row per structured product event. `importance` mirrors Product.priority's own bare-int
    style (lower = more important) rather than a fixed enum, for the same reason: spec §7 lists it
    with no suggested vocabulary."""

    __tablename__ = "product_events"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    event_type: Mapped[ProductEventType] = mapped_column(
        Enum(ProductEventType, name="product_event_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    event_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    importance: Mapped[int] = mapped_column(nullable=False, default=100)
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="product_event_visibility", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=Visibility.INTERNAL_ONLY, index=True,
    )
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="telegram")
    raw_instruction: Mapped[str | None] = mapped_column(String, nullable=True)
    structured_payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
