"""SOCIAL-INTELLIGENCE-OPS-1, spec §3/§4: TelegramSurfaceProposal - the pending-confirmation
staging area for /surface, structurally mirroring
database/models/business_context_proposal.py::BusinessContextProposal's own propose->confirm/
cancel shape (never applied to TelegramSurface until CONFIRMED - services/
telegram_surface_proposal_service.py::confirm_proposal() is the ONLY place that ever writes a
TelegramSurface row from this flow).

Kept as its OWN model rather than reusing BusinessContextProposal (spec's own "platform-specific
models remain platform-specific" principle, already established for TelegramSurface itself in the
prior phase) - a status enum this small is duplicated here rather than cross-imported, matching
database/models/instagram_hook_memory.py's own established "small duplication over cross-platform
coupling" convention."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, Boolean, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.telegram_surface import TelegramSurfaceRole


class TelegramSurfaceProposalStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class TelegramSurfaceProposal(Base):
    __tablename__ = "telegram_surface_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    status: Mapped[TelegramSurfaceProposalStatus] = mapped_column(
        Enum(TelegramSurfaceProposalStatus, name="telegram_surface_proposal_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=TelegramSurfaceProposalStatus.PENDING, index=True,
    )

    # The resolved target surface - `chat_id` is NEVER null on a proposal that actually reaches
    # PENDING (services/telegram_surface_proposal_service.py refuses to create one otherwise,
    # spec §7's own "do not invent unresolved channel IDs" instruction applied at write time).
    chat_id: Mapped[int] = mapped_column(BigInteger, nullable=False, index=True)
    username: Mapped[str | None] = mapped_column(String(200), nullable=True)
    role: Mapped[TelegramSurfaceRole] = mapped_column(
        Enum(TelegramSurfaceRole, name="telegram_surface_role", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    analytics_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    raw_instruction: Mapped[str] = mapped_column(Text, nullable=False)
    parsed_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resulting_surface_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
