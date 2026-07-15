"""Entry point for running one Source Collector pass.

Launch with:
    python -m scripts.run_collector

Contains no collection logic itself - it only wires up logging and calls
services.collector.run_collection_cycle().
"""
import asyncio

from core.logging import setup_logging
from services.collector import run_collection_cycle


async def main() -> None:
    """Run a single collection cycle and exit."""
    setup_logging()
    await run_collection_cycle()


if __name__ == "__main__":
    asyncio.run(main())
