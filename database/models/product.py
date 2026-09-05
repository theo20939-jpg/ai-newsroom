"""NINJA Social Intelligence Foundation, Part I §5: canonical Product model. One row per NINJA
product (VPN/AI/Store/Games/...) - the stable identity `ProductContextVersion`/`ProductEvent`/
`LaunchCampaign` all FK against. This row itself carries only the CURRENT confirmed snapshot of
each field; the full provenance/history of how it got there lives in `ProductContextVersion`
(§6) - this table is never the audit trail.

Mirrors database/models/event_recap_review.py's own conventions exactly: `Mapped[...]`/
`mapped_column`, client-side `uuid.uuid4()` PK, the fixed two-column `created_at`/`updated_at`
timestamp idiom, a `str, enum.Enum` declared above the model and mapped via SQLAlchemy's own
`Enum(..., values_callable=...)`."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ProductStatus(str, enum.Enum):
    """Spec §5's own suggested lifecycle - preserved verbatim, not renamed (no existing repo
    convention conflicts with these names)."""

    IDEA = "idea"
    DISCOVERY = "discovery"
    DEVELOPMENT = "development"
    PRIVATE_BETA = "private_beta"
    PUBLIC_BETA = "public_beta"
    PRE_LAUNCH = "pre_launch"
    LIVE = "live"
    PAUSED = "paused"
    SUNSET = "sunset"


class Product(Base):
    """One row per NINJA product. `slug` is the stable, human-typed identifier Telegram commands
    reference (e.g. "ai", "vpn", "store", "games") - `id` (UUID) is still the real FK target for
    every other table, `slug` is a convenience lookup column only."""

    __tablename__ = "products"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[ProductStatus] = mapped_column(
        Enum(ProductStatus, name="product_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=ProductStatus.IDEA, index=True,
    )
    # Free-text current-stage label (spec §5 "current_stage") - deliberately NOT another enum:
    # a founder's own short description of where things stand ("waiting on App Store review")
    # does not fit a fixed vocabulary the way `status` does. `status` is the queryable/authoritative
    # lifecycle stage; `current_stage` is a human-readable annotation on top of it.
    current_stage: Mapped[str | None] = mapped_column(Text, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    # List-shaped fields use plain JSON (Mapped[list | None]), matching Story.entities/.keywords'
    # own established convention - never a separate join table for a simple string list.
    core_value_propositions: Mapped[list | None] = mapped_column(JSON, nullable=True)
    current_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    planned_features: Mapped[list | None] = mapped_column(JSON, nullable=True)
    pricing_status: Mapped[str | None] = mapped_column(String(200), nullable=True)
    product_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    waitlist_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # Plain integer priority (lower = more urgent), mirroring TaskPriority's own ordinal-not-label
    # spirit but kept as a bare int here rather than a new enum - spec §5 lists "priority" with no
    # suggested fixed vocabulary, unlike `status`.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_products_slug"),
    )
