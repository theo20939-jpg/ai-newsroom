"""Tests for integrations.llm_gateway.rate_limit.limiter.RedisRateLimiter
(docs/phase7_architecture_contract.md §14). Integration tests against real local Redis -
every RateLimitKey uses a unique, uuid-namespaced provider_id per test, and the underlying
Redis hash keys are deleted in each test's own teardown."""
import asyncio
import uuid
from typing import Literal

import pytest
from redis.asyncio import Redis

from core.config import Settings
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError, RateLimitExceededError
from integrations.llm_gateway.rate_limit.limiter import RateLimitKey, RedisRateLimiter, _redis_key


def _settings(
    redis_unavailable_policy: Literal["fail_open", "fail_closed"] | None = "fail_closed",
) -> Settings:
    return Settings(_env_file=None, redis_unavailable_policy=redis_unavailable_policy)  # type: ignore[call-arg]


def _unique_provider_id() -> str:
    return f"test-provider-{uuid.uuid4()}"


async def _cleanup(redis_client: Redis, keys: list[RateLimitKey]) -> None:
    for key in keys:
        await redis_client.delete(_redis_key(key))


def test_missing_redis_unavailable_policy_raises_at_construction(redis_client: Redis) -> None:
    settings = _settings(redis_unavailable_policy=None)

    with pytest.raises(MissingRedisFailurePolicyError):
        RedisRateLimiter(redis_client, settings)


@pytest.mark.asyncio
async def test_acquire_succeeds_when_capacity_available(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, _settings(), capacity=5, refill_rate_per_second=0)
    keys = [RateLimitKey(provider_id=_unique_provider_id())]
    try:
        await limiter.acquire(keys)  # must not raise
    finally:
        await _cleanup(redis_client, keys)


@pytest.mark.asyncio
async def test_acquire_raises_once_capacity_is_exhausted(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, _settings(), capacity=2, refill_rate_per_second=0)
    keys = [RateLimitKey(provider_id=_unique_provider_id())]
    try:
        await limiter.acquire(keys)
        await limiter.acquire(keys)

        with pytest.raises(RateLimitExceededError):
            await limiter.acquire(keys)
    finally:
        await _cleanup(redis_client, keys)


@pytest.mark.asyncio
async def test_acquire_is_all_or_nothing_across_composite_keys(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, _settings(), capacity=1, refill_rate_per_second=0)
    provider_id = _unique_provider_id()
    exhausted_key = RateLimitKey(provider_id=provider_id, model_id="fake-model-a")
    healthy_key = RateLimitKey(provider_id=provider_id, capability_name="fake-capability")
    keys = [exhausted_key, healthy_key]
    try:
        # Exhaust only the model-specific bucket, leaving the capability bucket untouched.
        await limiter.acquire([exhausted_key])

        with pytest.raises(RateLimitExceededError):
            await limiter.acquire(keys)

        # The healthy bucket must still be untouched (capacity=1, never consumed) - if the
        # composite acquire() had partially consumed it, this second solo acquire would fail.
        await limiter.acquire([healthy_key])
    finally:
        await _cleanup(redis_client, keys)


@pytest.mark.asyncio
async def test_acquire_refills_over_time(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, _settings(), capacity=1, refill_rate_per_second=50)
    keys = [RateLimitKey(provider_id=_unique_provider_id())]
    try:
        await limiter.acquire(keys)

        with pytest.raises(RateLimitExceededError):
            await limiter.acquire(keys)

        await asyncio.sleep(0.2)  # 0.2s * 50 tokens/s = 10 tokens refilled, well past capacity=1

        await limiter.acquire(keys)  # must not raise - refilled
    finally:
        await _cleanup(redis_client, keys)


@pytest.mark.asyncio
async def test_acquire_with_empty_key_list_is_a_no_op(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(redis_client, _settings(), capacity=1, refill_rate_per_second=0)

    await limiter.acquire([])  # must not raise


@pytest.mark.asyncio
async def test_fail_open_policy_allows_the_call_when_the_script_raises(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(
        redis_client, _settings(redis_unavailable_policy="fail_open"), capacity=1, refill_rate_per_second=0
    )
    limiter._script = _RaisingScript()  # type: ignore[assignment]  # noqa: SLF001 - simulate a backend outage

    await limiter.acquire([RateLimitKey(provider_id=_unique_provider_id())])  # must not raise


@pytest.mark.asyncio
async def test_fail_closed_policy_raises_when_the_script_raises(redis_client: Redis) -> None:
    limiter = RedisRateLimiter(
        redis_client, _settings(redis_unavailable_policy="fail_closed"), capacity=1, refill_rate_per_second=0
    )
    limiter._script = _RaisingScript()  # type: ignore[assignment]  # noqa: SLF001 - simulate a backend outage

    with pytest.raises(RateLimitExceededError):
        await limiter.acquire([RateLimitKey(provider_id=_unique_provider_id())])


class _RaisingScript:
    async def __call__(self, keys: list[str], args: list[object]) -> None:
        raise ConnectionError("simulated Redis outage")


def test_tenant_id_is_never_populated_by_default() -> None:
    key = RateLimitKey(provider_id="fake-provider")

    assert key.tenant_id is None
