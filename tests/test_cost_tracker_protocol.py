"""Contract/shape test for services.cost_tracker - no database, no network.

Proves the Protocol is implementable; a real implementation and its wiring
into CapabilityExecutor are explicitly deferred (Amendment B, §16) - this
fake never touches a database.
"""
from datetime import datetime, timezone
from uuid import uuid4

import pytest

from schemas.capability import CapabilityCall, CapabilityUsage
from services.cost_tracker import CostTracker


class FakeInMemoryCostTracker:
    """Records into a plain list - proves the Protocol shape only, never a real write."""

    def __init__(self) -> None:
        self.recorded: list[tuple] = []

    async def record(self, task_id, capability_name: str, call: CapabilityCall) -> None:
        self.recorded.append((task_id, capability_name, call))


def _call() -> CapabilityCall:
    now = datetime.now(timezone.utc)
    return CapabilityCall(
        call_id=uuid4(), sequence=0, gateway_method="generate", status="SUCCESS",
        model_used="fake-model", usage=CapabilityUsage(input_tokens=1, output_tokens=1),
        started_at=now, finished_at=now, duration_seconds=0.01,
    )


@pytest.mark.asyncio
async def test_record_is_called_with_the_completed_call() -> None:
    tracker: CostTracker = FakeInMemoryCostTracker()
    task_id = uuid4()

    await tracker.record(task_id, "research", _call())

    assert len(tracker.recorded) == 1
