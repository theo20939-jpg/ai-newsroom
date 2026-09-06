"""SOCIAL-INTELLIGENCE-PRELAUNCH-1 §12/§13/§14: SocialLaunchProposal - the pending-confirmation
staging area for /launch, structurally mirroring database/models/telegram_surface_proposal.py's
own propose->confirm/cancel shape exactly (never applied to SocialLaunchContext until CONFIRMED -
services/social_launch_proposal_service.py::confirm_proposal() is the ONLY place that ever writes
a SocialLaunchContext row from this flow)."""
from __future__ import annotations

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.social_launch_context import SocialLaunchPlatform


class SocialLaunchProposalStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class SocialLaunchProposal(Base):
    __tablename__ = "social_launch_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[SocialLaunchProposalStatus] = mapped_column(
        Enum(SocialLaunchProposalStatus, name="social_launch_proposal_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=SocialLaunchProposalStatus.PENDING, index=True,
    )
    platform: Mapped[SocialLaunchPlatform] = mapped_column(
        Enum(SocialLaunchPlatform, name="social_launch_platform", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )

    raw_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    # The parser's own structured extraction - the exact same shape confirm_proposal() writes
    # into SocialLaunchContext.confirmed_structure once a human presses Confirm (spec §32/§102
    # precedent from BusinessContextProposal: never let an LLM self-confirm its own proposal).
    parsed_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resulting_context_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
