"""Entry point for running the NEWS_ANALYSIS automation worker.

Launch with:
    python -m worker.analysis_main

Mirrors worker/main.py's own established shape (Phase 12) for the enabled/disabled loop and
signal handling. The AI integration layer is assembled exactly as scripts/run_content_
generation.py's own already-established production pattern (Phase 10's first real caller of
assemble_ai_integration_layer()) - no redis_client kwarg passed explicitly, matching that one,
real, existing production precedent exactly.
"""
import asyncio
import logging
import signal
from pathlib import Path

from core.config import settings
from core.logging import setup_logging
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.prompts.file_repository import FilePromptRepository
from worker.analysis_cycle import run_analysis_cycle

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def _run_enabled_loop() -> None:
    """startup -> assemble AI layer once -> run one cycle -> cancellation-aware
    sleep(interval) -> next cycle. Cadence is cycle duration + configured interval (not
    wall-clock-fixed), mirroring worker/main.py's own disclosed, accepted behavior exactly."""
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)  # constructed once

    while True:
        try:
            await run_analysis_cycle(ai_layer.capability_registry)
        except Exception:
            logger.exception("analysis_cycle_failed")
        await asyncio.sleep(settings.news_analysis_poll_interval_seconds)


async def _run_disabled_idle() -> None:
    """Deterministic idle-while-alive model for news_analysis_enabled=False, mirroring
    worker/main.py's own _run_disabled_idle() exactly - no cycle, no DB/AI access, no restart
    loop under `restart: unless-stopped`."""
    logger.info("news_analysis_enabled is False - analysis worker idling, no cycles will run")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("analysis_worker_shutting_down_disabled")
        raise


async def main() -> None:
    setup_logging()
    task = asyncio.current_task()
    assert task is not None
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, task.cancel)
        except NotImplementedError:
            pass  # Windows dev-only limitation, identical to worker/main.py's own guard

    try:
        if not settings.news_analysis_enabled:
            await _run_disabled_idle()
            return
        await _run_enabled_loop()
    except asyncio.CancelledError:
        logger.info("analysis_worker_shutdown_complete")
        raise


if __name__ == "__main__":
    asyncio.run(main())
