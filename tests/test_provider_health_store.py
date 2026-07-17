"""Tests for integrations.llm_gateway.fallback.health_store.RedisProviderHealthStore
(docs/phase7_architecture_contract.md §18, §4.3 step 4, §5.4). Integration tests against real
local Redis - every (provider_id, model_id) pair is uuid-namespaced per test and the
underlying Redis hash key is deleted in each test's own teardown."""
import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.fallback.health_store import RedisProviderHealthStore


def _unique_pair() -> tuple[str, str]:
    suffix = uuid.uuid4()
    return f"test-provider-{suffix}", f"test-model-{suffix}"


@pytest.mark.asyncio
async def test_a_never_marked_pair_is_healthy(redis_client: Redis) -> None:
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()

    assert await store.is_healthy(provider_id, model_id) is True


@pytest.mark.asyncio
async def test_mark_unhealthy_makes_is_healthy_false(redis_client: Redis) -> None:
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_unhealthy(provider_id, model_id, ttl_seconds=60)

        assert await store.is_healthy(provider_id, model_id) is False
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_unhealthy_expires_automatically_after_its_ttl(redis_client: Redis) -> None:
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_unhealthy(provider_id, model_id, ttl_seconds=1)
        assert await store.is_healthy(provider_id, model_id) is False

        await asyncio.sleep(1.2)

        assert await store.is_healthy(provider_id, model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_mark_runtime_unavailable_makes_is_healthy_false(redis_client: Redis) -> None:
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id)

        assert await store.is_healthy(provider_id, model_id) is False
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_runtime_unavailable_does_not_expire(redis_client: Redis) -> None:
    """No TTL exists for runtime_unavailable at all - unlike the TTL test above, there is
    nothing to wait out. This asserts the mark survives being read multiple times."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id)

        assert await store.is_healthy(provider_id, model_id) is False
        await asyncio.sleep(0.1)
        assert await store.is_healthy(provider_id, model_id) is False
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_runtime_unavailable_persists_even_past_an_unhealthy_ttl_on_the_same_pair(
    redis_client: Redis,
) -> None:
    """Both fields live on the same Redis hash key - marking runtime_unavailable, then
    letting an unrelated unhealthy_until timestamp lapse, must not clear it."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_unhealthy(provider_id, model_id, ttl_seconds=1)
        await store.mark_runtime_unavailable(provider_id, model_id)

        await asyncio.sleep(1.2)  # the unhealthy_until timestamp has now lapsed

        assert await store.is_healthy(provider_id, model_id) is False  # still unhealthy
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_is_healthy_fails_open_on_backend_error() -> None:
    store = RedisProviderHealthStore(_RaisingRedis())  # type: ignore[arg-type]

    assert await store.is_healthy("fake-provider", "fake-model") is True


@pytest.mark.asyncio
async def test_mark_unhealthy_swallows_backend_errors() -> None:
    store = RedisProviderHealthStore(_RaisingRedis())  # type: ignore[arg-type]

    await store.mark_unhealthy("fake-provider", "fake-model")  # must not raise


@pytest.mark.asyncio
async def test_mark_runtime_unavailable_swallows_backend_errors() -> None:
    store = RedisProviderHealthStore(_RaisingRedis())  # type: ignore[arg-type]

    await store.mark_runtime_unavailable("fake-provider", "fake-model")  # must not raise


class _RaisingRedis:
    async def hset(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def hmget(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")
