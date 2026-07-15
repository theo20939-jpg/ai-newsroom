"""CLI entry point for importing the newsroom_sources_v1 config package.

Launch with:
    python -m scripts.import_source_pack

Loads and validates every source in config/newsroom_sources_v1 through the
Universal Source Registry, then imports the ones with a working adapter into
NewsSource through services.source_pack_importer. This script only wires the
two together and logs the combined summary; all loading/filtering/upsert
decisions live in services.source_registry and services.source_pack_importer.
"""
import asyncio

from core.logging import setup_logging
from database.session import async_session_factory
from services.source_pack_importer import import_source_pack
from services.source_registry import load_source_pack


async def main() -> None:
    """Load the source pack and upsert its importable sources into the database."""
    setup_logging()

    definitions, _registry_report = load_source_pack()

    async with async_session_factory() as session:
        await import_source_pack(session, definitions)


if __name__ == "__main__":
    asyncio.run(main())
