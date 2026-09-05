"""NINJA Social Intelligence Foundation, Part I §6: versioned product context. `Product` (product.py)
holds only the current confirmed snapshot; this table is the append-only provenance trail answering
"why does the system believe this?" and recovering the original human instruction - never
overwritten, never deleted. A confirmed `BusinessContextProposal` (business_context_proposal.py)
creates exactly one new row here per affected Product, chained via `supersedes_id`."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ProductContextVersion(Base):
    """One immutable row per confirmed change to a Product's structured context. `version` is a
    simple per-product monotonic counter (1, 2, 3, ...), not a global sequence. `raw_instruction`
    is the verbatim human Telegram message that produced this version - never derived/reconstructed
    after the fact. `structured_context` is the parsed structured payload actually applied to
    `Product` at confirmation time (a snapshot of what changed, not a diff)."""

    __tablename__ = "product_context_versions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("products.id"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    raw_instruction: Mapped[str] = mapped_column(String, nullable=False)
    structured_context: Mapped[dict] = mapped_column(JSON, nullable=False)
    # "telegram" is the only source this phase implements - kept as a plain string (not an enum)
    # since a future source (e.g. "manual_admin_panel", spec §18's own explicitly out-of-scope-for-
    # v1 alternative) should never require a migration to add.
    source: Mapped[str] = mapped_column(String(50), nullable=False, default="telegram")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    telegram_topic_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # confirmed_at/confirmed_by are set once, at row-creation time, by the SAME confirmation event
    # that creates this row - unlike EventRecapReview's mutable decided_at/decided_by (a row created
    # PENDING then later decided), a ProductContextVersion is only ever created already-confirmed
    # (the proposal itself is the pre-confirmation staging area, never this table).
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    confirmed_by: Mapped[int] = mapped_column(BigInteger, nullable=False)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("product_context_versions.id"), nullable=True
    )

    __table_args__ = (
        UniqueConstraint("product_id", "version", name="uq_product_context_versions_product_version"),
    )
