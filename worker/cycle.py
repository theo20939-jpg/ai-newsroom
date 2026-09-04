"""One automation cycle: collection, then Triage, then the (flag-gated, default-inert) EVENT_RECAP
scheduler.

Phase 12 Architecture Contract §6: calls the two existing, unmodified services
(services.collector.run_collection_cycle, services.triage_orchestrator.run_triage_cycle)
sequentially, in that order, every cycle - never concurrently, never duplicated. Both are
imported as module-level names specifically so tests can monkeypatch
worker.cycle.run_collection_cycle / worker.cycle.run_triage_cycle directly (Contract §24).

R2.10-RUNTIME-2: `services.event_recap_scheduler.run_event_recap_scan()` is called unconditionally,
every cycle, after Triage - exactly like the two calls above, also imported as a module-level name
for the same monkeypatch-ability. That function itself decides whether to do anything at all
(`settings.event_recap_scheduler_enabled`, default False everywhere) - when disabled, it returns
immediately without issuing a single Story query, so calling it unconditionally here is
byte/semantically equivalent to not calling it at all (§24's own explicit parity requirement,
verified directly by this module's own test suite).

This module catches nothing itself: services.collector.run_collection_cycle() already never
raises (its own outer try/except Exception guarantees a normal return), services.event_recap_
scheduler.run_event_recap_scan() already isolates per-Story failures internally and never raises
for an ordinary per-item problem, and services.triage_orchestrator.run_triage_cycle()'s real,
unwrapped top-level exception (if any) propagates through this function unmodified - worker/
main.py's own cycle-level handler is the one and only place that catches it (Contract §13/§14).
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timezone

from services.collector import CollectionReport, run_collection_cycle
from services.event_recap_scheduler import EventRecapScanResult, run_event_recap_scan
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
    # R2.10-RUNTIME-2: always populated (run_event_recap_scan() itself returns mode="disabled"
    # rather than None when its own flag is off) - never Optional, so no existing caller's own
    # field-access pattern needs a None-check added.
    event_recap: EventRecapScanResult


async def run_automation_cycle() -> AutomationCycleResult:
    """Run one collection pass, then one Triage pass, then one EVENT_RECAP scheduler pass
    (inert unless explicitly enabled), and return a combined summary."""
    started_at = datetime.now(timezone.utc)
    collection_report = await run_collection_cycle()
    triage_report = await run_triage_cycle()
    event_recap_report = await run_event_recap_scan()
    finished_at = datetime.now(timezone.utc)

    result = AutomationCycleResult(
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=(finished_at - started_at).total_seconds(),
        collection=collection_report,
        triage=triage_report,
        event_recap=event_recap_report,
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
            "event_recap_mode": event_recap_report.mode,
        },
    )
    return result
