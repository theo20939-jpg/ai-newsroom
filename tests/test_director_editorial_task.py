"""DIRECTOR-CONTROL-PLANE-1 §50: required Director-generated-task tests."""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.director_editorial_task import DirectorTaskReason, DirectorTaskStatus
from services.director_editorial_task_service import (
    create_task,
    find_open_duplicate,
    list_pending_tasks,
    mark_converted,
    mark_researched,
)


@pytest.mark.asyncio
async def test_feed_gap_creates_a_director_editorial_task(db_session: AsyncSession) -> None:
    task = await create_task(
        db_session, platform="telegram", proposed_topic="Weekly AI model roundup", why_now="No roundup format run in 30 days.",
        reason=DirectorTaskReason.FEED_GAP, director="strategy_director",
    )
    await db_session.flush()
    assert task.reason == DirectorTaskReason.FEED_GAP
    assert task.origin == "director"
    assert task.status == DirectorTaskStatus.RESEARCH_REQUIRED


@pytest.mark.asyncio
async def test_campaign_need_creates_a_director_editorial_task(db_session: AsyncSession) -> None:
    campaign_id = uuid4()
    task = await create_task(
        db_session, platform="telegram", proposed_topic="Product launch teaser", why_now="Campaign enters teasing phase.",
        reason=DirectorTaskReason.CAMPAIGN, director="channel_director", campaign_id=campaign_id,
    )
    await db_session.flush()
    assert task.reason == DirectorTaskReason.CAMPAIGN
    assert task.campaign_id == campaign_id


@pytest.mark.asyncio
async def test_task_includes_provenance(db_session: AsyncSession) -> None:
    task = await create_task(
        db_session, platform="telegram", proposed_topic="X", why_now="Y", reason=DirectorTaskReason.TREND,
        director="growth_director", director_run_context_fingerprint="abc123",
    )
    await db_session.flush()
    assert task.director == "growth_director"
    assert task.origin == "director"
    assert task.director_run_context_fingerprint == "abc123"


@pytest.mark.asyncio
async def test_task_cannot_publish_directly_no_publish_method_exists() -> None:
    """Structural proof (spec §32/§45): DirectorEditorialTask has no publish-capable method at
    all - the only state transitions are mark_researched()/mark_converted(), both purely internal
    bookkeeping."""
    import services.director_editorial_task_service as svc
    public_functions = [name for name in dir(svc) if not name.startswith("_")]
    assert not any("publish" in name.lower() or "send" in name.lower() for name in public_functions)


@pytest.mark.asyncio
async def test_task_must_pass_research_before_conversion(db_session: AsyncSession) -> None:
    task = await create_task(
        db_session, platform="telegram", proposed_topic="Needs facts", why_now="Z", reason=DirectorTaskReason.EXPLAINER,
        director="strategy_director", requires_research=True,
    )
    await db_session.flush()

    with pytest.raises(ValueError, match="research_event_id"):
        await mark_converted(db_session, task.id, content_draft_id=uuid4())

    researched = await mark_researched(db_session, task.id, research_event_id=uuid4())
    assert researched is not None
    assert researched.status == DirectorTaskStatus.RESEARCHED

    converted = await mark_converted(db_session, task.id, content_draft_id=uuid4())
    assert converted is not None
    assert converted.status == DirectorTaskStatus.CONVERTED_TO_DRAFT


@pytest.mark.asyncio
async def test_duplicate_director_idea_does_not_endlessly_recreate_itself(db_session: AsyncSession) -> None:
    first = await create_task(
        db_session, platform="telegram", proposed_topic="Same idea twice", why_now="A", reason=DirectorTaskReason.SERIES,
        director="strategy_director",
    )
    await db_session.flush()
    second = await create_task(
        db_session, platform="telegram", proposed_topic="Same idea twice", why_now="B", reason=DirectorTaskReason.SERIES,
        director="strategy_director",
    )
    await db_session.flush()
    assert first.id == second.id

    duplicate_check = await find_open_duplicate(db_session, platform="telegram", proposed_topic="Same idea twice")
    assert duplicate_check is not None
    assert duplicate_check.id == first.id


@pytest.mark.asyncio
async def test_list_pending_tasks_excludes_converted(db_session: AsyncSession) -> None:
    pending = await create_task(
        db_session, platform="telegram", proposed_topic="Pending topic", why_now="A", reason=DirectorTaskReason.OTHER,
        director="strategy_director",
    )
    done = await create_task(
        db_session, platform="telegram", proposed_topic="Done topic", why_now="A", reason=DirectorTaskReason.OTHER,
        director="strategy_director", requires_research=False,
    )
    await db_session.flush()
    await mark_researched(db_session, done.id, research_event_id=uuid4())
    await mark_converted(db_session, done.id, content_draft_id=uuid4())
    await db_session.flush()

    pending_list = await list_pending_tasks(db_session, platform="telegram")
    ids = {t.id for t in pending_list}
    assert pending.id in ids
    assert done.id not in ids
