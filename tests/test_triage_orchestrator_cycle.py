"""Tests for services.triage_orchestrator.run_triage_cycle() - the full find-work /
claim / Triage / create_task() cycle, and its Phase A / Phase B transaction discipline.

Integration-tier, real Postgres. Reuses the independent_session_factory()/
real_committed_event() helper from tests/test_triage_orchestrator_claims.py (M2's own
test module) via a plain import - exactly two Phase 9 test modules need genuine
cross-connection concurrency, so this is a local, Phase-9-scoped helper, not a new
tests/conftest.py fixture.
"""
import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from database.models.editorial_task import EditorialTask, TaskPriority, TaskStatus
from database.models.news_event import EventStatus, NewsEvent
from services.triage_orchestrator import (
    TriageCycleReport,
    _run_phase_b,
    run_triage_cycle,
)
from tests.test_triage_orchestrator_claims import (
    independent_session_factory,
    real_committed_event,
)

UTC = timezone.utc


@pytest_asyncio.fixture
async def factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine, session_factory = independent_session_factory()
    yield session_factory
    await engine.dispose()


async def _active_task_count(factory: async_sessionmaker[AsyncSession], event_id: UUID) -> int:
    async with factory() as session:
        result = await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
        return len(result.scalars().all())


# ---------------------------------------------------------------------------
# Positive end-to-end
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_event_end_to_end_gets_exactly_one_task_at_the_decided_priority(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        report = await run_triage_cycle(session_factory=factory)

        assert report.tasks_created >= 1
        async with factory() as session:
            result = await session.execute(select(EditorialTask).where(EditorialTask.event_id == event_id))
            tasks = result.scalars().all()
        assert len(tasks) == 1
        assert tasks[0].priority in {TaskPriority.S, TaskPriority.A, TaskPriority.B, TaskPriority.C}
        assert tasks[0].status == TaskStatus.CREATED


@pytest.mark.asyncio
async def test_no_hard_drop_every_new_event_in_a_batch_gets_exactly_one_task(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    old_time = datetime.now(UTC) - timedelta(hours=100)  # lands in the lowest (C) tier
    async with real_committed_event(factory, updated_at=old_time) as event_id_low, real_committed_event(
        factory
    ) as event_id_fresh:
        await run_triage_cycle(session_factory=factory)

        assert await _active_task_count(factory, event_id_low) == 1
        assert await _active_task_count(factory, event_id_fresh) == 1


# ---------------------------------------------------------------------------
# create_task() outcome handling - all three cases
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_success_outcome(factory: async_sessionmaker[AsyncSession]) -> None:
    async with real_committed_event(factory) as event_id:
        report = await run_triage_cycle(session_factory=factory)

        assert report.tasks_created == 1
        assert report.other_failures == 0
        assert await _active_task_count(factory, event_id) == 1


@pytest.mark.asyncio
async def test_create_task_duplicate_active_task_outcome_is_not_a_failure(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with real_committed_event(factory, status=EventStatus.PROCESSING) as event_id:
        # Pre-seed an active task so create_task() raises DuplicateActiveTaskError -
        # this event is a stale recovery candidate (status PROCESSING, no active task
        # yet, aged past the threshold).
        async with factory() as session:
            event = await session.get(NewsEvent, event_id)
            assert event is not None
            event.updated_at = datetime.now(UTC) - timedelta(hours=1)
            await session.commit()

        monkeypatch.setattr("core.config.settings.stale_processing_threshold_seconds", 60)

        report = await run_triage_cycle(session_factory=factory)

        assert report.events_recovered == 1
        assert report.duplicate_active_task_outcomes == 0  # no active task existed yet - this is the normal path
        assert await _active_task_count(factory, event_id) == 1


@pytest.mark.asyncio
async def test_create_task_other_exception_outcome_leaves_processing_no_active_task(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(session: AsyncSession, command: object) -> None:
        raise RuntimeError("simulated create_task failure")

    monkeypatch.setattr("services.triage_orchestrator.create_task", _boom)

    async with real_committed_event(factory) as event_id:
        report = await run_triage_cycle(session_factory=factory)

        assert report.other_failures == 1
        assert report.tasks_created == 0
        async with factory() as session:
            event = await session.get(NewsEvent, event_id)
            assert event is not None
            assert event.status == EventStatus.PROCESSING
        assert await _active_task_count(factory, event_id) == 0


# ---------------------------------------------------------------------------
# Transaction-discipline tests (MAJOR finding 1's required proofs)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_claim_committed_before_triage_executes(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with real_committed_event(factory) as event_id:
        async with factory() as orchestrator_session:
            from services.triage_orchestrator import _claim_new_event

            now = datetime.now(UTC)
            assert await _claim_new_event(orchestrator_session, event_id, now=now) is True
            await orchestrator_session.commit()

            observed: dict[str, EventStatus] = {}
            verify_tasks: list[asyncio.Task[None]] = []

            async def _verify_status_during_triage() -> None:
                async with factory() as verify_session:
                    event = await verify_session.get(NewsEvent, event_id)
                    assert event is not None
                    observed["status_during_triage"] = event.status

            def _check_and_call(*args: object, **kwargs: object) -> object:
                # decide_triage() (M1) is a plain, pure, synchronous function - _run_phase_b()
                # calls it without `await`, so this replacement must match that calling
                # convention exactly (a synchronous callable), not an `async def`, or it
                # would return an un-awaited coroutine instead of a TriageResult. The
                # verification read still uses a real, independent, second AsyncSession
                # (per this test's own docstring requirement) - scheduled as a task here and
                # awaited below, after _run_phase_b() returns.
                verify_tasks.append(asyncio.get_running_loop().create_task(_verify_status_during_triage()))
                from services.triage import decide_triage as real_decide_triage

                return real_decide_triage(*args, **kwargs)  # type: ignore[arg-type]

            monkeypatch.setattr("services.triage_orchestrator.decide_triage", _check_and_call)

            report = TriageCycleReport()
            await _run_phase_b(orchestrator_session, event_id, report)

            for task in verify_tasks:
                await task

        assert observed["status_during_triage"] == EventStatus.PROCESSING


@pytest.mark.asyncio
async def test_claim_committed_before_create_task_executes(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async with real_committed_event(factory) as event_id:
        async with factory() as orchestrator_session:
            from services.triage_orchestrator import _claim_new_event

            now = datetime.now(UTC)
            assert await _claim_new_event(orchestrator_session, event_id, now=now) is True
            await orchestrator_session.commit()

            observed: dict[str, EventStatus] = {}

            async def _check_then_raise(session: AsyncSession, command: object) -> None:
                async with factory() as verify_session:
                    event = await verify_session.get(NewsEvent, event_id)
                    assert event is not None
                    observed["status_during_create_task"] = event.status
                raise RuntimeError("stop before create_task's own commit")

            monkeypatch.setattr("services.triage_orchestrator.create_task", _check_then_raise)

            report = TriageCycleReport()
            await _run_phase_b(orchestrator_session, event_id, report)

        assert observed["status_during_create_task"] == EventStatus.PROCESSING
        assert report.other_failures == 1


@pytest.mark.asyncio
async def test_post_claim_failure_triggers_rollback_session_remains_usable(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(session: AsyncSession, command: object) -> None:
        raise RuntimeError("simulated failure")

    monkeypatch.setattr("services.triage_orchestrator.create_task", _boom)

    async with real_committed_event(factory) as event_id:
        async with factory() as session:
            from services.triage_orchestrator import _claim_new_event

            assert await _claim_new_event(session, event_id, now=datetime.now(UTC)) is True
            await session.commit()

            report = TriageCycleReport()
            await _run_phase_b(session, event_id, report)

            # The session MUST remain usable immediately afterward - not left in
            # Postgres's InFailedSqlTransaction state.
            result = await session.execute(select(1))
            assert result.scalar() == 1


@pytest.mark.asyncio
async def test_later_events_in_the_same_batch_survive_an_earlier_events_failure(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    from services.workflow_service import create_task as real_create_task

    async def _fail_only_for_first(session: AsyncSession, command: object) -> object:
        if getattr(command, "event_id", None) == first_event_id:
            raise RuntimeError("simulated failure for the first event only")
        return await real_create_task(session, command)  # type: ignore[arg-type]

    async with real_committed_event(factory) as first_event_id, real_committed_event(factory) as second_event_id:
        monkeypatch.setattr("services.triage_orchestrator.create_task", _fail_only_for_first)

        report = await run_triage_cycle(session_factory=factory)

        assert report.other_failures == 1
        assert report.tasks_created == 1

        async with factory() as session:
            first_event = await session.get(NewsEvent, first_event_id)
            assert first_event is not None
            assert first_event.status == EventStatus.PROCESSING
        assert await _active_task_count(factory, first_event_id) == 0

        assert await _active_task_count(factory, second_event_id) == 1


@pytest.mark.asyncio
async def test_residual_processing_state_remains_recoverable_on_a_later_pass(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _boom(session: AsyncSession, command: object) -> None:
        raise RuntimeError("simulated failure")

    async with real_committed_event(factory) as event_id:
        monkeypatch.setattr("services.triage_orchestrator.create_task", _boom)
        monkeypatch.setattr("core.config.settings.stale_processing_threshold_seconds", 1)

        first_report = await run_triage_cycle(session_factory=factory)
        assert first_report.other_failures == 1
        assert await _active_task_count(factory, event_id) == 0

        # Age the event past the (now 1-second) threshold, then restore create_task
        # and run a second pass.
        async with factory() as session:
            event = await session.get(NewsEvent, event_id)
            assert event is not None
            event.updated_at = datetime.now(UTC) - timedelta(seconds=5)
            await session.commit()

        monkeypatch.undo()
        monkeypatch.setattr("core.config.settings.stale_processing_threshold_seconds", 1)

        second_report = await run_triage_cycle(session_factory=factory)
        assert second_report.events_recovered == 1
        assert second_report.tasks_created == 1
        assert await _active_task_count(factory, event_id) == 1


@pytest.mark.asyncio
async def test_losing_claimant_never_runs_phase_b(
    factory: async_sessionmaker[AsyncSession], monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    async def _tracking_run_phase_b(session: AsyncSession, event_id: UUID, report: TriageCycleReport) -> None:
        calls.append(str(event_id))

    async with real_committed_event(factory) as event_id:
        now = datetime.now(UTC)
        async with factory() as pre_claim_session:
            from services.triage_orchestrator import _claim_new_event

            # Simulate another instance already having claimed the event.
            assert await _claim_new_event(pre_claim_session, event_id, now=now) is True
            await pre_claim_session.commit()

        monkeypatch.setattr("services.triage_orchestrator._run_phase_b", _tracking_run_phase_b)

        report = await run_triage_cycle(session_factory=factory)

        assert str(event_id) not in calls
        assert report.claim_races_lost >= 0  # the event is no longer NEW by the time the cycle runs


# ---------------------------------------------------------------------------
# Rerun safety / logging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rerun_after_full_success_creates_no_duplicate_task(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_id:
        await run_triage_cycle(session_factory=factory)
        await run_triage_cycle(session_factory=factory)

        assert await _active_task_count(factory, event_id) == 1


@pytest.mark.asyncio
async def test_triage_decision_is_logged_with_required_fields(
    factory: async_sessionmaker[AsyncSession], caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    caplog.set_level(logging.INFO, logger="services.triage_orchestrator")

    async with real_committed_event(factory):
        await run_triage_cycle(session_factory=factory)

    decision_records = [r for r in caplog.records if r.msg == "phase9_triage_decision"]
    assert len(decision_records) >= 1
    record = decision_records[0]
    for field in (
        "event_id",
        "source_id",
        "freshness_tier",
        "reliability_score",
        "priority",
        "reference_now",
    ):
        assert hasattr(record, field), f"missing required log field: {field}"


# ---------------------------------------------------------------------------
# Concurrency: two full cycles against a shared pool of events
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_cycles_produce_exactly_one_task_per_event(
    factory: async_sessionmaker[AsyncSession],
) -> None:
    async with real_committed_event(factory) as event_a, real_committed_event(factory) as event_b:
        _, factory_2 = independent_session_factory()
        try:
            report_a, report_b = await asyncio.gather(
                run_triage_cycle(session_factory=factory), run_triage_cycle(session_factory=factory_2)
            )
        finally:
            pass

        assert await _active_task_count(factory, event_a) == 1
        assert await _active_task_count(factory, event_b) == 1
        assert report_a.tasks_created + report_b.tasks_created == 2
