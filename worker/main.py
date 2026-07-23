"""Entry point for running the fresh-news automation worker.

Launch with:
    python -m worker.main

Phase 12 Architecture Contract §5/§14: a dedicated, single-purpose async worker process, matching
this repository's own established entry-point shape (bot/main.py, every scripts/run_*.py file).
"""
import asyncio
import logging
import signal

from core.config import settings
from core.logging import setup_logging
from worker.cycle import run_automation_cycle

logger = logging.getLogger(__name__)


async def _run_enabled_loop() -> None:
    """startup -> run one cycle -> cancellation-aware sleep(interval) -> next cycle.

    Cadence is cycle duration + configured interval (not wall-clock-fixed) - a cycle taking
    longer than the interval simply extends the effective start-to-start cadence (Contract §28,
    disclosed, not a defect). `except Exception` only: an ordinary cycle failure (in practice,
    only Triage's own real top-level exception ever reaches here - collection never raises, per
    services.collector.run_collection_cycle's own outer try/except) is logged and the loop
    proceeds to the next scheduled interval. asyncio.CancelledError is a BaseException subclass
    and is never caught here - it propagates uncaught out of this loop, through both the cycle
    await and the interval asyncio.sleep() (itself a standard, correctly-cancellable await),
    into main()'s own outer handler (Contract §13).
    """
    while True:
        try:
            await run_automation_cycle()
        except Exception:
            logger.exception("automation_cycle_failed")
        await asyncio.sleep(settings.news_collection_interval_seconds)


async def _run_disabled_idle() -> None:
    """Deterministic idle-while-alive model for news_collection_enabled=False (Contract §14).

    Logs the disabled state exactly once, then waits indefinitely on an Event that is never
    set - blocks without polling or busy-waiting, while remaining fully cancellation-responsive
    (asyncio.Event.wait() is implemented on a Future and raises CancelledError correctly when the
    task is cancelled). No cycle, no DB/source access. Chosen specifically so that a disabled
    worker deployed with `restart: unless-stopped` never causes a Docker restart loop - an
    immediate return/exit here would.
    """
    logger.info("news_collection_enabled is False - automation worker idling, no cycles will run")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("automation_worker_shutting_down_disabled")
        raise


async def main() -> None:
    """Create the worker task, wire graceful shutdown, and run until cancelled."""
    setup_logging()

    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            # add_signal_handler is not implemented on Windows' default event loop. No fallback
            # handler is registered here; local Windows dev remains stoppable only through the
            # interpreter's normal process-interruption path, whose exact timing during a long
            # await is not guaranteed by this module. The Contract's actual deployment target is
            # Linux/Docker, where this handler registers successfully for both signals.
            pass

    try:
        if not settings.news_collection_enabled:
            await _run_disabled_idle()
            return
        await _run_enabled_loop()
    except asyncio.CancelledError:
        logger.info("automation_worker_shutdown_complete")
        raise


if __name__ == "__main__":
    asyncio.run(main())
