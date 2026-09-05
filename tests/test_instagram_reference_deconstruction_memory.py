"""INSTAGRAM-GROWTH-3, item 19: Reference Deconstruction persistence + originality constraint test."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from services.instagram_reference_deconstruction_memory import (
    create_reference_deconstruction,
    list_reference_deconstructions,
)


@pytest.mark.asyncio
async def test_must_not_copy_required_non_empty(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError):
        await create_reference_deconstruction(
            db_session, reference_description="a viral split-screen reel", must_not_copy=[],
        )


@pytest.mark.asyncio
async def test_reference_deconstruction_persists_with_originality_constraints(db_session: AsyncSession) -> None:
    record = await create_reference_deconstruction(
        db_session, reference_description="a viral split-screen reel", must_not_copy=["exact audio track", "verbatim on-screen text"],
        hook_mechanics="before/after split reveal", originality_constraints=["use a different product angle"],
    )
    assert record.must_not_copy == ["exact audio track", "verbatim on-screen text"]
    assert record.ai_assisted is False

    fetched = await list_reference_deconstructions(db_session)
    assert any(r.id == record.id for r in fetched)
