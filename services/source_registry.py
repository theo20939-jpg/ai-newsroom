"""Universal Source Registry: loads config/newsroom_sources_v1 (Registry Service).

Read-only config loader - no database access and no decision about what
gets imported. Reads manifest.json for the package's own file list, parses
every sources/*.yaml file it points to, and validates each entry against
SourceDefinition. Only what cannot honestly become a SourceDefinition (schema
violations, duplicate ids) is dropped; everything else - enabled or not,
auth-gated or not, adapter-less or not - is kept in full. Deciding what
actually reaches NewsSource is services.source_pack_importer's job, not this
module's.
"""
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from schemas.source_definition import SourceDefinition

logger = logging.getLogger(__name__)

DEFAULT_PACKAGE_DIR = Path(__file__).resolve().parent.parent / "config" / "newsroom_sources_v1"


@dataclass
class SourceRegistryReport:
    """Summary of one source pack load, used for logging."""

    declared: int = 0
    valid: int = 0
    invalid: int = 0
    duplicate_ids: int = 0
    duplicate_urls: int = 0
    invalid_reasons: list[str] = field(default_factory=list)


def load_source_pack(
    package_dir: Path = DEFAULT_PACKAGE_DIR,
) -> tuple[list[SourceDefinition], SourceRegistryReport]:
    """Load and validate every source declared in the package's manifest.

    Returns the full set of valid, uniquely-identified SourceDefinition
    objects - regardless of `enabled` or `auth` - plus a report of what was
    rejected and why. A malformed individual entry is skipped and logged; it
    never stops the rest of the package from loading.

    URL uniqueness is enforced here, not just id uniqueness: `url` is the
    natural key both SourceImporter (upsert) and the Adapter Registry (source
    lookup) already rely on, so a duplicate url is rejected the same way a
    duplicate id is.
    """
    report = SourceRegistryReport()
    manifest = _load_manifest(package_dir)
    raw_entries = _load_source_entries(package_dir, manifest)
    report.declared = len(raw_entries)

    definitions: list[SourceDefinition] = []
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()

    for index, entry in enumerate(raw_entries):
        try:
            definition = SourceDefinition.model_validate(entry)
        except ValidationError as error:
            report.invalid += 1
            report.invalid_reasons.append(f"sources[{index}] ({entry.get('id', '?')}): {error}")
            logger.warning("Invalid source entry skipped: sources[%d] (%s)", index, entry.get("id", "?"))
            continue

        if definition.id in seen_ids:
            report.duplicate_ids += 1
            report.invalid_reasons.append(f"duplicate id: {definition.id}")
            logger.warning("Duplicate source id skipped: %s", definition.id)
            continue

        normalized_url = _normalize_url(definition.url)
        if normalized_url in seen_urls:
            report.duplicate_urls += 1
            report.invalid_reasons.append(f"duplicate url: {definition.url}")
            logger.warning("Duplicate source url skipped: %s (%s)", definition.id, definition.url)
            continue

        seen_ids.add(definition.id)
        seen_urls.add(normalized_url)
        definitions.append(definition)
        report.valid += 1

    logger.info(
        "Source pack loaded from %s: declared=%d valid=%d invalid=%d duplicate_ids=%d duplicate_urls=%d",
        package_dir,
        report.declared,
        report.valid,
        report.invalid,
        report.duplicate_ids,
        report.duplicate_urls,
    )
    return definitions, report


def _normalize_url(url: str) -> str:
    """Minimal URL normalization: trim whitespace and one trailing slash.

    Deliberately not a full URL-canonicalization routine - source urls in
    this package never vary by case or query-param order, so anything beyond
    this would be speculative complexity. Same formula as
    services.adapter_registry.SourceLookupKey.from_url - kept in sync by
    being this simple, not by sharing an import.
    """
    return url.strip().rstrip("/")


def _load_manifest(package_dir: Path) -> dict[str, Any]:
    """Read manifest.json, the package's own list of its files."""
    manifest_path = package_dir / "manifest.json"
    with manifest_path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _load_source_entries(package_dir: Path, manifest: dict[str, Any]) -> list[dict[str, Any]]:
    """Load and concatenate every sources/*.yaml file listed in the manifest."""
    entries: list[dict[str, Any]] = []

    for relative_path in manifest.get("files", []):
        if not relative_path.startswith("sources/"):
            continue

        file_path = package_dir / relative_path
        with file_path.open(encoding="utf-8") as handle:
            content = yaml.safe_load(handle) or {}

        entries.extend(content.get("sources", []))

    return entries
