"""NINJA Social Intelligence Foundation, Telegram Directors Phase 2 §25: persistence for
TelegramExperiment. Plain module-level async functions (no class), mirroring services/
event_recap_review_service.py's own established idempotent-mutation shape - `record_experiment_
result()` is a no-op (returns the row unchanged) once an experiment is already COMPLETED/
ABANDONED, never re-mutated."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.telegram_experiment import ExperimentStatus, TelegramExperiment

_TERMINAL_STATUSES = frozenset({ExperimentStatus.COMPLETED, ExperimentStatus.ABANDONED})


async def create_experiment(
    session: AsyncSession, *, hypothesis: str, dimension: str, variant: str, baseline: str,
    sample_target: int, start_at: datetime | None = None,
) -> TelegramExperiment:
    experiment = TelegramExperiment(
        id=uuid.uuid4(), hypothesis=hypothesis, dimension=dimension, variant=variant,
        baseline=baseline, sample_target=sample_target, start_at=start_at,
        status=ExperimentStatus.PLANNED,
    )
    session.add(experiment)
    return experiment


async def record_experiment_result(
    session: AsyncSession, experiment_id: uuid.UUID, *, result: str, confidence: float,
    status: ExperimentStatus = ExperimentStatus.COMPLETED, end_at: datetime | None = None,
) -> TelegramExperiment | None:
    experiment = (await session.execute(
        select(TelegramExperiment).where(TelegramExperiment.id == experiment_id)
    )).scalar_one_or_none()
    if experiment is None:
        return None
    if experiment.status in _TERMINAL_STATUSES:
        return experiment
    experiment.result = result
    experiment.confidence = confidence
    experiment.status = status
    experiment.end_at = end_at
    return experiment
