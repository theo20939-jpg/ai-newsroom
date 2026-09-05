"""INSTAGRAM-GROWTH-3, item 6/8: CreativePlan/CreativeDraft - AI creative output persisted as a
PROPOSAL, never as canonical business truth. `InstagramCreativePlan` is the planning envelope
(references BusinessContext/CampaignPlan state AS OF planning time, mirrors
database/models/instagram_calendar_item.py::planned_against_campaign_status/phase's own
context-versioning discipline); `InstagramCreativeDraft` is the actual generated content (one plan
may accumulate multiple draft attempts/regenerations, only ever a proposal until a human approves
it - `status` never auto-flips to APPROVED anywhere in the service layer)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class CreativePlanStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class CreativeDraftStatus(str, enum.Enum):
    PROPOSED = "proposed"
    APPROVED = "approved"
    REJECTED = "rejected"


class InstagramCreativePlan(Base):
    __tablename__ = "instagram_creative_plans"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    content_opportunity_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=True, index=True
    )
    series_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instagram_series.id"), nullable=True, index=True
    )

    objective: Mapped[str] = mapped_column(String(50), nullable=False)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    hook_family: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Business-truth versioning AS OF planning time (item 8) - mirrors
    # instagram_content_calendar_items.planned_against_campaign_status/phase exactly.
    business_context_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    campaign_state_snapshot: Mapped[str | None] = mapped_column(String(200), nullable=True)

    status: Mapped[CreativePlanStatus] = mapped_column(
        Enum(CreativePlanStatus, name="instagram_creative_plan_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=CreativePlanStatus.PROPOSED, index=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class InstagramCreativeDraft(Base):
    __tablename__ = "instagram_creative_drafts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    creative_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("instagram_creative_plans.id"), nullable=False, index=True
    )
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    # The generated creative content itself (SinglePostPackage/CarouselPackage/ReelPackage-shaped
    # dict) - a PROPOSAL, never written back into any canonical business-truth table.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    approved_claims: Mapped[list | None] = mapped_column(JSON, nullable=True)
    restricted_claims: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # Every factual bullet the draft actually cites, each required to be a member of the caller's
    # own supplied evidence set (services/instagram_creative_director.py::assert_evidence_grounded)
    # - never a fact the AI introduced on its own.
    evidence_used: Mapped[list | None] = mapped_column(JSON, nullable=True)

    ai_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ai_capability: Mapped[str | None] = mapped_column(String(50), nullable=True)
    ai_cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)

    status: Mapped[CreativeDraftStatus] = mapped_column(
        Enum(CreativeDraftStatus, name="instagram_creative_draft_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=CreativeDraftStatus.PROPOSED,
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
