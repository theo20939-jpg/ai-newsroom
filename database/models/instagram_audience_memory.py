"""INSTAGRAM-GROWTH-3, item 2/3/13: persisted Audience Intelligence - the previous phase's
`services/instagram_audience_intelligence.py::AudienceInsight` was a pure dataclass with no way to
accumulate evidence across separate observations over time. `evidence_stage` is derived from
`observation_count` via `services/instagram_content_brain.py::advance_intelligence_evidence_stage()`
- never hand-set, so a caller cannot silently mark a thin insight as a stable rule.

CRITICAL (item 3): `source` uses the SAME `AudienceEvidenceSource` enum values as the accepted
dataclass (services/instagram_audience_intelligence.py) - a HYPOTHESIS-sourced row always resolves
`evidence_stage=HYPOTHESIS` regardless of how many times it was restated (see the service layer).
No demographic columns exist here either - the accepted "nothing to fabricate into" discipline
carries over unchanged into persistence."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Float, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base
from database.models.instagram_shared import IntelligenceEvidenceStage


class AudienceEvidenceSource(str, enum.Enum):
    """Mirrors services/instagram_audience_intelligence.py::AudienceEvidenceSource verbatim."""

    FIRST_PARTY_PERFORMANCE = "first_party_performance"
    COMMENTS = "comments"
    PRODUCT_DATA = "product_data"
    MANUAL_RESEARCH = "manual_research"
    COMPETITOR_OBSERVATION = "competitor_observation"
    FOUNDER_INPUT = "founder_input"
    HYPOTHESIS = "hypothesis"


class InstagramAudienceInsight(Base):
    __tablename__ = "instagram_audience_insights"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    segment_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    funnel_stage: Mapped[str | None] = mapped_column(String(50), nullable=True)

    need: Mapped[str] = mapped_column(Text, nullable=False)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    interest: Mapped[str | None] = mapped_column(Text, nullable=True)
    objection: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_job: Mapped[str | None] = mapped_column(Text, nullable=True)
    format_preference_hypothesis: Mapped[str | None] = mapped_column(String(200), nullable=True)

    source: Mapped[AudienceEvidenceSource] = mapped_column(
        Enum(AudienceEvidenceSource, name="instagram_audience_evidence_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # Every evidence string ever attached, oldest first - never overwritten, only appended to
    # (item 13's own "allow confidence/evidence to evolve as more observations arrive").
    evidence: Mapped[list | None] = mapped_column(JSON, nullable=True)
    observation_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    evidence_stage: Mapped[IntelligenceEvidenceStage] = mapped_column(
        Enum(IntelligenceEvidenceStage, name="instagram_intelligence_evidence_stage", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=IntelligenceEvidenceStage.OBSERVATION,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.2)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
