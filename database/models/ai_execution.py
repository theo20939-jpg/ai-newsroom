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
    capability: Mapped[AICapability] = mapped_column(Enum(AICapability, name="ai_capability"), nullable=False)
    model: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version: Mapped[str | None] = mapped_column(String, nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost: Mapped[Decimal] = mapped_column(
        Numeric(precision=12, scale=6),
        nullable=False,
    )
    response: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
