"""Tests for services.budget_guard.RedisBudgetGuard (docs/phase7_architecture_contract.md
§15.2, Amendment C §25; docs/api_cost_optimization_report.md §10's off/shadow/enforce mode).
Integration tests against real local Redis - every test injects a fresh uuid-based
`ledger_namespace`, and the ledger key is deleted in each test's own teardown."""
import asyncio
import uuid
from decimal import Decimal
from typing import Literal

import pytest
from redis.asyncio import Redis

from capabilities.errors import BudgetExceededError
from core.config import Settings
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError
from services.budget_guard import RedisBudgetGuard, image_attempt_key, image_execution_key
from services.cost_tracker import capability_ledger_key, global_ledger_key


def _settings(
    llm_budget_mode: Literal["off", "shadow", "enforce"] = "enforce",
    llm_daily_budget_usd: float = 10.0,
    llm_daily_warning_usd: float = 5.0,
    redis_unavailable_policy: Literal["fail_open", "fail_closed"] | None = "fail_closed",
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        llm_budget_mode=llm_budget_mode,
        llm_daily_budget_usd=llm_daily_budget_usd,
        llm_daily_warning_usd=llm_daily_warning_usd,
        redis_unavailable_policy=redis_unavailable_policy,
    )


def _unique_namespace() -> str:
    return f"test-{uuid.uuid4()}"


def test_missing_redis_unavailable_policy_raises_at_construction(redis_client: Redis) -> None:
    settings = _settings(redis_unavailable_policy=None)

    with pytest.raises(MissingRedisFailurePolicyError):
        RedisBudgetGuard(redis_client, settings)


@pytest.mark.asyncio
async def test_check_allows_when_mode_is_off_regardless_of_ceiling(redis_client: Redis) -> None:
    guard = RedisBudgetGuard(redis_client, _settings(llm_budget_mode="off", llm_daily_budget_usd=1.0))

    await guard.check("research", TaskPriority.B, Decimal("999999"))  # must not raise


@pytest.mark.asyncio
async def test_check_allows_when_under_the_ceiling_with_empty_ledger(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(redis_client, _settings(llm_daily_budget_usd=10.0), ledger_namespace=namespace)

    await guard.check("research", TaskPriority.B, Decimal("5.0"))  # must not raise


@pytest.mark.asyncio
async def test_enforce_mode_denies_when_worst_case_alone_exceeds_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(
        redis_client, _settings(llm_budget_mode="enforce", llm_daily_budget_usd=10.0), ledger_namespace=namespace
    )

    with pytest.raises(BudgetExceededError):
        await guard.check("research", TaskPriority.B, Decimal("15.0"))


@pytest.mark.asyncio
async def test_enforce_mode_denies_when_existing_spend_plus_worst_case_exceeds_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    try:
        await redis_client.incrbyfloat(global_ledger_key(namespace), 8.0)
        guard = RedisBudgetGuard(
            redis_client, _settings(llm_budget_mode="enforce", llm_daily_budget_usd=10.0), ledger_namespace=namespace
        )

        with pytest.raises(BudgetExceededError):
            await guard.check("research", TaskPriority.B, Decimal("5.0"))  # 8 + 5 > 10
    finally:
        await redis_client.delete(global_ledger_key(namespace))


@pytest.mark.asyncio
async def test_check_allows_when_existing_spend_plus_worst_case_is_exactly_at_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    try:
        await redis_client.incrbyfloat(global_ledger_key(namespace), 5.0)
        guard = RedisBudgetGuard(
            redis_client, _settings(llm_budget_mode="enforce", llm_daily_budget_usd=10.0), ledger_namespace=namespace
        )

        await guard.check("research", TaskPriority.B, Decimal("5.0"))  # 5 + 5 == 10, not > 10
    finally:
        await redis_client.delete(global_ledger_key(namespace))


@pytest.mark.asyncio
async def test_denial_message_names_capability_and_priority(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(
        redis_client, _settings(llm_budget_mode="enforce", llm_daily_budget_usd=1.0), ledger_namespace=namespace
    )

    with pytest.raises(BudgetExceededError, match="research"):
        await guard.check("research", TaskPriority.S, Decimal("5.0"))


@pytest.mark.asyncio
async def test_shadow_mode_never_raises_even_when_budget_would_be_exceeded(redis_client: Redis) -> None:
    """docs/api_cost_optimization_report.md §10: shadow computes the same projected decision
    enforce would, but never blocks - the safe default until real spend data validates it."""
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(
        redis_client, _settings(llm_budget_mode="shadow", llm_daily_budget_usd=1.0), ledger_namespace=namespace
    )

    await guard.check("research", TaskPriority.B, Decimal("999999"))  # must not raise


@pytest.mark.asyncio
async def test_shadow_mode_logs_the_projected_denial(redis_client: Redis, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    namespace = _unique_namespace()
    guard = RedisBudgetGuard(
        redis_client, _settings(llm_budget_mode="shadow", llm_daily_budget_usd=1.0), ledger_namespace=namespace
    )

    with caplog.at_level(logging.INFO, logger="services.budget_guard"):
        await guard.check("research", TaskPriority.B, Decimal("999999"))

    assert any(r.message == "llm_daily_budget_would_be_exceeded_shadow_mode" for r in caplog.records)


@pytest.mark.asyncio
async def test_warning_threshold_logs_once_spend_crosses_it(redis_client: Redis, caplog: pytest.LogCaptureFixture) -> None:
    import logging

    namespace = _unique_namespace()
    try:
        await redis_client.incrbyfloat(global_ledger_key(namespace), 0.60)
        guard = RedisBudgetGuard(
            redis_client,
            _settings(llm_budget_mode="shadow", llm_daily_budget_usd=1.0, llm_daily_warning_usd=0.50),
            ledger_namespace=namespace,
        )

        with caplog.at_level(logging.WARNING, logger="services.budget_guard"):
            await guard.check("research", TaskPriority.B, Decimal("0.01"))

        assert any(r.message == "llm_daily_spend_warning_threshold_crossed" for r in caplog.records)
    finally:
        await redis_client.delete(global_ledger_key(namespace))


@pytest.mark.asyncio
async def test_fail_open_policy_allows_the_call_when_the_ledger_read_raises() -> None:
    guard = RedisBudgetGuard(
        _RaisingRedis(), _settings(llm_budget_mode="enforce", redis_unavailable_policy="fail_open")  # type: ignore[arg-type]
    )

    await guard.check("research", TaskPriority.B, Decimal("1.0"))  # must not raise


@pytest.mark.asyncio
async def test_fail_closed_policy_denies_when_the_ledger_read_raises_in_enforce_mode() -> None:
    guard = RedisBudgetGuard(
        _RaisingRedis(), _settings(llm_budget_mode="enforce", redis_unavailable_policy="fail_closed")  # type: ignore[arg-type]
    )

    with pytest.raises(BudgetExceededError):
        await guard.check("research", TaskPriority.B, Decimal("1.0"))


@pytest.mark.asyncio
async def test_fail_closed_policy_in_shadow_mode_never_raises_on_ledger_read_failure() -> None:
    """Shadow mode's own "never blocks" guarantee applies even to a ledger-read failure - only
    enforce mode's fail_closed policy actually denies."""
    guard = RedisBudgetGuard(
        _RaisingRedis(), _settings(llm_budget_mode="shadow", redis_unavailable_policy="fail_closed")  # type: ignore[arg-type]
    )

    await guard.check("research", TaskPriority.B, Decimal("1.0"))  # must not raise


class _RaisingRedis:
    async def get(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")


async def _cleanup_image_reservation(redis_client: Redis, namespace: str, capability: str, *ids: str) -> None:
    keys = [global_ledger_key(namespace), capability_ledger_key(namespace, capability)]
    keys.extend(image_execution_key(namespace, value) for value in ids)
    keys.extend(image_attempt_key(namespace, value) for value in ids)
    await redis_client.delete(*keys)


@pytest.mark.asyncio
async def test_image_reservation_is_idempotent_under_concurrency(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    capability = "image_generation:instagram"
    guard = RedisBudgetGuard(redis_client, _settings(llm_daily_budget_usd=1), ledger_namespace=namespace)
    kwargs = dict(
        capability_name=capability, priority=TaskPriority.B, worst_case=Decimal("0.093"),
        execution_id="package:v1", creative_id="package", max_attempts=1,
    )
    try:
        first, second = await asyncio.gather(
            guard.reserve_image_cost(**kwargs), guard.reserve_image_cost(**kwargs)
        )
        assert {first.status, second.status} == {"reserved", "duplicate"}
        assert Decimal(str(await redis_client.get(global_ledger_key(namespace)))) == Decimal("0.093")
    finally:
        await _cleanup_image_reservation(redis_client, namespace, capability, "package:v1", "package")


@pytest.mark.asyncio
async def test_image_reservation_atomically_prevents_concurrent_overspend(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    capability = "image_generation:instagram"
    guard = RedisBudgetGuard(redis_client, _settings(llm_daily_budget_usd=1), ledger_namespace=namespace)
    async def reserve(execution_id: str):
        return await guard.reserve_image_cost(
            capability_name=capability, priority=TaskPriority.B, worst_case=Decimal("0.60"),
            execution_id=execution_id, creative_id=execution_id, max_attempts=1,
        )
    try:
        first, second = await asyncio.gather(reserve("one"), reserve("two"))
        assert {first.status, second.status} == {"reserved", "budget_exceeded"}
        assert Decimal(str(await redis_client.get(global_ledger_key(namespace)))) == Decimal("0.6")
    finally:
        await _cleanup_image_reservation(redis_client, namespace, capability, "one", "two")


@pytest.mark.asyncio
async def test_successful_image_settlement_replaces_reservation_with_usage_estimate(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    capability = "image_generation:instagram"
    guard = RedisBudgetGuard(redis_client, _settings(llm_daily_budget_usd=1), ledger_namespace=namespace)
    try:
        reserved = await guard.reserve_image_cost(
            capability_name=capability, priority=TaskPriority.B, worst_case=Decimal("0.093"),
            execution_id="settle:v1", creative_id="settle", max_attempts=1,
        )
        assert reserved.status == "reserved"
        await guard.complete_image_reservation(
            execution_id="settle:v1", capability_name=capability, status="success",
            accounted_cost=Decimal("0.05325"), audit_fields={"provider": "openai"},
        )
        assert Decimal(str(await redis_client.get(global_ledger_key(namespace)))) == Decimal("0.05325")
        audit = await redis_client.hgetall(image_execution_key(namespace, "settle:v1"))
        assert audit["status"] == "success"
        assert Decimal(audit["accounted_cost_usd"]) == Decimal("0.05325")
    finally:
        await _cleanup_image_reservation(redis_client, namespace, capability, "settle:v1", "settle")
