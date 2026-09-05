"""INSTAGRAM-GROWTH-3, item 2/10: Hook Intelligence evidence + Creative Fatigue history
persistence. `record_hook_evidence()` upserts by (dimension, value) and re-runs the ACCEPTED
`services/instagram_content_brain.py::advance_evidence_stage()` gate against the ACCUMULATED
sample - a dimension/value pair that was ANOMALY last week can become POSSIBLE_SIGNAL this week as
more samples arrive, but never jumps straight to STABLE_WORKING_RULE off one update.

`record_fatigue_observation()` is APPEND-ONLY (a real history, per item 2's own naming) -
`get_latest_fatigue_state()` reads back only the most recent row per (dimension, value).

Enum values are identical between services/instagram_content_brain.py and
database/models/instagram_hook_memory.py's own copies (see that model's docstring) - conversion at
this boundary is always a plain `.value` round-trip, never a semantic remapping."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_hook_memory import (
    EvidenceStage as DBEvidenceStage,
)
from database.models.instagram_hook_memory import (
    FatigueState as DBFatigueState,
)
from database.models.instagram_hook_memory import (
    InstagramFatigueObservation,
    InstagramHookEvidenceRecord,
)
from services.instagram_content_brain import PerformancePattern, advance_evidence_stage, evaluate_fatigue_state


async def record_hook_evidence(
    session: AsyncSession, *, dimension: str, value: str, pattern: PerformancePattern,
) -> InstagramHookEvidenceRecord:
    stmt = select(InstagramHookEvidenceRecord).where(
        InstagramHookEvidenceRecord.dimension == dimension, InstagramHookEvidenceRecord.value == value,
    )
    existing = (await session.execute(stmt)).scalar_one_or_none()
    stage = DBEvidenceStage(advance_evidence_stage(pattern).value)

    if existing is None:
        record = InstagramHookEvidenceRecord(
            dimension=dimension, value=value, sample_size=pattern.sample_size, effect_size=pattern.effect_size,
            repeatability=pattern.repeatability, baseline=pattern.baseline, recency_days=pattern.recency_days,
            evidence_stage=stage,
        )
        session.add(record)
    else:
        existing.sample_size = pattern.sample_size
        existing.effect_size = pattern.effect_size
        existing.repeatability = pattern.repeatability
        existing.baseline = pattern.baseline
        existing.recency_days = pattern.recency_days
        existing.evidence_stage = stage
        record = existing

    await session.commit()
    await session.refresh(record)
    return record


async def get_hook_evidence(session: AsyncSession, *, dimension: str, value: str) -> InstagramHookEvidenceRecord | None:
    stmt = select(InstagramHookEvidenceRecord).where(
        InstagramHookEvidenceRecord.dimension == dimension, InstagramHookEvidenceRecord.value == value,
    )
    return (await session.execute(stmt)).scalar_one_or_none()


async def record_fatigue_observation(
    session: AsyncSession, *, dimension: str, value: str, repetition_count: int, window_days: int,
) -> InstagramFatigueObservation:
    state = evaluate_fatigue_state(dimension=dimension, repetition_count=repetition_count, window_days=window_days)
    observation = InstagramFatigueObservation(
        dimension=dimension, value=value, repetition_count=repetition_count, window_days=window_days,
        fatigue_state=DBFatigueState(state.value),
    )
    session.add(observation)
    await session.commit()
    await session.refresh(observation)
    return observation


async def list_fatigue_history(
    session: AsyncSession, *, dimension: str, value: str,
) -> list[InstagramFatigueObservation]:
    stmt = (
        select(InstagramFatigueObservation)
        .where(InstagramFatigueObservation.dimension == dimension, InstagramFatigueObservation.value == value)
        .order_by(InstagramFatigueObservation.observed_at)
    )
    return list((await session.execute(stmt)).scalars().all())


async def get_latest_fatigue(
    session: AsyncSession, *, dimension: str, value: str,
) -> InstagramFatigueObservation | None:
    history = await list_fatigue_history(session, dimension=dimension, value=value)
    return history[-1] if history else None
