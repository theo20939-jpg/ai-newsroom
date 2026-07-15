"""CLI entry point for importing NewsSource records from a JSON file.

Launch with:
    python -m scripts.import_sources path/to/sources.json

Expected file shape:
    {"sources": [{"name": "...", "type": "TELEGRAM", "url": "@channel"}, ...]}

Required fields per entry: name, type, url.
Optional fields: category, reliability_score, active.

This script only handles argument parsing, file I/O and input validation;
the actual upsert decision logic lives in services.source_importer.
"""
import argparse
import asyncio
import json
import logging

from pydantic import ValidationError

from core.logging import setup_logging
from database.session import async_session_factory
from schemas.source_import import SourceImportItem
from services.source_importer import import_sources

logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    """Parse the required JSON file path argument."""
    parser = argparse.ArgumentParser(description="Import NewsSource records from a JSON file.")
    parser.add_argument("file_path", help="Path to a JSON file with a top-level 'sources' list")
    return parser.parse_args()


def _load_items(file_path: str) -> tuple[list[SourceImportItem], list[str]]:
    """Read and validate the import file; return (valid items, invalid reasons)."""
    with open(file_path, encoding="utf-8") as handle:
        raw = json.load(handle)

    valid_items: list[SourceImportItem] = []
    invalid_reasons: list[str] = []

    for index, entry in enumerate(raw.get("sources", [])):
        try:
            valid_items.append(SourceImportItem.model_validate(entry))
        except ValidationError as error:
            invalid_reasons.append(f"sources[{index}]: {error}")

    return valid_items, invalid_reasons


async def main() -> None:
    """Validate the given file and upsert its sources into the database."""
    setup_logging()
    args = _parse_args()

    valid_items, invalid_reasons = _load_items(args.file_path)
    for reason in invalid_reasons:
        logger.warning("Invalid source entry skipped: %s", reason)

    async with async_session_factory() as session:
        report = await import_sources(session, valid_items)

    logger.info(
        "Import summary: created=%d updated=%d skipped=%d invalid=%d",
        report.created,
        report.updated,
        report.skipped,
        len(invalid_reasons),
    )


if __name__ == "__main__":
    asyncio.run(main())
