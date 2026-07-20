"""Entry point for running one Triage cycle.

Launch with:
    python -m scripts.run_triage

Contains no orchestration logic itself - it only wires up logging and calls
services.triage_orchestrator.run_triage_cycle(). Production scheduling
(cron, systemd timer, task queue) remains deferred (Contract §7.4) - this
script has the same status scripts/run_collector.py itself has today.
"""
import asyncio

from core.logging import setup_logging
from services.triage_orchestrator import run_triage_cycle


async def main() -> None:
    """Run a single Triage cycle and exit."""
    setup_logging()
    await run_triage_cycle()


if __name__ == "__main__":
    asyncio.run(main())
