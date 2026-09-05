"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §5: TelegramPostPerformanceSnapshot.
One row per (channel post, capture window) - "unavailable != zero" is a hard contract enforced at
the column level: every metric is nullable, and services/telegram_performance_collection.py's own
collector NEVER writes 0 for a metric it could not actually read (it writes NULL, or skips the
column entirely via a per-metric capability check)."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class SnapshotWindow(str, enum.Enum):
    """Spec §5's own desired windows - kept as an explicit enum (not a bare int) so a snapshot's
    intended window is always self-describing even if `age_seconds` drifts slightly from the
    nominal value (a collector cycle is never perfectly on-time)."""

    M5 = "5m"
    M30 = "30m"
    H1 = "1h"
    H3 = "3h"
    H6 = "6h"
    H24 = "24h"
    H72 = "72h"


class TelegramPostPerformanceSnapshot(Base):
    __tablename__ = "telegram_post_performance_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    channel_memory_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True, index=True)
    telegram_message_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    window: Mapped[SnapshotWindow] = mapped_column(
        Enum(SnapshotWindow, name="telegram_snapshot_window", values_callable=lambda e: [m.value for m in e]),
        nullable=False, index=True,
    )
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    age_seconds: Mapped[int] = mapped_column(Integer, nullable=False)

    # Every metric nullable - NULL means "not collected/not available", never a guessed 0 (spec
    # §5's own explicit "No guessed zeros. Unavailable != zero." requirement).
    views: Mapped[int | None] = mapped_column(Integer, nullable=True)
    forwards: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reactions_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    comments_total: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscriber_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    subscriber_delta: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Records exactly which capability classification (services/telegram_platform_capabilities.py)
    # was in effect when this row was written - so a future analysis can tell "metric X is NULL
    # because it was UNAVAILABLE at the time" apart from "collection simply hadn't run yet".
    capability_version: Mapped[str] = mapped_column(String(50), nullable=False)
    collector: Mapped[str] = mapped_column(String(100), nullable=False)
    raw_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
