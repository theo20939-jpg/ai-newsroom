from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest

from core.config import settings
from services.director_editorial_gate import EditorialGateDecision
from services.editorial_treatment import SKIP, STANDARD
from tests.test_content_worker_cycle import (
    _isolated_freshness_window,  # noqa: F401
    _make_completed_news_analysis_task,
    _make_event,
    factory,  # noqa: F401
    test_source,  # noqa: F401
)
from worker.content_cycle import _select_eligible_events, run_content_cycle


def _treatment(value: str) -> SimpleNamespace:
    return SimpleNamespace(treatment=value, reason=f"test {value}")


def _duplicate(blocked: bool) -> SimpleNamespace:
    return SimpleNamespace(blocked=blocked, reason="test duplicate")


def _update(blocked: bool) -> SimpleNamespace:
    return SimpleNamespace(
        would_fail_closed=blocked, story_id=uuid4(), reason="test update"
    )


def _failed_generation() -> SimpleNamespace:
    return SimpleNamespace(content_draft=None)


@pytest.fixture(autouse=True)
def _bounded_refill_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "content_generation_batch_size", 1)
    monkeypatch.setattr(settings, "content_generation_scan_limit", 3)
    monkeypatch.setattr(settings, "instagram_automatic_generation_enabled", False)


@pytest.mark.asyncio
async def test_explicit_refill_pool_is_ranked_and_scan_bounded(
    factory, test_source, _isolated_freshness_window, monkeypatch
) -> None:
    monkeypatch.setattr(settings, "content_generation_batch_size", 1)
    monkeypatch.setattr(settings, "content_generation_scan_limit", 3)
    created = []
    async with factory() as session:
        now = datetime.now(timezone.utc)
        for offset, score in enumerate((71, 90, 80, 99)):
            event = await _make_event(
                session, test_source, published_at=now - timedelta(seconds=offset)
            )
            await _make_completed_news_analysis_task(session, event, score=score)
            created.append((score, event.id))
        refill_pool = await _select_eligible_events(session, max_results=3)

    assert len(refill_pool) == 3
    # The SQL scan cap is hard: the fourth row never enters the Python rank pool. Within the
    # scanned pool, existing score-descending order is preserved.
    scanned_ids = {event_id for _score, event_id in created[:3]}
    assert set(refill_pool) == scanned_ids
    assert refill_pool == [event_id for _score, event_id in sorted(created[:3], reverse=True)]


@pytest.mark.asyncio
async def test_treatment_skip_refills_with_next_ranked_candidate(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "router")
    first, second, third = uuid4(), uuid4(), uuid4()
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(side_effect=[_treatment(SKIP), _treatment(STANDARD)]),
        ),
        patch(
            "worker.content_cycle.check_duplicate_story_delivery",
            new=AsyncMock(return_value=_duplicate(False)),
        ),
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(return_value=_update(False)),
        ),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, second, third],
        )

    assert [call.args[0] for call in generate.await_args_list] == [second]
    assert result.treatment_skipped == 1
    assert result.generation_attempts == 1
    assert result.refill_used is True


@pytest.mark.asyncio
async def test_duplicate_skip_refills_with_next_ranked_candidate(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "router")
    first, second = uuid4(), uuid4()
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle._classify_event_for_router_treatment",
            new=AsyncMock(side_effect=[_treatment(STANDARD), _treatment(STANDARD)]),
        ),
        patch(
            "worker.content_cycle.check_duplicate_story_delivery",
            new=AsyncMock(side_effect=[_duplicate(True), _duplicate(False)]),
        ),
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(return_value=_update(False)),
        ),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, second],
        )

    assert [call.args[0] for call in generate.await_args_list] == [second]
    assert result.duplicate_blocked == 1
    assert result.generation_attempts == 1
    assert result.refill_used is True


@pytest.mark.asyncio
async def test_update_fail_closed_refills_with_next_ranked_candidate(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    first, second = uuid4(), uuid4()
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(side_effect=[_update(True), _update(False)]),
        ),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, second],
        )

    assert [call.args[0] for call in generate.await_args_list] == [second]
    assert result.update_fail_closed_before_generation == 1
    assert result.generation_attempts == 1
    assert result.refill_used is True


@pytest.mark.asyncio
async def test_director_suppression_refills_with_next_ranked_candidate(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    first, second = uuid4(), uuid4()
    suppressed = SimpleNamespace(
        escalation_worthy=False,
        stage2_status="not_used",
        outcome=SimpleNamespace(decision=EditorialGateDecision.HOLD),
        suppress_generation=True,
    )
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(return_value=_update(False)),
        ),
        patch(
            "worker.content_cycle.run_pre_generation_gate",
            new=AsyncMock(side_effect=[suppressed, None]),
        ),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, second],
        )

    assert [call.args[0] for call in generate.await_args_list] == [second]
    assert result.gate_generation_suppressed == 1
    assert result.generation_attempts == 1
    assert result.refill_used is True


@pytest.mark.asyncio
async def test_generation_failure_consumes_slot_and_stops_before_next_candidate(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    first, second = uuid4(), uuid4()
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(return_value=_update(False)),
        ),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, second],
        )

    assert [call.args[0] for call in generate.await_args_list] == [first]
    assert result.generation_attempts == 1
    assert result.failed == 1
    assert result.refill_used is False


@pytest.mark.asyncio
async def test_duplicate_event_ids_are_processed_once_in_stable_order(factory, monkeypatch) -> None:
    monkeypatch.setattr(settings, "editorial_delivery_mode", "legacy")
    monkeypatch.setattr(settings, "content_generation_batch_size", 2)
    first, second = uuid4(), uuid4()
    generate = AsyncMock(return_value=_failed_generation())

    with (
        patch(
            "worker.content_cycle.check_update_would_fail_closed",
            new=AsyncMock(return_value=_update(False)),
        ),
        patch("worker.content_cycle.run_pre_generation_gate", new=AsyncMock(return_value=None)),
        patch("worker.content_cycle.run_content_generation_for_event", new=generate),
    ):
        result = await run_content_cycle(
            AsyncMock(), AsyncMock(), session_factory=factory,
            event_ids_override=[first, first, second],
        )

    assert result.event_ids == [first, second]
    assert [call.args[0] for call in generate.await_args_list] == [first, second]
    assert result.generation_attempts == 2
