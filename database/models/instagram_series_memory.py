"""INSTAGRAM-GROWTH-3, item 2/9: persisted ContentSeries - the accepted
services/instagram_series.py::ContentSeries/SeriesStatus lifecycle was a pure dataclass with no
way to accumulate episode_count/status across separate planning runs. `status` transitions ONLY
via services/instagram_series_memory.py::promote_series() (service layer), which re-runs the
accepted `evaluate_series_promotion()` gate every time - this table never accepts a hand-set
status jump straight to ACTIVE."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Enum, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class SeriesStatus(str, enum.Enum):
    """Mirrors services/instagram_series.py::SeriesStatus values exactly - see
    database/models/instagram_hook_memory.py's own docstring for why this is a deliberate
    persistence-layer copy rather than a services/ import."""

    SERIES_HYPOTHESIS = "series_hypothesis"
    SERIES_TESTING = "series_testing"
    SERIES_ACTIVE = "series_active"
    SERIES_FATIGUED = "series_fatigued"
    SERIES_RETIRED = "series_retired"


class InstagramSeries(Base):
    __tablename__ = "instagram_series"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    objective: Mapped[str] = mapped_column(String(50), nullable=False)
    preferred_formats: Mapped[list | None] = mapped_column(JSON, nullable=True)
    topic_scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    cadence: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[SeriesStatus] = mapped_column(
        Enum(SeriesStatus, name="instagram_series_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=SeriesStatus.SERIES_HYPOTHESIS, index=True,
    )
    episode_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    performance_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    fatigue: Mapped[str] = mapped_column(String(50), nullable=False, default="fresh")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
