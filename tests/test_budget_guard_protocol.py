"""Contract/shape tests for services.budget_guard - no database, no network."""
import pytest

from database.models.editorial_task import TaskPriority
from capabilities.errors import BudgetExceededError
from schemas.capability import CapabilityUsage
from services.budget_guard import BudgetCheckRequest, BudgetGuard


class FakeAllowingBudgetGuard:
    """Always allows - proves the Protocol is implementable without ever writing spend data."""

    async def check(self, request: BudgetCheckRequest) -> None:
        return None


class FakeRejectingBudgetGuard:
    """Always rejects with BudgetExceededError - a PermanentCapabilityError subtype."""

    async def check(self, request: BudgetCheckRequest) -> None:
        raise BudgetExceededError(f"budget exceeded for {request.capability_name}")


def _request() -> BudgetCheckRequest:
    return BudgetCheckRequest(
        capability_name="research", priority=TaskPriority.B,
        estimated_usage=CapabilityUsage(input_tokens=100, output_tokens=50),
    )


@pytest.mark.asyncio
async def test_allowing_guard_permits_the_call() -> None:
    guard: BudgetGuard = FakeAllowingBudgetGuard()
    await guard.check(_request())  # must not raise


@pytest.mark.asyncio
async def test_rejecting_guard_raises_budget_exceeded_error() -> None:
    guard: BudgetGuard = FakeRejectingBudgetGuard()
    with pytest.raises(BudgetExceededError):
        await guard.check(_request())
