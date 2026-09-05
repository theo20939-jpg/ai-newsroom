"""PRODUCTION-SOURCE-RECONCILIATION-1B §17/§18: closes the known Visual Design Autonomy
observability debt - zero logging previously existed anywhere in
services/visual_designer_brief_service.py or services/visual_regression_service.py, so a founder
had no way to see brief lifecycle events short of querying the database directly.

Log-only, read-nothing-back: this module never changes what any caller does, never blocks a
mutation, and never raises. Mirrors services/director_run_service.py's own
`logger.info("director_run_persisted", extra={...})` convention exactly.

CRITICAL: never logs raw brief text (`VisualDesignerBriefVersion.brief_text`) - only metadata
(scope, version, parent version, reason, evidence STAGE - never the evidence payload itself,
result, cost/model where known). A brief's own creative content has no reason to live in a log
aggregator; the database row is already the durable, queryable record of what it actually says."""
from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

logger = logging.getLogger(__name__)


def _evidence_stage(evidence: dict[str, Any] | None) -> str | None:
    """Extracts only the STAGE label (e.g. "repeated_pattern", "manual") from an evidence payload,
    never the payload itself - `evidence` may carry root-cause detail, feed samples, or other
    content-bearing fields that do not belong in a log line."""
    if not evidence:
        return None
    stage = evidence.get("stage")
    return str(stage) if stage is not None else None


def log_candidate_created(
    *, scope: str, version: int, brief_version_id: UUID, parent_version_id: UUID | None,
    reason: str, evidence: dict[str, Any] | None = None,
) -> None:
    logger.info(
        "visual_brief_candidate_created",
        extra={
            "scope": scope, "brief_version_id": str(brief_version_id), "version": version,
            "parent_version_id": str(parent_version_id) if parent_version_id else None,
            "reason_code": reason, "evidence_stage": _evidence_stage(evidence),
        },
    )


def log_candidate_validated(
    *, scope: str, candidate_version_id: UUID, baseline_version_id: UUID | None, result: str,
    reasons: list[str] | None = None, total_cost: float | None = None,
) -> None:
    logger.info(
        "visual_brief_candidate_validated",
        extra={
            "scope": scope, "brief_version_id": str(candidate_version_id),
            "baseline_version_id": str(baseline_version_id) if baseline_version_id else None,
            "result": result, "reason_code": "; ".join(reasons) if reasons else None,
            "cost_usd": total_cost,
        },
    )


def log_promoted(*, scope: str, version: int, brief_version_id: UUID) -> None:
    logger.info(
        "visual_brief_promoted",
        extra={"scope": scope, "brief_version_id": str(brief_version_id), "version": version, "result": "promoted"},
    )


def log_candidate_rejected(*, scope: str, version: int, brief_version_id: UUID, reason: str) -> None:
    logger.info(
        "visual_brief_candidate_rejected",
        extra={
            "scope": scope, "brief_version_id": str(brief_version_id), "version": version,
            "reason_code": reason, "result": "rejected",
        },
    )


def log_rolled_back(
    *, scope: str, from_version_id: UUID | None, to_version_id: UUID, to_version: int, reason: str,
) -> None:
    logger.info(
        "visual_brief_rolled_back",
        extra={
            "scope": scope, "brief_version_id": str(to_version_id), "version": to_version,
            "rolled_back_from_version_id": str(from_version_id) if from_version_id else None,
            "reason_code": reason, "result": "rolled_back",
        },
    )


def log_frozen(*, scope: str, version: int, brief_version_id: UUID, reason: str) -> None:
    logger.info(
        "visual_brief_frozen",
        extra={"scope": scope, "brief_version_id": str(brief_version_id), "version": version, "reason_code": reason},
    )


def log_unfrozen(*, scope: str, version: int, brief_version_id: UUID, reason: str) -> None:
    logger.info(
        "visual_brief_unfrozen",
        extra={"scope": scope, "brief_version_id": str(brief_version_id), "version": version, "reason_code": reason},
    )
