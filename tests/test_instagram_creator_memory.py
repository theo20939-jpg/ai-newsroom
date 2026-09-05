"""INSTAGRAM-GROWTH-3, item 19: minimal Creator Radar persistence test."""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.instagram_creator_memory import list_creator_observations, record_creator_observation


@pytest.mark.asyncio
async def test_creator_observation_persists_manually(db_session: AsyncSession) -> None:
    observation = await record_creator_observation(
        db_session, handle="@creator1", note="posts consistent split-screen comparison reels",
        observed_at=datetime.now(timezone.utc),
    )
    assert observation.observation_source.value == "manual"

    fetched = await list_creator_observations(db_session, handle="@creator1")
    assert len(fetched) == 1
