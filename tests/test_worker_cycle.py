"""Tests for worker.cycle.run_automation_cycle() - pure orchestration, no real DB or network
(collection/triage are mocked at the worker.cycle module boundary, mirroring Phase 11's own
proven handler-test-double convention, per Contract §24)."""
import ast
import asyncio
import inspect
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import worker.cycle
from services.collector import CollectionReport
from services.event_recap_scheduler import EventRecapScanResult
from services.triage_orchestrator import TriageCycleReport
from worker.cycle import run_automation_cycle


@pytest.mark.asyncio
async def test_collection_runs_before_triage_exactly_once_each() -> None:
    call_order: list[str] = []

    async def fake_collection() -> CollectionReport:
        call_order.append("collection")
        return CollectionReport()

    async def fake_triage() -> TriageCycleReport:
        call_order.append("triage")
        return TriageCycleReport()

    with (
        patch("worker.cycle.run_collection_cycle", side_effect=fake_collection) as mocked_collection,
        patch("worker.cycle.run_triage_cycle", side_effect=fake_triage) as mocked_triage,
    ):
        await run_automation_cycle()

    assert call_order == ["collection", "triage"]
    mocked_collection.assert_called_once_with()
    mocked_triage.assert_called_once_with()


@pytest.mark.asyncio
async def test_triage_still_runs_after_collection_reports_source_failures() -> None:
    failing_collection_report = CollectionReport(sources_processed=1, sources_failed=1)

    with (
        patch(
            "worker.cycle.run_collection_cycle",
            new=AsyncMock(return_value=failing_collection_report),
        ),
        patch(
            "worker.cycle.run_triage_cycle", new=AsyncMock(return_value=TriageCycleReport())
        ) as mocked_triage,
    ):
        await run_automation_cycle()

    mocked_triage.assert_called_once_with()


@pytest.mark.asyncio
async def test_triage_exception_propagates_out_of_run_automation_cycle() -> None:
    with (
        patch(
            "worker.cycle.run_collection_cycle", new=AsyncMock(return_value=CollectionReport())
        ),
        patch("worker.cycle.run_triage_cycle", new=AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        with pytest.raises(RuntimeError, match="boom"):
            await run_automation_cycle()


@pytest.mark.asyncio
async def test_cancelled_error_from_triage_propagates_uncaught() -> None:
    with (
        patch(
            "worker.cycle.run_collection_cycle", new=AsyncMock(return_value=CollectionReport())
        ),
        patch(
            "worker.cycle.run_triage_cycle",
            new=AsyncMock(side_effect=asyncio.CancelledError()),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await run_automation_cycle()


@pytest.mark.asyncio
async def test_event_recap_scan_runs_after_triage_and_populates_result() -> None:
    """R2.10-RUNTIME-2: the new scheduler call is wired in after collection+triage, every cycle,
    and its (real, default-inert) result is always attached to AutomationCycleResult.event_recap -
    never None. Uses the REAL run_event_recap_scan() (not mocked) since settings.event_recap_
    scheduler_enabled defaults False everywhere, so this call is genuinely a no-op query-free
    no-op - exercising the true default-disabled wiring end to end, not a stand-in."""
    call_order: list[str] = []

    async def fake_collection() -> CollectionReport:
        call_order.append("collection")
        return CollectionReport()

    async def fake_triage() -> TriageCycleReport:
        call_order.append("triage")
        return TriageCycleReport()

    with (
        patch("worker.cycle.run_collection_cycle", side_effect=fake_collection),
        patch("worker.cycle.run_triage_cycle", side_effect=fake_triage),
    ):
        result = await run_automation_cycle()

    assert call_order == ["collection", "triage"]
    assert result.event_recap == EventRecapScanResult(mode="disabled")


def test_worker_cycle_imports_no_downstream_execution_module() -> None:
    """Mechanical AST proof that worker/cycle.py never imports WorkflowRunner/Capability/
    CONTENT_GENERATION machinery (Contract §9/§23)."""
    source = inspect.getsource(worker.cycle)
    tree = ast.parse(source)

    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_names.add(node.module)

    forbidden_prefixes = (
        "workflows.runner",
        "capabilities.executor",
        "capabilities.",
        "scripts.run_content_generation",
    )
    for name in imported_names:
        assert not any(name.startswith(prefix) for prefix in forbidden_prefixes), (
            f"worker/cycle.py must not import {name}"
        )


@pytest.mark.asyncio
async def test_automation_cycle_result_duration_matches_timestamps() -> None:
    async def slow_collection() -> CollectionReport:
        return CollectionReport()

    async def slow_triage() -> TriageCycleReport:
        return TriageCycleReport()

    with (
        patch("worker.cycle.run_collection_cycle", side_effect=slow_collection),
        patch("worker.cycle.run_triage_cycle", side_effect=slow_triage),
    ):
        result = await run_automation_cycle()

    assert result.duration_seconds >= 0
    assert result.finished_at >= result.started_at
    expected = (result.finished_at - result.started_at).total_seconds()
    assert result.duration_seconds == pytest.approx(expected)
    assert datetime.now(timezone.utc) - result.finished_at < timedelta(seconds=5)
