"""Converts SourceDefinition objects into NewsSource rows (Source Pack Importer).

Bridges the Universal Source Registry (schemas.source_definition.SourceDefinition,
which holds every field the config package defines) down to the pre-existing,
unchanged services.source_importer, which only knows SourceImportItem: name,
type, url, category, reliability_score, active. No new database columns are
introduced here - priority, tags, fetch_interval and adapter stay on the
SourceDefinition objects and are simply not exported.

A source only reaches NewsSource if its adapter resolves to one already
implemented (see services.adapter_keys, the single roster shared with
services.adapter_registry - resolution here uses the exact same
resolve_adapter_key() rule so the two never disagree about what counts as
implemented), it is enabled, and every credential named in `auth` is
configured (see core.auth_resolution - checked against core.config.settings
where a Settings field exists, since .env values don't reach os.environ).
Anything else is counted (pending_adapter / disabled / auth_excluded) and
skipped - never imported, never raised.
"""
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from core.auth_resolution import is_auth_configured
from schemas.source_definition import SourceDefinition
from schemas.source_import import SourceImportItem
from services.adapter_keys import ADAPTER_KEY_TO_SOURCE_TYPE, resolve_adapter_key
from services.source_importer import ImportReport, import_sources

logger = logging.getLogger(__name__)


@dataclass
class SourcePackImportReport:
    """Summary of one source pack import run."""

    pending_adapter: int = 0
    disabled: int = 0
    auth_excluded: int = 0
    submitted: int = 0
    import_report: ImportReport = field(default_factory=ImportReport)


async def import_source_pack(
    session: AsyncSession, definitions: list[SourceDefinition]
) -> SourcePackImportReport:
    """Filter SourceDefinitions down to importable ones and upsert them."""
    report = SourcePackImportReport()
    items: list[SourceImportItem] = [
        item
        for definition in definitions
        if (item := _to_import_item(definition, report)) is not None
    ]

    report.submitted = len(items)
    report.import_report = await import_sources(session, items)

    logger.info(
        "Source pack import: submitted=%d pending_adapter=%d disabled=%d auth_excluded=%d "
        "created=%d updated=%d skipped=%d",
        report.submitted,
        report.pending_adapter,
        report.disabled,
        report.auth_excluded,
        report.import_report.created,
        report.import_report.updated,
        report.import_report.skipped,
    )
    return report


def _to_import_item(
    definition: SourceDefinition, report: SourcePackImportReport
) -> SourceImportItem | None:
    """Decide whether one SourceDefinition is importable, and map it if so.

    Adapter resolution is checked first and unconditionally: a source with no
    working adapter is pending_adapter regardless of its enabled/auth state.
    """
    key = resolve_adapter_key(definition.adapter, definition.type)
    source_type = ADAPTER_KEY_TO_SOURCE_TYPE.get(key) if key is not None else None
    if source_type is None:
        report.pending_adapter += 1
        logger.info(
            "Source %s pending_adapter: type=%s adapter=%s", definition.id, definition.type, definition.adapter
        )
        return None

    if not definition.enabled:
        report.disabled += 1
        return None

    if not _auth_satisfied(definition):
        report.auth_excluded += 1
        logger.info("Source %s auth_excluded: missing %s", definition.id, definition.auth)
        return None

    return SourceImportItem(
        name=definition.name,
        type=source_type,
        url=definition.url,
        category=definition.category,
        reliability_score=definition.reliability,
        active=definition.enabled,
    )


def _auth_satisfied(definition: SourceDefinition) -> bool:
    """Check that every credential named in `auth` is configured."""
    if not definition.auth:
        return True

    required = [name.strip() for name in definition.auth.split(",")]
    return all(is_auth_configured(name) for name in required)
