"""Contract/shape tests for services.budget_guard - no database, no network.

Updated for Amendment C (docs/phase7_architecture_contract.md §25): BudgetGuard.check() now
takes (capability_name, priority, worst_case: Decimal) directly - the estimate CostEstimator
(§15.1) produces - rather than Phase 6's original BudgetCheckRequest{estimated_usage:
CapabilityUsage}. No production code called the old signature (Amendment B already deferred
any real invocation, and capabilities/executor.py never called it either), so this is an
update to the exercised shape, not a break to a real call site.
"""
from decimal import Decimal

import pytest

from capabilities.errors import BudgetExceededError
from database.models.editorial_task import TaskPriority
from services.budget_guard import BudgetGuard


class FakeAllowingBudgetGuard:
    """Always allows - proves the Protocol is implementable without ever writing spend data."""

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        return None


class FakeRejectingBudgetGuard:
    """Always rejects with BudgetExceededError - a PermanentCapabilityError subtype."""

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        raise BudgetExceededError(f"budget exceeded for {capability_name}")


@pytest.mark.asyncio
async def test_allowing_guard_permits_the_call() -> None:
    guard: BudgetGuard = FakeAllowingBudgetGuard()
    await guard.check("research", TaskPriority.B, Decimal("0.05"))  # must not raise


@pytest.mark.asyncio
async def test_rejecting_guard_raises_budget_exceeded_error() -> None:
    guard: BudgetGuard = FakeRejectingBudgetGuard()
    with pytest.raises(BudgetExceededError):
        await guard.check("research", TaskPriority.B, Decimal("0.05"))
