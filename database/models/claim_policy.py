"""NINJA Social Intelligence Foundation, Part I §13: explicit product claim policy. Deliberately
NEVER conflates "true internally" with "approved for public communication" (module's own
recurring theme, shared with Visibility) - a claim with no ClaimPolicy row for a given product is
NOT implicitly APPROVED; services/claim_policy_service.py's own query treats "no matching row" as
"unknown, do not assume approved", never a permissive default."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ClaimStatus(str, enum.Enum):
    APPROVED = "approved"
    RESTRICTED = "restricted"
    EMBARGOED = "embargoed"


class ClaimPolicy(Base):
    """One row per claim statement. `campaign_id` optional (a claim policy may exist independent
    of any specific campaign - spec §13's own product-scoped examples). `embargoed_until` is only
    meaningful when `status == EMBARGOED` - services/claim_policy_service.py's own query is what
    actually resolves "is this claim currently approved AS OF `now`", never a raw status read
    alone (an EMBARGOED claim whose embargo has already passed must resolve as effectively
    APPROVED at query time, without requiring a separate confirmation to flip the stored status)."""

    __tablename__ = "claim_policies"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    campaign_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("launch_campaigns.id"), nullable=True, index=True
    )
    claim_text: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[ClaimStatus] = mapped_column(
        Enum(ClaimStatus, name="claim_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    embargoed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
