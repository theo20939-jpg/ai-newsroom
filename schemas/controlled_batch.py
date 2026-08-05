"""Phase 18.9 M5: result shapes for the bounded, explicit-allowlist controlled-run tooling
(docs/phase18_9_controlled_run_plan.md).

Additive only - not consumed by `CapabilityExecutor`, `WorkflowRunner`, or any worker/cycle module.
Exists solely for `scripts/phase18_9_controlled_batch_runner.py` and its own tests.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from uuid import UUID


class BoundedTaskStatus(str, Enum):
    COMPLETED = "completed"
    FAILED = "failed"
    DRY_RUN_PREVIEW = "dry_run_preview"
    SKIPPED_NOT_ELIGIBLE = "skipped_not_eligible"
    SKIPPED_BUDGET_EXCEEDED = "skipped_budget_exceeded"
    STOPPED_UNEXPECTED_ERROR = "stopped_unexpected_error"
    STOPPED_UNEXPECTED_MODEL = "stopped_unexpected_model"


@dataclass(frozen=True)
class BoundedTaskOutcome:
    id: UUID
    status: BoundedTaskStatus
    cost: Decimal | None = None
    detail: str | None = None


@dataclass
class BoundedBatchResult:
    outcomes: list[BoundedTaskOutcome] = field(default_factory=list)
    total_cost: Decimal = Decimal("0")
    stopped_early: bool = False
    stop_reason: str | None = None
