"""BudgetGuard Protocol (docs/phase6_architecture_contract.md §9).

Pre-flight, READ-ONLY budget check - may reject a proposed call before any
provider call is made. Never writes spend data, never calls LLMGateway or a
provider. A separate, non-overlapping concern from CostTracker (services.
cost_tracker), which is post-hoc and write-only - the two are never merged
(P5, §9's binding rule).

No implementation exists in Phase 6: this is a contract only, exercised in
tests against fakes.
"""
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from database.models.editorial_task import TaskPriority
from schemas.capability import CapabilityUsage


class BudgetCheckRequest(BaseModel):
    """What a Capability proposes to spend, before making the call."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    capability_name: str
    priority: TaskPriority
    estimated_usage: CapabilityUsage


class BudgetGuard(Protocol):
    """Consulted by a Capability before each LLMGateway call it intends to make."""

    async def check(self, request: BudgetCheckRequest) -> None:
        """Raise BudgetExceededError (capabilities.errors) if the proposed call
        would exceed budget. Read-only - MUST NOT write spend data, MUST NOT
        call LLMGateway or a provider."""
        ...
