"""CostTracker (docs/phase6_architecture_contract.md §9; docs/phase7_architecture_contract.md
§15.3-§15.4, §18's CostTracker row).

Post-hoc, WRITE-ONLY: given a completed CapabilityCall, computes Decimal cost and writes a
spend ledger. Never performs pre-flight checks (that is BudgetGuard's exclusive job), never
calls a provider.

Phase 7 §15.3 supersedes Phase 6 §9's "computes cost from its own model-price table" wording:
CostTracker MUST read pricing from PricingCatalog, never maintain an independent price table -
implemented below via ModelRegistryPricingCatalog, the same source CostEstimator uses.

Per §18's CostTracker row, writing a real `AIExecution` database row remains "still deferred"
(Amendment B) - this implementation writes ONLY the Redis-backed spend ledger BudgetGuard
reads, never a database row, never a migration.
"""
from datetime import datetime, timezone
from decimal import Decimal
from typing import Protocol
from uuid import UUID

from redis.asyncio import Redis

from schemas.capability import CapabilityCall
from services.pricing_catalog import PricingCatalog


class CostTracker(Protocol):
    """Records actual usage/cost for one completed CapabilityCall."""

    async def record(self, task_id: UUID, capability_name: str, call: CapabilityCall) -> None:
        """Compute cost from call.usage + call.model_used and write the spend ledger. MUST
        NOT perform pre-flight checks. MUST NOT call a provider. Per Amendment B (still in
        effect): does not persist an AIExecution database row in this delivery."""
        ...


def _today_namespace() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def global_ledger_key(namespace: str) -> str:
    return f"phase7:cost_ledger:{namespace}"


def capability_ledger_key(namespace: str, capability_name: str) -> str:
    return f"phase7:cost_ledger:{namespace}:{capability_name}"


def compute_call_cost(call: CapabilityCall, pricing_catalog: PricingCatalog) -> Decimal:
    """API cost optimization: extracted from RedisCostTracker's own (formerly private)
    computation so both the Redis ledger and the durable AIExecution row (services/
    cost_recording.py) use exactly one cost formula - never two independently-drifting ones.

    Cached input tokens are billed at the standard input rate (no verified "cached_input"
    PricingTier exists in the current catalog - docs/api_cost_optimization_report.md §8) - a
    deliberate, disclosed overestimate (real cached pricing is typically cheaper), never an
    invented rate. `cached_input_tokens` is a subset of `input_tokens`, never added on top."""
    if call.model_used is None:
        return Decimal("0")
    tier = pricing_catalog.get_tier(call.model_used, condition="standard")
    input_tokens = call.usage.input_tokens or 0
    output_tokens = call.usage.output_tokens or 0
    million = Decimal(1_000_000)
    return (
        Decimal(input_tokens) / million * tier.input_price_per_million
        + Decimal(output_tokens) / million * tier.output_price_per_million
    )


class RedisCostTracker:
    """The only implementation of CostTracker in this delivery. Reads pricing exclusively via
    PricingCatalog (§15.3) - never an independent price table. Writes a Redis-backed daily
    spend ledger: a global total (the same ledger RedisBudgetGuard reads) and a per-capability
    breakdown (for future audit use, not currently read by anything).

    `ledger_namespace`: None (the production default) computes the real UTC calendar date at
    each call; tests inject a fixed, uuid-based namespace instead for isolation, so repeated
    test runs on the same real day never share ledger state.
    """

    def __init__(
        self,
        redis_client: Redis,
        pricing_catalog: PricingCatalog,
        *,
        ledger_namespace: str | None = None,
    ) -> None:
        self._redis = redis_client
        self._pricing_catalog = pricing_catalog
        self._ledger_namespace = ledger_namespace

    def _namespace(self) -> str:
        return self._ledger_namespace if self._ledger_namespace is not None else _today_namespace()

    async def record(self, task_id: UUID, capability_name: str, call: CapabilityCall) -> None:
        cost = compute_call_cost(call, self._pricing_catalog)
        namespace = self._namespace()
        try:
            await self._redis.incrbyfloat(global_ledger_key(namespace), float(cost))
            await self._redis.incrbyfloat(capability_ledger_key(namespace, capability_name), float(cost))
        except Exception:  # noqa: BLE001 - §18: write failure is a cost-audit data-loss risk, never call-blocking
            return
