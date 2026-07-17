"""Minimal, permissive in-memory fakes for the Redis-backed/service infrastructure components
(ProviderHealthStore, LatencyTracker, BudgetGuard, CacheStore) - shared across test files that
need to assemble a full RoutingEngine/FallbackPolicy/RoutingGateway pipeline without real
Redis. Each real Redis-backed implementation already has its own dedicated integration tests
(test_provider_health_store.py, test_latency_tracker.py, test_cache_store.py,
test_budget_guard_real.py) - these fakes exist only to let pipeline-composition tests focus on
pipeline behavior, not infrastructure correctness.
"""
from decimal import Decimal

from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.routing.latency_tracker import RoutingTelemetrySnapshot


class PermissiveProviderHealthStore:
    """Every (provider_id, model_id) pair is always healthy - marks are recorded but never
    consulted, so tests can inspect what FallbackPolicy tried to mark without it affecting
    subsequent routing decisions within the same test."""

    def __init__(self) -> None:
        self.unhealthy_marks: list[tuple[str, str]] = []
        self.runtime_unavailable_marks: list[tuple[str, str]] = []

    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        self.unhealthy_marks.append((provider_id, model_id))

    async def mark_runtime_unavailable(self, provider_id: str, model_id: str) -> None:
        self.runtime_unavailable_marks.append((provider_id, model_id))

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        return True


class EmptyLatencyTracker:
    """Always returns an empty RoutingTelemetrySnapshot - FASTEST-objective callers fall back
    to the static quality_tier heuristic (§4.6)."""

    async def record(self, provider_id: str, model_id: str, latency_ms: float) -> None:
        return None

    async def snapshot(self) -> RoutingTelemetrySnapshot:
        return RoutingTelemetrySnapshot()


class AllowingBudgetGuard:
    """Always approves - never raises BudgetExceededError."""

    def __init__(self) -> None:
        self.check_calls: list[Decimal] = []

    async def check(self, capability_name: str, priority: TaskPriority, worst_case: Decimal) -> None:
        self.check_calls.append(worst_case)


class InMemoryCacheStore:
    """A plain dict-backed CacheStore - every key starts as a miss."""

    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)
