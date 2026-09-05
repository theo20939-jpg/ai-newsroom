"""INSTAGRAM-GROWTH-3, item 2/15: minimal, honest Creator Radar persistence - manual observations
only, mirrors services/instagram_competitor_intelligence.py's own create/query shape. No creator
discovery, no invented follower/engagement numbers (services/instagram_platform_capabilities.py's
own "creator_discovery" capability is UNKNOWN)."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_creator_memory import CreatorObservationSource, InstagramCreatorObservation


async def record_creator_observation(
    session: AsyncSession, *, handle: str, note: str, observed_at: datetime, platform: str = "instagram",
    observation_source: CreatorObservationSource = CreatorObservationSource.MANUAL, confidence: float = 0.2,
) -> InstagramCreatorObservation:
    observation = InstagramCreatorObservation(
        handle=handle, platform=platform, observed_at=observed_at, note=note,
        observation_source=observation_source, confidence=confidence,
    )
    session.add(observation)
    await session.commit()
    await session.refresh(observation)
    return observation


async def list_creator_observations(
    session: AsyncSession, *, handle: str | None = None,
) -> list[InstagramCreatorObservation]:
    stmt = select(InstagramCreatorObservation)
    if handle is not None:
        stmt = stmt.where(InstagramCreatorObservation.handle == handle)
    return list((await session.execute(stmt)).scalars().all())
