"""INSTAGRAM GROWTH ENGINE v2, spec §13/§14: CompetitorAccount + CompetitorContentObservation -
the first REAL persistence for Instagram Competitor Intelligence (the previous foundation had no
competitor model at all). `observable_metrics` on an observation may ONLY ever hold metrics that
are genuinely public/observable (e.g. visible like/comment counts on a public post) - this module
never claims access to a competitor's private Instagram Insights, and `observation_source` records
exactly how a row was obtained so a reader can judge its reliability (spec §54's own "no brittle
unauthorized scraping" instruction - MANUAL and PUBLIC_DATA_IMPORT are the only sources this phase
defines; there is no automated collector anywhere in this codebase)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, Float, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ObservationSource(str, enum.Enum):
    MANUAL = "manual"
    PUBLIC_DATA_IMPORT = "public_data_import"
    UNKNOWN = "unknown"


class CompetitorAccount(Base):
    __tablename__ = "competitor_accounts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, default="instagram", index=True)
    handle: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    display_name: Mapped[str | None] = mapped_column(String(300), nullable=True)
    niche: Mapped[str | None] = mapped_column(String(300), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class CompetitorContentObservation(Base):
    """One row per manually/import-recorded piece of competitor content. `objective_inference`/
    `hook_family`/`creative_family` are this codebase's own INFERENCE about the observation, never
    a fact the competitor confirmed - kept as free-text/nullable rather than FK'd to
    services/instagram_hook_intelligence.py's HookFamily enum so an observation is never blocked
    on that taxonomy already covering every case."""

    __tablename__ = "competitor_content_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("competitor_accounts.id"), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    format: Mapped[str] = mapped_column(String(50), nullable=False)
    topic: Mapped[str] = mapped_column(Text, nullable=False)
    objective_inference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    hook_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    creative_family: Mapped[str | None] = mapped_column(String(100), nullable=True)
    series: Mapped[str | None] = mapped_column(String(200), nullable=True)

    # Public/observable metrics ONLY (e.g. visible like/comment counts) - never a private-insights
    # field. A None/absent key means "not observed", never a fabricated 0 (spec §13's own
    # "do not claim access to private metrics" instruction).
    observable_metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    observation_source: Mapped[ObservationSource] = mapped_column(
        Enum(ObservationSource, name="competitor_observation_source", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=ObservationSource.MANUAL,
    )
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.3)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
