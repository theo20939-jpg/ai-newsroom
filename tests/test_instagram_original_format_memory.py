"""INSTAGRAM-GROWTH-3, item 19: Original Format experiment persistence tests."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.instagram_original_format_memory import OriginalFormatStatus as DBOriginalFormatStatus
from services.instagram_original_format_lab import OriginalFormatStatus
from services.instagram_original_format_memory import create_experiment, update_experiment_status


async def _create(db_session: AsyncSession):
    return await create_experiment(
        db_session, idea="split-screen comparison reel", novelty_hypothesis="h", intentional_difference="d",
        target_objective="reach", target_audience="a", format="reel", test_conditions="t",
        success_criteria="s", evaluation_window="7d",
    )


@pytest.mark.asyncio
async def test_experiment_persists_as_draft(db_session: AsyncSession) -> None:
    experiment = await _create(db_session)
    assert experiment.status == DBOriginalFormatStatus.DRAFT


@pytest.mark.asyncio
async def test_terminal_status_without_result_is_rejected(db_session: AsyncSession) -> None:
    experiment = await _create(db_session)
    with pytest.raises(ValueError):
        await update_experiment_status(db_session, experiment.id, status=OriginalFormatStatus.ADOPTED)


@pytest.mark.asyncio
async def test_terminal_status_with_result_persists(db_session: AsyncSession) -> None:
    experiment = await _create(db_session)
    updated = await update_experiment_status(
        db_session, experiment.id, status=OriginalFormatStatus.ADOPTED, result="variant clearly outperformed control",
    )
    assert updated.status == DBOriginalFormatStatus.ADOPTED
    assert updated.result == "variant clearly outperformed control"


@pytest.mark.asyncio
async def test_no_automatic_adoption_status_stays_until_explicit_call(db_session: AsyncSession) -> None:
    experiment = await _create(db_session)
    updated = await update_experiment_status(db_session, experiment.id, status=OriginalFormatStatus.TESTING)
    assert updated.status == DBOriginalFormatStatus.TESTING
