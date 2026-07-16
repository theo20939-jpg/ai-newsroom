"""CostTracker Protocol (docs/phase6_architecture_contract.md §9).

Post-hoc, WRITE-ONLY: given a completed CapabilityCall, computes Decimal cost
from its own model-price table and would write the AIExecution row. Never
performs pre-flight checks (that is BudgetGuard's exclusive job), never calls
a provider.

Per Amendment B (§16): CostTracker's write path is a Protocol only in
Phase 6. It is never invoked by capabilities.executor.CapabilityExecutor -
no implementation exists, and no real AIExecution row is ever written by
anything built in this phase.
"""
from typing import Protocol
from uuid import UUID

from schemas.capability import CapabilityCall


class CostTracker(Protocol):
    """Records actual usage/cost for one completed CapabilityCall. Never invoked in Phase 6."""

    async def record(self, task_id: UUID, capability_name: str, call: CapabilityCall) -> None:
        """Compute cost from call.usage + call.model_used and persist an
        AIExecution row. MUST NOT perform pre-flight checks. MUST NOT call a
        provider."""
        ...
