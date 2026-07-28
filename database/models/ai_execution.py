"""AIExecution ORM model."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class AICapability(str, enum.Enum):
    """Which AI capability performed the call."""

    RESEARCH = "RESEARCH"
    INTELLIGENCE = "INTELLIGENCE"
    TREND = "TREND"
    SCORING = "SCORING"
    COPYWRITING = "COPYWRITING"
    CREATIVE = "CREATIVE"
    QUALITY = "QUALITY"


class AIExecution(Base):
    """A record of a single AI call, kept for cost and audit tracking."""

    __tablename__ = "ai_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("editorial_tasks.id"), nullable=False
    )
    # API cost optimization: nullable (a call may occur before/without a resolvable event_id in
    # some future caller), no FK constraint (mirrors this column's own observability-only
    # purpose - never joined for referential integrity, only for cost-per-event reporting).
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    workflow_name: Mapped[str] = mapped_column(String, nullable=False, default="UNKNOWN")
    capability: Mapped[AICapability] = mapped_column(Enum(AICapability, name="ai_capability"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    retry_number: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cached_input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    reasoning_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=6),
        nullable=False,
    )
    # Where the usage numbers above came from - "provider_response" (the real, verified case)
    # vs any future estimate-only fallback - never fabricated, always labeled (API cost
    # optimization's own "no invented token usage" requirement).
    usage_source: Mapped[str] = mapped_column(String, nullable=False, default="provider_response")
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
