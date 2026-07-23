"""One automation cycle: collection, then Triage. No business logic of its own.

Phase 12 Architecture Contract §6: calls the two existing, unmodified services
(services.collector.run_collection_cycle, services.triage_orchestrator.run_triage_cycle)
sequentially, in that order, every cycle - never concurrently, never duplicated. Both are
imported as module-level names specifically so tests can monkeypatch
worker.cycle.run_collection_cycle / worker.cycle.run_triage_cycle directly (Contract §24).

This module catches nothing itself: services.collector.run_collection_cycle() already never
raises (its own outer try/except Exception guarantees a normal return), and
services.triage_orchestrator.run_triage_cycle()'s real, unwrapped top-level exception (if any)
propagates through this function unmodified - worker/main.py's own cycle-level handler is the
one and only place that catches it (Contract §13/§14).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from services.collector import CollectionReport, run_collection_cycle
from services.triage_orchestrator import TriageCycleReport, run_triage_cycle

logger = logging.getLogger(__name__)


@dataclass
class AutomationCycleResult:
    """Summary of one automation cycle, used for logging."""

    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    collection: CollectionReport
    triage: TriageCycleReport


async def run_automation_cycle() -> AutomationCycleResult:
    """Run one collection pass, then one Triage pass, and return a combined summary."""
    started_at = datetime.now(timezone.utc)
    collection_report = await run_collection_cycle()
    triage_report = await run_triage_cycle()
    finished_at = datetime.now(timezone.utc)

    result = AutomationCycleResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
        collection=collection_report,
        triage=triage_report,
    )
    logger.info(
        "automation_cycle_finished",
        extra={
            "duration_seconds": result.duration_seconds,
            "sources_processed": collection_report.sources_processed,
            "sources_failed": collection_report.sources_failed,
            "events_created": collection_report.events_created,
            "duplicates_skipped": collection_report.duplicates_skipped,
            "events_claimed": triage_report.events_claimed,
            "events_recovered": triage_report.events_recovered,
            "tasks_created": triage_report.tasks_created,
        },
    )
    return result
