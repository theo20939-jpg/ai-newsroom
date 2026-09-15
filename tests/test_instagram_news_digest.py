"""INSTAGRAM-CONTENT-STRATEGY-V2 Phase 4: services/instagram_news_digest.py. Mirrors
tests/test_content_worker_cycle.py's own `_make_event()`/`_make_completed_news_analysis_task()`
technique (direct EditorialTask/NewsEvent construction, not a real WorkflowRunner pass - these are
selection-query-focused tests, not workflow-execution tests)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from database.models.digest_schedule_state import DigestScheduleState
from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventCategory, NewsEvent
from database.models.news_source import NewsSource, SourceType
from database.models.story import Story
from database.models.story_link import NewsEventStoryLink
from schemas.editorial_task import EditorialTaskCreate
from schemas.workflow import WorkflowType
from services import workflow_service
from services.instagram_content_opportunity import OpportunitySourceType
from services.instagram_news_digest import (
    DIGEST_SCHEDULE_KEY,
    build_digest_opportunity,
    get_or_initialize_schedule,
    is_digest_due,
    mark_digest_run,
    select_digest_stories,
)


async def _make_source(session: AsyncSession) -> NewsSource:
    source = NewsSource(name="Digest Test Source", type=SourceType.RSS, url=f"https://example.com/{uuid4()}", active=True)
    session.add(source)
    await session.flush()
    return source


async def _make_event(session: AsyncSession, source: NewsSource, *, title: str) -> NewsEvent:
    event = NewsEvent(
        source_id=source.id, title=title, category=EventCategory.AI, hash=f"digest-test-{uuid4()}",
        published_at=datetime.now(timezone.utc),
    )
    session.add(event)
    await session.flush()
    return event


async def _make_completed_task(
    session: AsyncSession, event: NewsEvent, *, score: int, facts: list[str] | None = None,
    updated_at: datetime | None = None,
) -> EditorialTask:
    command = EditorialTaskCreate(event_id=event.id, workflow_type=WorkflowType.NEWS_ANALYSIS, priority=TaskPriority.B)
    read = await workflow_service.create_task(session, command)
    task = await session.get(EditorialTask, read.id)
    assert task is not None

    step_results = [
        {
            "step_name": "scoring", "status": "SUCCESS", "attempt": 1,
            "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": None, "result": {"score": score, "rationale": "test"},
        },
    ]
    if facts is not None:
        step_results.append({
            "step_name": "research", "status": "SUCCESS", "attempt": 1,
            "started_at": datetime.now(timezone.utc).isoformat(), "finished_at": datetime.now(timezone.utc).isoformat(),
            "error": None, "result": {"facts": facts},
        })
    task.workflow = {**(task.workflow or {}), "step_results": step_results}
    task.status = TaskStatus.COMPLETED
    await session.commit()
    if updated_at is not None:
        await session.execute(update(EditorialTask).where(EditorialTask.id == task.id).values(updated_at=updated_at))
        await session.commit()
        await session.refresh(task)
    return task


# ---------------------------------------------------------------------------
# Cold-start rule: no automatic historical backfill
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_activation_initializes_last_run_at_to_now_never_backfilled(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    schedule = await get_or_initialize_schedule(db_session, now=now)
    assert abs((schedule.last_run_at - now).total_seconds()) < 1

    due = await is_digest_due(db_session, now=now)
    assert due is False  # never immediately due on first activation


@pytest.mark.asyncio
async def test_digest_becomes_due_only_after_a_full_cadence_has_elapsed(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await get_or_initialize_schedule(db_session, now=now)

    almost_due = now + timedelta(hours=71, minutes=59)
    assert await is_digest_due(db_session, now=almost_due) is False

    fully_due = now + timedelta(hours=72, minutes=1)
    assert await is_digest_due(db_session, now=fully_due) is True


@pytest.mark.asyncio
async def test_a_simulated_restart_does_not_reset_the_durable_state(db_session: AsyncSession) -> None:
    """A restart calling get_or_initialize_schedule() again must NOT re-initialize last_run_at to
    "now" a second time - the row already exists, so it is read, never overwritten."""
    now = datetime.now(timezone.utc)
    await get_or_initialize_schedule(db_session, now=now)

    restart_time = now + timedelta(hours=1)
    schedule_after_restart = await get_or_initialize_schedule(db_session, now=restart_time)
    assert abs((schedule_after_restart.last_run_at - now).total_seconds()) < 1  # unchanged


@pytest.mark.asyncio
async def test_mark_digest_run_advances_the_cadence(db_session: AsyncSession) -> None:
    now = datetime.now(timezone.utc)
    await get_or_initialize_schedule(db_session, now=now)
    run_time = now + timedelta(hours=100)
    await mark_digest_run(db_session, now=run_time)

    schedule = await db_session.get(DigestScheduleState, DIGEST_SCHEDULE_KEY)
    assert schedule is not None
    assert abs((schedule.last_run_at - run_time).total_seconds()) < 1
    assert await is_digest_due(db_session, now=run_time + timedelta(hours=1)) is False


# ---------------------------------------------------------------------------
# Story selection: real ranking, no padding, Story-deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_selects_strongest_distinct_stories_within_window(db_session: AsyncSession) -> None:
    # NOTE: this shared Postgres test database carries pre-existing leftover rows from other test
    # modules (confirmed independently - the same pollution tests/test_director_console_service.py
    # already had to disclose), so assertions below filter to THIS test's own event_ids rather
    # than asserting a global count/emptiness - a real, disclosed environmental condition, not
    # something this phase's code caused or can safely "fix" by mutating shared state mid-run.
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    own_ids: set = set()
    for i, score in enumerate([95, 90, 85, 80, 75, 71]):
        event = await _make_event(db_session, source, title=f"OpenAI ships feature number {i}")
        await _make_completed_task(db_session, event, score=score, facts=[f"fact {i}"], updated_at=now)
        own_ids.add(event.id)

    stories = await select_digest_stories(db_session, now=now, window=timedelta(hours=72))
    own_stories = [s for s in stories if s.event_id in own_ids]
    assert len(own_stories) == 6
    assert [s.score for s in own_stories] == sorted([s.score for s in own_stories], reverse=True)


@pytest.mark.asyncio
async def test_below_min_score_threshold_is_excluded(db_session: AsyncSession) -> None:
    from core.config import settings

    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    own_ids: set = set()
    for i in range(6):
        event = await _make_event(db_session, source, title=f"OpenAI ships feature number {i}")
        await _make_completed_task(db_session, event, score=settings.content_generation_min_score - 1, updated_at=now)
        own_ids.add(event.id)

    stories = await select_digest_stories(db_session, now=now)
    assert not any(s.event_id in own_ids for s in stories)  # below-threshold events never included


@pytest.mark.asyncio
async def test_outside_window_is_excluded(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)
    stale = now - timedelta(hours=100)
    own_ids: set = set()
    for i in range(6):
        event = await _make_event(db_session, source, title=f"OpenAI ships feature number {i}")
        await _make_completed_task(db_session, event, score=90, updated_at=stale)
        own_ids.add(event.id)

    stories = await select_digest_stories(db_session, now=now, window=timedelta(hours=72))
    assert not any(s.event_id in own_ids for s in stories)  # stale events never included


# ---------------------------------------------------------------------------
# rank_and_gate_candidates(): the pure decision core - min/max gate + dedup, isolated from any
# database state (deterministic, immune to shared-test-DB pollution).
# ---------------------------------------------------------------------------


def test_pure_gate_never_pads_below_min_stories() -> None:
    from services.instagram_news_digest import DigestStoryCandidate, rank_and_gate_candidates

    candidates = [DigestStoryCandidate(event_id=uuid4(), title=f"s{i}", score=90) for i in range(2)]
    assert rank_and_gate_candidates(candidates, min_stories=5) == []


def test_pure_gate_caps_at_max_stories() -> None:
    from services.instagram_news_digest import DigestStoryCandidate, rank_and_gate_candidates

    candidates = [DigestStoryCandidate(event_id=uuid4(), title=f"s{i}", score=90 - i) for i in range(12)]
    result = rank_and_gate_candidates(candidates, min_stories=5, max_stories=8)
    assert len(result) == 8
    assert [c.score for c in result] == sorted([c.score for c in result], reverse=True)


def test_pure_gate_returns_all_when_between_min_and_max() -> None:
    from services.instagram_news_digest import DigestStoryCandidate, rank_and_gate_candidates

    candidates = [DigestStoryCandidate(event_id=uuid4(), title=f"s{i}", score=90 - i) for i in range(6)]
    result = rank_and_gate_candidates(candidates, min_stories=5, max_stories=8)
    assert len(result) == 6


@pytest.mark.asyncio
async def test_story_deduplication_keeps_only_the_best_scoring_event_per_story(db_session: AsyncSession) -> None:
    source = await _make_source(db_session)
    now = datetime.now(timezone.utc)

    first_event = await _make_event(db_session, source, title="OpenAI update variant 0")
    await _make_completed_task(db_session, first_event, score=70, updated_at=now)
    story = Story(
        title="Real Story", category=EventCategory.AI, entities=[], keywords=[], topic_bucket="ai",
        first_event_id=first_event.id,
    )
    db_session.add(story)
    await db_session.flush()
    db_session.add(NewsEventStoryLink(news_event_id=first_event.id, story_id=story.id, match_score=1.0, match_type="new_story"))

    events = [first_event]
    for i, score in ((1, 95), (2, 80)):  # two more events, same story, middle one strongest
        event = await _make_event(db_session, source, title=f"OpenAI update variant {i}")
        await _make_completed_task(db_session, event, score=score, updated_at=now)
        db_session.add(NewsEventStoryLink(news_event_id=event.id, story_id=story.id, match_score=0.9, match_type="story_update"))
        events.append(event)
    # Pad with enough OTHER standalone strong stories to clear min_stories=5 alongside the 1
    # deduplicated cluster.
    for i in range(4):
        other = await _make_event(db_session, source, title=f"OpenAI other launch {i}")
        await _make_completed_task(db_session, other, score=85, updated_at=now)
    await db_session.commit()

    stories = await select_digest_stories(db_session, now=now)
    matched_from_cluster = [s for s in stories if s.event_id == events[1].id]
    assert len(matched_from_cluster) == 1  # the score=95 one survives
    assert not any(s.event_id in (events[0].id, events[2].id) for s in stories)  # the other two are excluded


# ---------------------------------------------------------------------------
# build_digest_opportunity(): real evidence, deterministic per-window identity
# ---------------------------------------------------------------------------


def test_build_digest_opportunity_carries_real_story_evidence_never_fabricated() -> None:
    from services.instagram_news_digest import DigestStoryCandidate

    now = datetime.now(timezone.utc)
    stories = [
        DigestStoryCandidate(event_id=uuid4(), title="Story A", score=90, facts=["fact A1"]),
        DigestStoryCandidate(event_id=uuid4(), title="Story B", score=85, facts=["fact B1", "fact B2"]),
    ]
    opportunity = build_digest_opportunity(stories, now=now)
    assert opportunity.source_type == OpportunitySourceType.NEWS_DIGEST
    assert "story: Story A" in opportunity.evidence
    assert "fact A1" in opportunity.evidence
    assert "fact B1" in opportunity.evidence and "fact B2" in opportunity.evidence
    assert opportunity.product_mention_allowed is False


def test_build_digest_opportunity_identity_is_deterministic_per_window() -> None:
    from services.instagram_news_digest import DigestStoryCandidate

    now = datetime.now(timezone.utc)
    stories = [DigestStoryCandidate(event_id=uuid4(), title="Story A", score=90)]
    first = build_digest_opportunity(stories, now=now)
    second = build_digest_opportunity(stories, now=now)
    assert first.id == second.id  # a crash-and-retry within the same window computes the SAME id
