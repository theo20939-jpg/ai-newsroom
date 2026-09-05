"""VISUAL-DESIGN-AUTONOMY-1, spec §40-42/§75: VisualRegressionCase/VisualRegressionRun - a bounded
set of stress conditions a CANDIDATE Designer Brief must be validated against before it may ever be
promoted (services/visual_regression_service.py). Cases are real, hand-authored synthetic stress
descriptions (busy photo, dark photo, screenshot, DATA number-heavy, etc. - spec §40's own list) -
this development branch has no historical incident asset library to draw real past failures from
(forensic finding, see this phase's final report), so cases describe the STRESS CONDITION honestly
rather than fabricating a "real historical example" that does not exist in this repository."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class VisualRegressionOutcome(str, enum.Enum):
    PASS = "pass"
    PASS_WITH_NOTES = "pass_with_notes"
    REWORK = "rework"
    BLOCK = "block"


class VisualRegressionCase(Base):
    __tablename__ = "visual_regression_cases"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    stress_condition: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    fixture_reference: Mapped[str | None] = mapped_column(String(300), nullable=True)
    expected_facts: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class VisualRegressionRun(Base):
    __tablename__ = "visual_regression_runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    candidate_brief_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visual_designer_brief_versions.id"), nullable=False, index=True,
    )
    baseline_brief_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("visual_designer_brief_versions.id"), nullable=True,
    )
    case_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("visual_regression_cases.id"), nullable=False)

    candidate_outcome: Mapped[VisualRegressionOutcome] = mapped_column(
        Enum(VisualRegressionOutcome, name="visual_regression_outcome", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    baseline_outcome: Mapped[VisualRegressionOutcome | None] = mapped_column(
        Enum(VisualRegressionOutcome, name="visual_regression_outcome", values_callable=lambda e: [m.value for m in e]),
        nullable=True,
    )
    issue_codes: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cost: Mapped[float | None] = mapped_column(nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
