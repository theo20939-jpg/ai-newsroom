"""INSTAGRAM-EXECUTION-FOUNDATION-1 section 21/22: publication audit persistence.

No existing Instagram/Social DB model truthfully represents a publication REQUEST/RESULT record
(verified: `database/models/instagram_calendar_item.py` is scheduling metadata with no
container/media-id/publish-status/shadow-marker fields at all; `database/models/
instagram_creative_plan.py::InstagramCreativeDraft.payload` stores the CREATIVE CONTENT proposal,
not a publish attempt). Rather than force either table to carry fields it was never designed for,
this module provides a deterministic, dependency-free JSON-lines audit log as the DEFAULT
persistence for shadow-mode results (works everywhere, no DB required, fully testable) - see
`docs/instagram_execution_foundation_1_report.md` section P for the drafted-but-NOT-applied
`instagram_publication_records` migration this module's own record shape is designed to map onto
directly, once a future phase decides to apply it."""
from __future__ import annotations

import json
from pathlib import Path

from services.instagram_content_package import InstagramContentPackage
from services.instagram_publish_adapter import PublicationResult

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_AUDIT_LOG_PATH = _REPO_ROOT / "artifacts" / "instagram_execution_foundation_1" / "publication_audit.jsonl"


def build_audit_record(result: PublicationResult, package: InstagramContentPackage) -> dict:
    return {
        "publication_result": result.to_dict(),
        "package_summary": {
            "package_id": package.package_id, "content_format": package.content_format.value,
            "opportunity_id": package.opportunity_id, "campaign_id": package.campaign_id,
            "caption": package.caption,
        },
    }


def append_publication_audit_record(
    result: PublicationResult, package: InstagramContentPackage, *, path: Path = DEFAULT_AUDIT_LOG_PATH,
) -> Path:
    """Appends ONE JSON line - never overwrites, never truncates. Creates parent directories if
    needed. Deterministic content (no wall-clock-only fields beyond what `PublicationResult`
    already carries)."""
    record = build_audit_record(result, package)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")
    return path


def read_publication_audit_records(*, path: Path = DEFAULT_AUDIT_LOG_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
