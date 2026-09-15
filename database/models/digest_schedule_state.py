"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4 (Migration 2): durable wall-clock cadence state for the
NEWS_DIGEST lane. A plain `cycle_count % N`-style in-memory counter (the pattern
`worker/content_main.py` already uses for image retention) is fine when missing a tick is
harmless, but wrong for a 72-hour guarantee - a process restart resetting an in-memory counter
could fire a second digest far too soon. This is the smallest durable fix: one row per named
schedule (`schedule_key` is the primary key, not a fixed single-row assumption, so a future second
named cadence never needs a schema change), storing only `last_run_at`.

Cold-start rule ("Founder Plan Review" constraint #3): on first activation (no row exists yet),
`last_run_at` is initialized to the ACTIVATION timestamp, never backfilled from the preceding 72h
of historical stories - `services/instagram_news_digest.py::get_or_initialize_schedule()` is the
only place this row is ever created."""
from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class DigestScheduleState(Base):
    __tablename__ = "digest_schedule_state"

    schedule_key: Mapped[str] = mapped_column(String(50), primary_key=True)
    last_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
