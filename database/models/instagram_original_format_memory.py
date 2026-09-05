"""INSTAGRAM-GROWTH-3, item 2/11: persisted Original Format Lab - moves
services/instagram_original_format_lab.py::OriginalFormatExperiment beyond contract-only. No
automatic adoption anywhere in the service layer (item 11's own explicit instruction) - `status`
only ever changes via an explicit service call naming the new status, never a background job."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class OriginalFormatStatus(str, enum.Enum):
    """Mirrors services/instagram_original_format_lab.py::OriginalFormatStatus values exactly."""

    DRAFT = "draft"
    READY_TO_TEST = "ready_to_test"
    TESTING = "testing"
    PROMISING = "promising"
    FAILED = "failed"
    RETEST = "retest"
    ADOPTED = "adopted"


class InstagramOriginalFormatExperiment(Base):
    __tablename__ = "instagram_original_format_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idea: Mapped[str] = mapped_column(Text, nullable=False)
    novelty_hypothesis: Mapped[str] = mapped_column(Text, nullable=False)
    intentional_difference: Mapped[str] = mapped_column(Text, nullable=False)
    target_objective: Mapped[str] = mapped_column(String(50), nullable=False)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    format: Mapped[str] = mapped_column(String(50), nullable=False)
    test_conditions: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_window: Mapped[str | None] = mapped_column(String(100), nullable=True)
    references: Mapped[list | None] = mapped_column(JSON, nullable=True)

    status: Mapped[OriginalFormatStatus] = mapped_column(
        Enum(OriginalFormatStatus, name="instagram_original_format_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=OriginalFormatStatus.DRAFT, index=True,
    )
    result: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
