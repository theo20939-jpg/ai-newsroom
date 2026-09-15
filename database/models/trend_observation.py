"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5 (Migration 3): TrendObservation - append-only, one row
per `(source, source_item_id, observed_at)`, mirroring `ProductContextVersion`'s own append-only
precedent exactly. Engagement velocity requires >= 2 timestamped observations of the same
`(source, source_item_id)` - never a single mutable "current snapshot" row, and never a fabricated
velocity from one observation (see services/trend_normalization.py)."""
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TrendObservation(Base):
    __tablename__ = "trend_observations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_item_id: Mapped[str] = mapped_column(String(300), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    raw_topic_text: Mapped[str] = mapped_column(Text, nullable=False)
    # {topic, entities, format, hook_pattern, mechanic, visual_pattern} - the bounded LLM-produced
    # structured fingerprint (services/trend_fingerprint.py) - nullable because the fingerprint
    # call is fail-soft (a Gateway failure records the raw observation anyway, never blocks
    # ingestion; services/trend_signal_matching.py degrades to raw-text comparison when absent).
    trend_fingerprint: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # Whatever REAL metrics that source's own official API provides (services/instagram_content_
    # strategy_v2 plan §4's own Data Source Capability Matrix) - never a fabricated/estimated
    # metric for a source that doesn't provide it.
    engagement_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("trend_clusters.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("source", "source_item_id", "observed_at", name="uq_trend_observations_source_item_observed"),
    )
