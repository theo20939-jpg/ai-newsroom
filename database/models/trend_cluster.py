"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 5 (Migration 3): TrendCluster - the persisted identity a
group of `TrendObservation` rows converges on (services/trend_signal_matching.py). Deliberately
NOT built on `Story`/`NewsEventStoryLink` (both hard-FK'd to `news_events` - a trend item is not a
NewsEvent, and forcing it through that schema would corrupt Story's own real semantics)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class TrendClusterType(str, enum.Enum):
    """Founder-specified taxonomy (three types, no more): TOPIC (same real-world subject - a new
    AI model, a new device, a new game/event), FORMAT (same spreading mechanic/editing pattern -
    POV, starter pack, action figure, a ranking format - across DIFFERENT topics), HYBRID (both a
    topic AND a format/mechanic are spreading together)."""

    TOPIC = "topic"
    FORMAT = "format"
    HYBRID = "hybrid"


class TrendClusterStatus(str, enum.Enum):
    ACTIVE = "active"
    STALE = "stale"


class TrendCluster(Base):
    __tablename__ = "trend_clusters"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    representative_text: Mapped[str] = mapped_column(Text, nullable=False)
    cluster_type: Mapped[TrendClusterType] = mapped_column(
        Enum(TrendClusterType, name="trend_cluster_type", values_callable=lambda e: [m.value for m in e]),
        nullable=False,
    )
    # The cluster's own representative fingerprint (same {topic, entities, format, hook_pattern,
    # mechanic, visual_pattern} shape as a single observation's) - the first observation's
    # fingerprint that founded this cluster, kept for downstream matching against new
    # observations without re-fetching every member row.
    trend_fingerprint: Mapped[dict] = mapped_column(JSON, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[TrendClusterStatus] = mapped_column(
        Enum(TrendClusterStatus, name="trend_cluster_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=TrendClusterStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
