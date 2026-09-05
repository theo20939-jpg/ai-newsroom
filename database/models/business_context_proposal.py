"""NINJA Social Intelligence Foundation, Part II: BusinessContextProposal - the pending-
confirmation staging area every mutation command (/product, /campaign, /milestone, /directive,
/claim, /context) writes to first. Structural sibling of `EventRecapReview`/`FinalPostReview`
(propose -> human confirm/cancel -> exactly one resulting durable write), generalized to carry a
MULTI-entity change set (spec §25: /context may span Product/Campaign/Milestone/Directive in one
proposal) rather than one fixed target row.

`proposed_change_set` is never applied to canonical tables until `status` transitions to
CONFIRMED (services/business_context_proposal_service.py::confirm_proposal()) - the parser
(services/business_context_command_parser.py) NEVER writes canonical state directly (spec §32/§102:
"Never let an LLM self-confirm its own proposed mutation")."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class BusinessContextCommandType(str, enum.Enum):
    PRODUCT = "product"
    CAMPAIGN = "campaign"
    MILESTONE = "milestone"
    DIRECTIVE = "directive"
    CLAIM = "claim"
    CONTEXT = "context"


class BusinessContextProposalStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class BusinessContextProposal(Base):
    """One row per parsed-but-not-yet-confirmed command. `proposed_change_set` is a JSON list of
    typed operations (see services/business_context_proposal_service.py::ChangeOperation for the
    exact shape each dict must satisfy) - e.g.
    `[{"entity_type": "product_context_version", "product_slug": "ai", "payload": {...}}, ...]`.
    `resulting_version_ids` is populated only on confirmation, recording exactly which new
    ProductContextVersion/CampaignMilestone/etc. rows this proposal produced - the audit trail's
    own forward link (spec §35), complementing ProductContextVersion's own backward
    `supersedes_id`."""

    __tablename__ = "business_context_proposals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    command_type: Mapped[BusinessContextCommandType] = mapped_column(
        Enum(
            BusinessContextCommandType, name="business_context_command_type",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, index=True,
    )
    status: Mapped[BusinessContextProposalStatus] = mapped_column(
        Enum(
            BusinessContextProposalStatus, name="business_context_proposal_status",
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False, default=BusinessContextProposalStatus.PENDING, index=True,
    )
    raw_instruction: Mapped[str] = mapped_column(String, nullable=False)
    proposed_change_set: Mapped[list] = mapped_column(JSON, nullable=False)
    parsed_structure: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    resulting_version_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
