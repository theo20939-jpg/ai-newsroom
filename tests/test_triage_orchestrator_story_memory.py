"""Phase 18.10 M1/M2: story_memory_mode wiring in services.triage_orchestrator.run_triage_cycle().

Kept as a separate file from tests/test_triage_orchestrator_cycle.py (rather than extending it)
to avoid touching that file's own documented pre-existing cross-test-isolation sensitivity
(real_committed_event()-based, genuinely committed, not SAVEPOINT-rolled-back) - same fixture
reuse convention, isolated blast radius for this phase's own new tests.
"""
import pytest

from core.config import settings
from services.triage_orchestrator import TriageCycleReport, run_triage_cycle
from tests.test_triage_orchestrator_claims import independent_session_factory, real_committed_event


@pytest.mark.asyncio
async def test_default_off_mode_never_touches_story_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    """The default, byte-identical-to-pre-18.10 path - story_memory_mode == "off" must produce
    zero story-related counters and never query/mutate anything story-related. Does not need the
    (unapplied) story-memory migration at all, since _apply_story_memory() is never even called
    in this mode - confirms the off-path has zero footprint, not just zero behavior change."""
    monkeypatch.setattr(settings, "story_memory_mode", "off")

    engine, session_factory = independent_session_factory()
    try:
        async with real_committed_event(session_factory):
            report = await run_triage_cycle(session_factory=session_factory)

        assert report.story_new == 0
        assert report.story_updates == 0
        assert report.story_supporting_sources == 0
        assert report.story_semantic_duplicates == 0
        assert report.story_uncertain_matches == 0
    finally:
        await engine.dispose()


def test_received_events_property_sums_claimed_and_recovered() -> None:
    report = TriageCycleReport(events_claimed=3, events_recovered=2)
    assert report.received_events == 5


@pytest.mark.asyncio
async def test_shadow_mode_without_migration_degrades_gracefully_not_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The exact safety property this compatibility fix relies on: if story_memory_mode is
    enabled before the Phase 18.10 migration has been applied (the "stories"/
    "news_event_story_links" tables don't exist yet), run_triage_cycle() must NOT crash or
    corrupt other events - _run_phase_b()'s own pre-existing `except Exception` handler catches
    the "relation does not exist" error exactly like any other Phase B failure, leaves the event
    PROCESSING with no task (automatically recoverable once the migration lands), and the cycle
    itself completes normally."""
    monkeypatch.setattr(settings, "story_memory_mode", "shadow")

    engine, session_factory = independent_session_factory()
    try:
        async with real_committed_event(session_factory) as event_id:
            report = await run_triage_cycle(session_factory=session_factory)  # must not raise

            assert report.other_failures >= 1
            assert report.tasks_created == 0

            from sqlalchemy import select

            from database.models.editorial_task import EditorialTask
            from database.models.news_event import EventStatus, NewsEvent

            async with session_factory() as session:
                event = await session.get(NewsEvent, event_id)
                assert event is not None
                assert event.status == EventStatus.PROCESSING  # recoverable, not lost

                tasks = (
                    await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
                ).scalars().all()
                assert tasks == []
    finally:
        await engine.dispose()
