"""Entry point for running the automatic CONTENT_GENERATION + Telegram notification worker.

Launch with:
    python -m worker.content_main

Mirrors worker/analysis_main.py's own established shape (Phase 13) exactly for the enabled/
disabled loop and signal handling. Additionally assembles a real Bot once at startup (via the
existing, unmodified bot/loader.py::create_bot()), alongside the real AI integration layer.
"""
import asyncio
import logging
import signal
from pathlib import Path

from bot.loader import create_bot
from core.config import settings
from core.logging import setup_logging
from integrations.llm_gateway.boot import assemble_ai_integration_layer
from integrations.llm_gateway.models.catalog import build_model_registry
from integrations.prompts.file_repository import FilePromptRepository
from services.image_retention import run_retention_cleanup
from services.pricing_catalog import ModelRegistryPricingCatalog
from worker.content_cycle import run_content_cycle

logger = logging.getLogger(__name__)

_PROMPTS_ROOT = Path(__file__).resolve().parent.parent / "prompts"


async def _run_enabled_loop() -> None:
    """startup -> assemble AI layer + Bot once -> run one cycle -> cancellation-aware
    sleep(interval) -> next cycle. Cadence is cycle duration + configured interval (not
    wall-clock-fixed), mirroring worker/analysis_main.py's own disclosed, accepted behavior
    exactly."""
    prompt_repository = FilePromptRepository(_PROMPTS_ROOT)
    ai_layer = assemble_ai_integration_layer(settings, prompt_repository)  # constructed once
    bot = create_bot()  # constructed once, identically regardless of content_generation_dry_run
    # API cost optimization: same pattern as worker/analysis_main.py.
    pricing_catalog = ModelRegistryPricingCatalog(build_model_registry())

    cycle_count = 0
    while True:
        try:
            await run_content_cycle(
                ai_layer.capability_registry, bot,
                cost_tracker=ai_layer.cost_tracker, pricing_catalog=pricing_catalog,
            )
        except Exception:
            logger.exception("content_cycle_failed")

        # Phase 16 M5 (docs/phase16_m5_persistence_and_retention_report.md §15): "least coupled
        # existing owner, no new worker/scheduler" - reuses this loop's own cadence instead of a
        # dedicated timer. Runs every `image_cleanup_every_n_cycles` cycles regardless of
        # `image_candidate_persistence_mode` (a row persisted while a prior mode was active must
        # still expire on schedule even after the mode changes) - cheap no-op scans when the
        # `image_candidates` table has nothing due. Never allowed to affect delivery: swallowed
        # like `run_content_cycle` itself.
        cycle_count += 1
        if cycle_count % settings.image_cleanup_every_n_cycles == 0:
            try:
                await run_retention_cleanup()
            except Exception:
                logger.exception("image_retention_cleanup_failed")

        await asyncio.sleep(settings.content_generation_poll_interval_seconds)


async def _run_disabled_idle() -> None:
    """Deterministic idle-while-alive model for content_generation_enabled=False, mirroring
    worker/analysis_main.py's own _run_disabled_idle() exactly - no cycle, no DB/AI/Telegram
    access, no restart loop under `restart: unless-stopped`."""
    logger.info("content_generation_enabled is False - content worker idling, no cycles will run")
    try:
        await asyncio.Event().wait()
    except asyncio.CancelledError:
        logger.info("content_worker_shutting_down_disabled")
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
            pass  # Windows dev-only limitation, identical to worker/analysis_main.py's own guard

    try:
        if not settings.content_generation_enabled:
            await _run_disabled_idle()
            return
        await _run_enabled_loop()
    except asyncio.CancelledError:
        logger.info("content_worker_shutdown_complete")
        raise


if __name__ == "__main__":
    asyncio.run(main())
