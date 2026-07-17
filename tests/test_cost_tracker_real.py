"""Tests for services.cost_tracker.RedisCostTracker (docs/phase7_architecture_contract.md
§15.3-§15.4). Integration tests against real local Redis - every test injects a fresh
uuid-based `ledger_namespace` instead of relying on the real calendar date, so runs never
share ledger state; the ledger keys are deleted in each test's own teardown."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.models.registry import ModelDescriptor, ModelRegistry, PricingTier
from schemas.capability import CapabilityCall, CapabilityUsage
from services.cost_tracker import RedisCostTracker, capability_ledger_key, global_ledger_key
from services.pricing_catalog import ModelRegistryPricingCatalog


def _registry() -> ModelRegistry:
    registry = ModelRegistry()
    registry.register(
        ModelDescriptor(
            model_id="fake-model-a",
            provider_id="fake-provider",
            display_name="Fake Model A",
            context_window_tokens=128_000,
            pricing_currency="USD",
            pricing_tiers=[
                PricingTier(
                    condition="standard",
                    input_price_per_million=Decimal("1.00"),
                    output_price_per_million=Decimal("2.00"),
                )
            ],
        )
    )
    registry.seal()
    return registry


def _call(model_used: str | None = "fake-model-a", input_tokens: int = 1000, output_tokens: int = 500) -> CapabilityCall:
    now = datetime.now(timezone.utc)
    return CapabilityCall(
        call_id=uuid.uuid4(),
        sequence=0,
        gateway_method="generate",
        status="SUCCESS",
        model_used=model_used,
        usage=CapabilityUsage(input_tokens=input_tokens, output_tokens=output_tokens),
        started_at=now,
        finished_at=now,
        duration_seconds=0.5,
    )


def _unique_namespace() -> str:
    return f"test-{uuid.uuid4()}"


async def _cleanup(redis_client: Redis, namespace: str, capability_name: str) -> None:
    await redis_client.delete(global_ledger_key(namespace))
    await redis_client.delete(capability_ledger_key(namespace, capability_name))


@pytest.mark.asyncio
async def test_record_increments_the_global_ledger_by_the_computed_cost(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    tracker = RedisCostTracker(
        redis_client, ModelRegistryPricingCatalog(_registry()), ledger_namespace=namespace
    )
    try:
        # 1000 input tokens * $1.00/1M + 500 output tokens * $2.00/1M = 0.001 + 0.001 = 0.002
        await tracker.record(uuid.uuid4(), "research", _call())

        raw = await redis_client.get(global_ledger_key(namespace))

        assert raw is not None
        assert Decimal(str(raw)) == Decimal("0.002")
    finally:
        await _cleanup(redis_client, namespace, "research")


@pytest.mark.asyncio
async def test_record_also_increments_the_per_capability_ledger(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    tracker = RedisCostTracker(
        redis_client, ModelRegistryPricingCatalog(_registry()), ledger_namespace=namespace
    )
    try:
        await tracker.record(uuid.uuid4(), "research", _call())

        raw = await redis_client.get(capability_ledger_key(namespace, "research"))

        assert raw is not None
        assert Decimal(str(raw)) == Decimal("0.002")
    finally:
        await _cleanup(redis_client, namespace, "research")


@pytest.mark.asyncio
async def test_record_accumulates_across_multiple_calls(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    tracker = RedisCostTracker(
        redis_client, ModelRegistryPricingCatalog(_registry()), ledger_namespace=namespace
    )
    try:
        await tracker.record(uuid.uuid4(), "research", _call())
        await tracker.record(uuid.uuid4(), "research", _call())

        raw = await redis_client.get(global_ledger_key(namespace))

        assert raw is not None
        assert Decimal(str(raw)) == Decimal("0.004")
    finally:
        await _cleanup(redis_client, namespace, "research")


@pytest.mark.asyncio
async def test_record_with_no_model_used_costs_zero_and_does_not_raise(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    tracker = RedisCostTracker(
        redis_client, ModelRegistryPricingCatalog(_registry()), ledger_namespace=namespace
    )
    try:
        await tracker.record(uuid.uuid4(), "research", _call(model_used=None))  # must not raise

        raw = await redis_client.get(global_ledger_key(namespace))

        assert raw is None or Decimal(str(raw)) == Decimal("0")
    finally:
        await _cleanup(redis_client, namespace, "research")


@pytest.mark.asyncio
async def test_record_swallows_backend_errors() -> None:
    tracker = RedisCostTracker(_RaisingRedis(), ModelRegistryPricingCatalog(_registry()))  # type: ignore[arg-type]

    await tracker.record(uuid.uuid4(), "research", _call())  # must not raise


class _RaisingRedis:
    async def incrbyfloat(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")
