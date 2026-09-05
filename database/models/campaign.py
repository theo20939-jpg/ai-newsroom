"""NINJA Social Intelligence Foundation, Part I §8/§10: canonical LaunchCampaign model. Phase
derivation (§9) is deliberately NOT a stored column here - `services/campaign_planner.py::
CampaignPlanner` derives the current phase from `planned_launch_date`/`start_at`/`end_at`/`status`
+ `now` at read time, so no stored phase can ever silently drift from the dates/status that
actually define it.

CRITICAL (§8): `planned_launch_date` and `status` are deliberately independent fields - a
TENTATIVE campaign with a concrete `planned_launch_date` does NOT mean directors may treat that
date as public-safe. `date_confidence` makes this machine-checkable, not just a code-review
convention."""
import enum
import uuid
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class CampaignStatus(str, enum.Enum):
    """Spec §8's own suggested lifecycle, preserved verbatim."""

    DRAFT = "draft"
    TENTATIVE = "tentative"
    CONFIRMED = "confirmed"
    DELAYED = "delayed"
    CANCELLED = "cancelled"
    LAUNCHED = "launched"
    COMPLETED = "completed"


class DateConfidence(str, enum.Enum):
    """Separate from `CampaignStatus` on purpose (§8's own "date and confidence are separate"
    requirement) - a campaign can be CONFIRMED in status while its date is still only ESTIMATED
    (e.g. "confirmed for early October, exact day pending")."""

    EXACT = "exact"
    ESTIMATED = "estimated"
    ROUGH = "rough"
    UNKNOWN = "unknown"


class LaunchCampaign(Base):
    """One row per product launch/marketing campaign. List-shaped advisory fields
    (target_audiences/secondary_goals/key_messages/approved_claims/restricted_claims/
    available_assets) use plain JSON, matching Product's own established list-field convention -
    `approved_claims`/`restricted_claims` here are a campaign-level convenience cache; the
    queryable-by-date authority for claim policy is `ClaimPolicy` (claim_policy.py), never this
    column alone (see services/claim_policy_service.py)."""

    __tablename__ = "launch_campaigns"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(300), nullable=False)
    objective: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus, name="campaign_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=CampaignStatus.DRAFT, index=True,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    planned_launch_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    date_confidence: Mapped[DateConfidence] = mapped_column(
        Enum(DateConfidence, name="campaign_date_confidence", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=DateConfidence.UNKNOWN,
    )

    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    target_audiences: Mapped[list | None] = mapped_column(JSON, nullable=True)
    primary_goal: Mapped[str | None] = mapped_column(String(300), nullable=True)
    secondary_goals: Mapped[list | None] = mapped_column(JSON, nullable=True)

    key_messages: Mapped[list | None] = mapped_column(JSON, nullable=True)
    approved_claims: Mapped[list | None] = mapped_column(JSON, nullable=True)
    restricted_claims: Mapped[list | None] = mapped_column(JSON, nullable=True)
    required_cta: Mapped[str | None] = mapped_column(String(300), nullable=True)

    available_assets: Mapped[list | None] = mapped_column(JSON, nullable=True)
    embargo_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
