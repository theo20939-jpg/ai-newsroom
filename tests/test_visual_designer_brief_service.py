"""VISUAL-DESIGN-AUTONOMY-1, spec §71/§56: VisualDesignerBriefService tests - single-ACTIVE
invariant, freeze/unfreeze, rollback to a prior validated version, history never deleted."""
from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.visual_designer_brief import VisualDesignerBriefStatus
from services.visual_designer_brief_service import (
    create_candidate_brief,
    create_initial_brief,
    freeze_brief,
    get_active_brief,
    get_active_or_frozen_brief,
    get_frozen_brief,
    list_history,
    promote_candidate,
    reject_candidate,
    rollback_to,
    unfreeze_brief,
)


@pytest.mark.asyncio
async def test_create_initial_brief_is_active_v1(db_session: AsyncSession) -> None:
    brief = await create_initial_brief(db_session, scope="global", brief_text="v1 text")
    assert brief.version == 1
    assert brief.status == VisualDesignerBriefStatus.ACTIVE
    assert brief.activated_at is not None
    assert await get_active_brief(db_session, "global") is not None


@pytest.mark.asyncio
async def test_create_initial_brief_rejects_when_history_exists(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="news", brief_text="v1")
    with pytest.raises(ValueError):
        await create_initial_brief(db_session, scope="news", brief_text="v1 again")


@pytest.mark.asyncio
async def test_promote_candidate_supersedes_previous_active(db_session: AsyncSession) -> None:
    v1 = await create_initial_brief(db_session, scope="data", brief_text="v1")
    candidate = await create_candidate_brief(
        db_session, scope="data", brief_text="v2", reason="repeated VISUAL_TOO_BUSY", evidence={"pattern": "busy"},
    )
    assert candidate.version == 2
    assert candidate.parent_version_id == v1.id

    promoted = await promote_candidate(db_session, candidate.id)
    assert promoted.status == VisualDesignerBriefStatus.ACTIVE
    assert promoted.activated_at is not None

    history = await list_history(db_session, "data")
    assert len(history) == 2  # nothing deleted
    old = next(v for v in history if v.id == v1.id)
    assert old.status == VisualDesignerBriefStatus.SUPERSEDED

    only_active = [v for v in history if v.status == VisualDesignerBriefStatus.ACTIVE]
    assert len(only_active) == 1  # single-ACTIVE invariant


@pytest.mark.asyncio
async def test_reject_candidate_never_touches_active(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="quote", brief_text="v1")
    candidate = await create_candidate_brief(db_session, scope="quote", brief_text="v2", reason="one bad render")
    rejected = await reject_candidate(db_session, candidate.id, reason="insufficient evidence")
    assert rejected.status == VisualDesignerBriefStatus.REJECTED
    active = await get_active_brief(db_session, "quote")
    assert active is not None
    assert active.version == 1


@pytest.mark.asyncio
async def test_freeze_and_unfreeze_round_trip(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="recap", brief_text="v1")
    frozen = await freeze_brief(db_session, "recap", reason="founder request")
    assert frozen.status == VisualDesignerBriefStatus.FROZEN
    assert await get_active_brief(db_session, "recap") is None
    assert await get_frozen_brief(db_session, "recap") is not None
    # A frozen brief still governs per-post creative direction (spec §20).
    assert (await get_active_or_frozen_brief(db_session, "recap")) is not None

    unfrozen = await unfreeze_brief(db_session, "recap", reason="issue resolved")
    assert unfrozen.status == VisualDesignerBriefStatus.ACTIVE


@pytest.mark.asyncio
async def test_rollback_restores_prior_validated_version_without_deleting_history(db_session: AsyncSession) -> None:
    v1 = await create_initial_brief(db_session, scope="breaking", brief_text="v1 stable")
    candidate = await create_candidate_brief(db_session, scope="breaking", brief_text="v2 broken", reason="test")
    await promote_candidate(db_session, candidate.id)

    restored = await rollback_to(db_session, "breaking", target_version_id=v1.id, reason="v2 caused regressions")
    assert restored.id == v1.id
    assert restored.status == VisualDesignerBriefStatus.ACTIVE
    assert restored.brief_text == "v1 stable"

    history = await list_history(db_session, "breaking")
    assert len(history) == 2  # both versions still present
    rolled = next(v for v in history if v.id == candidate.id)
    assert rolled.status == VisualDesignerBriefStatus.ROLLED_BACK


@pytest.mark.asyncio
async def test_rollback_rejects_a_never_validated_candidate(db_session: AsyncSession) -> None:
    await create_initial_brief(db_session, scope="carousel", brief_text="v1")
    candidate = await create_candidate_brief(db_session, scope="carousel", brief_text="v2", reason="test")
    with pytest.raises(ValueError):
        await rollback_to(db_session, "carousel", target_version_id=candidate.id, reason="should fail - still CANDIDATE")
