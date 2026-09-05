"""NINJA Social Intelligence Foundation, Part I §11: CampaignMilestone/ProductMilestone. A
milestone is context, NOT an instruction to publish (module docstring of product_event.py makes
the identical point for ProductEvent) - `publicity_allowed`/`asset_preparation_allowed` are the
explicit, separately-gated permissions a director must check before acting on a milestone at all,
distinct from `visibility` (which describes the milestone's own sensitivity, not what a director
may currently DO about it)."""
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.business_context_shared import Visibility


class CampaignMilestone(Base):
    """One row per milestone. `campaign_id` is optional (spec §11: "campaign_id optional") - a
    milestone can exist purely as product context before any campaign is even drafted."""

    __tablename__ = "campaign_milestones"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    # Free-text type (spec §11 lists no fixed vocabulary for milestone "type", unlike ProductEvent's
    # own explicit event_type taxonomy) - e.g. "internal_acceptance", "design_review".
    type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    milestone_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    importance: Mapped[int] = mapped_column(nullable=False, default=100)
    visibility: Mapped[Visibility] = mapped_column(
        Enum(Visibility, name="campaign_milestone_visibility", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=Visibility.INTERNAL_ONLY, index=True,
    )
    publicity_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    asset_preparation_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
