"""Tests for services.budget_guard.RedisBudgetGuard (docs/phase7_architecture_contract.md
§15.2, Amendment C §25). Integration tests against real local Redis - every test injects a
fresh uuid-based `ledger_namespace`, and the ledger key is deleted in each test's own
teardown."""
import uuid
from decimal import Decimal
from typing import Literal

import pytest
from redis.asyncio import Redis

from capabilities.errors import BudgetExceededError
from core.config import Settings
from database.models.editorial_task import TaskPriority
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError
from services.budget_guard import RedisBudgetGuard
from services.cost_tracker import global_ledger_key


def _settings(
    max_daily_ai_cost: float | None,
    redis_unavailable_policy: Literal["fail_open", "fail_closed"] | None = "fail_closed",
) -> Settings:
    return Settings(  # type: ignore[call-arg]
        _env_file=None,
        max_daily_ai_cost=max_daily_ai_cost,
        redis_unavailable_policy=redis_unavailable_policy,
    )


def _unique_namespace() -> str:
    return f"test-{uuid.uuid4()}"


def test_missing_redis_unavailable_policy_raises_at_construction(redis_client: Redis) -> None:
    settings = _settings(max_daily_ai_cost=10.0, redis_unavailable_policy=None)

    with pytest.raises(MissingRedisFailurePolicyError):
        RedisBudgetGuard(redis_client, settings)


@pytest.mark.asyncio
async def test_check_allows_when_no_ceiling_is_configured(redis_client: Redis) -> None:
    guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=None))

    await guard.check("research", TaskPriority.B, Decimal("999999"))  # must not raise


@pytest.mark.asyncio
async def test_check_allows_when_under_the_ceiling_with_empty_ledger(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=10.0), ledger_namespace=namespace)

    await guard.check("research", TaskPriority.B, Decimal("5.0"))  # must not raise


@pytest.mark.asyncio
async def test_check_denies_when_worst_case_alone_exceeds_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=10.0), ledger_namespace=namespace)

    with pytest.raises(BudgetExceededError):
        await guard.check("research", TaskPriority.B, Decimal("15.0"))


@pytest.mark.asyncio
async def test_check_denies_when_existing_spend_plus_worst_case_exceeds_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    try:
        await redis_client.incrbyfloat(global_ledger_key(namespace), 8.0)
        guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=10.0), ledger_namespace=namespace)

        with pytest.raises(BudgetExceededError):
            await guard.check("research", TaskPriority.B, Decimal("5.0"))  # 8 + 5 > 10
    finally:
        await redis_client.delete(global_ledger_key(namespace))


@pytest.mark.asyncio
async def test_check_allows_when_existing_spend_plus_worst_case_is_exactly_at_the_ceiling(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    try:
        await redis_client.incrbyfloat(global_ledger_key(namespace), 5.0)
        guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=10.0), ledger_namespace=namespace)

        await guard.check("research", TaskPriority.B, Decimal("5.0"))  # 5 + 5 == 10, not > 10
    finally:
        await redis_client.delete(global_ledger_key(namespace))


@pytest.mark.asyncio
async def test_denial_message_names_capability_and_priority(redis_client: Redis) -> None:
    namespace = _unique_namespace()
    guard = RedisBudgetGuard(redis_client, _settings(max_daily_ai_cost=1.0), ledger_namespace=namespace)

    with pytest.raises(BudgetExceededError, match="research"):
        await guard.check("research", TaskPriority.S, Decimal("5.0"))


@pytest.mark.asyncio
async def test_fail_open_policy_allows_the_call_when_the_ledger_read_raises() -> None:
    guard = RedisBudgetGuard(_RaisingRedis(), _settings(max_daily_ai_cost=10.0, redis_unavailable_policy="fail_open"))  # type: ignore[arg-type]

    await guard.check("research", TaskPriority.B, Decimal("1.0"))  # must not raise


@pytest.mark.asyncio
async def test_fail_closed_policy_denies_when_the_ledger_read_raises() -> None:
    guard = RedisBudgetGuard(_RaisingRedis(), _settings(max_daily_ai_cost=10.0, redis_unavailable_policy="fail_closed"))  # type: ignore[arg-type]

    with pytest.raises(BudgetExceededError):
        await guard.check("research", TaskPriority.B, Decimal("1.0"))


class _RaisingRedis:
    async def get(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")
