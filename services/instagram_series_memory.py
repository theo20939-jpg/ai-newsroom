"""INSTAGRAM-GROWTH-3, item 2/9: Content Series persistence. `promote()` bridges the persisted row
into the ACCEPTED `services/instagram_series.py::evaluate_series_promotion()` gate by building a
throwaway in-memory `ContentSeries` mirror of the row's own current state - the promotion RULE
itself is never reimplemented here, only re-run against whatever the row's current episode_count/
status actually are. A single strong post cannot immediately create an ACTIVE franchise: this is
enforced by `evaluate_series_promotion()` itself (unchanged), not by anything added here."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_series_memory import InstagramSeries
from database.models.instagram_series_memory import SeriesStatus as DBSeriesStatus
from services.instagram_content_brain import EvidenceStage
from services.instagram_series import ContentSeries, SeriesStatus, evaluate_series_promotion


async def create_series(
    session: AsyncSession, *, name: str, description: str, objective: str,
    preferred_formats: list[str] | None = None, topic_scope: str | None = None,
    target_audience: str | None = None, cadence: str | None = None,
) -> InstagramSeries:
    series = InstagramSeries(
        name=name, description=description, objective=objective, preferred_formats=preferred_formats or [],
        topic_scope=topic_scope, target_audience=target_audience, cadence=cadence,
    )
    session.add(series)
    await session.commit()
    await session.refresh(series)
    return series


async def get_series(session: AsyncSession, series_id: UUID) -> InstagramSeries | None:
    return await session.get(InstagramSeries, series_id)


async def list_series(session: AsyncSession) -> list[InstagramSeries]:
    return list((await session.execute(select(InstagramSeries))).scalars().all())


async def record_episode(session: AsyncSession, series_id: UUID) -> InstagramSeries:
    series = await session.get(InstagramSeries, series_id)
    if series is None:
        raise ValueError(f"no InstagramSeries with id={series_id}")
    series.episode_count += 1
    await session.commit()
    await session.refresh(series)
    return series


async def promote_series(
    session: AsyncSession, series_id: UUID, *, evidence_stage: EvidenceStage, is_fatigued: bool = False,
) -> InstagramSeries:
    series = await session.get(InstagramSeries, series_id)
    if series is None:
        raise ValueError(f"no InstagramSeries with id={series_id}")

    in_memory = ContentSeries(
        id=str(series.id), name=series.name, description=series.description or "", objective=series.objective,
        preferred_formats=list(series.preferred_formats or []), status=SeriesStatus(series.status.value),
        episode_count=series.episode_count,
    )
    new_status = evaluate_series_promotion(in_memory, evidence_stage=evidence_stage, is_fatigued=is_fatigued)
    series.status = DBSeriesStatus(new_status.value)
    await session.commit()
    await session.refresh(series)
    return series
