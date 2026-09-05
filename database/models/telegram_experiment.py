"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §25: formalizes
services/telegram_performance_memory.py::ExperimentRecord (contract-only) into a real persisted
`TelegramExperiment` row. No automatic assignment of production posts to an experiment exists
anywhere in this phase (spec §25's own "no automatic experiment assignment... unless purely
passive metadata already supports it") - this table exists so a hypothesis/variant/result CAN be
recorded, not so one is automatically created."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, Integer, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from database.base import Base


class ExperimentStatus(str, enum.Enum):
    PLANNED = "planned"
    RUNNING = "running"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class TelegramExperiment(Base):
    __tablename__ = "telegram_experiments"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    hypothesis: Mapped[str] = mapped_column(String(500), nullable=False)
    dimension: Mapped[str] = mapped_column(String(100), nullable=False)
    variant: Mapped[str] = mapped_column(String(200), nullable=False)
    baseline: Mapped[str] = mapped_column(String(200), nullable=False)

    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sample_target: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    status: Mapped[ExperimentStatus] = mapped_column(
        Enum(ExperimentStatus, name="telegram_experiment_status", values_callable=lambda e: [m.value for m in e]),
        nullable=False, default=ExperimentStatus.PLANNED,
    )
    result: Mapped[str | None] = mapped_column(String(500), nullable=True)
    confidence: Mapped[float] = mapped_column(nullable=False, default=0.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
