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
async def test_bounded_runtime_unavailable_creates_expiry_field_and_is_unhealthy(redis_client: Redis) -> None:
    """Phase 15 runtime reliability fix, scenario 1: a bounded (ttl_seconds given) mark creates
    a real expiry field on the Redis hash - "TTL is present where intended" in this codebase's
    own established explicit-timestamp-at-read-time design (see this module's own docstring for
    why native Redis EXPIRE is deliberately not used)."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id, ttl_seconds=60)

        assert await store.is_healthy(provider_id, model_id) is False
        raw = await redis_client.hgetall(store._redis_key(provider_id, model_id))  # noqa: SLF001
        assert raw.get("runtime_unavailable") == "1"
        assert "runtime_unavailable_until_ms" in raw
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_bounded_runtime_unavailable_expires_automatically_after_its_ttl(redis_client: Redis) -> None:
    """Phase 15 runtime reliability fix, scenario 2: unlike the permanent (no-TTL) case, a
    bounded mark self-clears - the fix's central guarantee that a latch cannot survive forever
    without a manual Redis diagnosis-and-clear."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id, ttl_seconds=1)
        assert await store.is_healthy(provider_id, model_id) is False

        await asyncio.sleep(1.2)

        assert await store.is_healthy(provider_id, model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_mark_healthy_clears_bounded_runtime_unavailable_before_its_ttl_elapses(redis_client: Redis) -> None:
    """Phase 15 runtime reliability fix, scenario 3: a real successful call (mark_healthy)
    clears the state immediately, rather than waiting out the full cooldown."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id, ttl_seconds=3600)
        assert await store.is_healthy(provider_id, model_id) is False

        await store.mark_healthy(provider_id, model_id)

        assert await store.is_healthy(provider_id, model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_mark_healthy_also_clears_a_permanent_no_ttl_runtime_unavailable_mark(redis_client: Redis) -> None:
    """A real successful call is unambiguous proof of health regardless of why the candidate was
    previously marked unavailable - even a permanent (no-TTL) mark is cleared by it."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id)  # no TTL - permanent
        assert await store.is_healthy(provider_id, model_id) is False

        await store.mark_healthy(provider_id, model_id)

        assert await store.is_healthy(provider_id, model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_mark_healthy_also_clears_a_transient_unhealthy_mark(redis_client: Redis) -> None:
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_unhealthy(provider_id, model_id, ttl_seconds=60)
        assert await store.is_healthy(provider_id, model_id) is False

        await store.mark_healthy(provider_id, model_id)

        assert await store.is_healthy(provider_id, model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_permanent_runtime_unavailable_still_has_no_ttl_field_at_all(redis_client: Redis) -> None:
    """Scenario 4 (permanent invalid configuration remains unavailable): the default,
    unbounded call path writes no expiry field whatsoever - not merely a very long one -
    exactly the pre-existing behavior, unchanged."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        await store.mark_runtime_unavailable(provider_id, model_id)

        raw = await redis_client.hgetall(store._redis_key(provider_id, model_id))  # noqa: SLF001
        assert raw.get("runtime_unavailable") == "1"
        assert "runtime_unavailable_until_ms" not in raw
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_bounded_mark_touches_only_its_own_key(redis_client: Redis) -> None:
    """Scenario 8 (no unrelated Redis keys are changed): marking one (provider_id, model_id)
    pair must never write or affect any other key."""
    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    other_provider_id, other_model_id = _unique_pair()
    try:
        before = set(await redis_client.keys("phase7:health:*"))
        await store.mark_runtime_unavailable(provider_id, model_id, ttl_seconds=60)
        after = set(await redis_client.keys("phase7:health:*"))

        assert after - before == {store._redis_key(provider_id, model_id)}  # noqa: SLF001
        assert await store.is_healthy(other_provider_id, other_model_id) is True
    finally:
        await redis_client.delete(store._redis_key(provider_id, model_id))  # noqa: SLF001


@pytest.mark.asyncio
async def test_mark_runtime_unavailable_log_contains_no_secret_pattern(
    redis_client: Redis, caplog: pytest.LogCaptureFixture
) -> None:
    """Scenario 9 (no secret values appear in logs): the state-transition log line only ever
    carries provider_id/model_id/ttl_seconds - never an API key or bearer token."""
    import logging

    store = RedisProviderHealthStore(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        with caplog.at_level(logging.INFO, logger="integrations.llm_gateway.fallback.health_store"):
            await store.mark_runtime_unavailable(provider_id, model_id, ttl_seconds=60)

        import re

        combined = "\n".join(record.getMessage() + str(getattr(record, "__dict__", "")) for record in caplog.records)
        # An API-key-shaped pattern, not a bare "sk-" substring - "Task-80" (asyncio's own task
        # name) legitimately contains "sk-" as a coincidental substring and must not fail this.
        assert re.search(r"sk-[A-Za-z0-9_-]{8,}", combined) is None
        assert "Bearer " not in combined
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


@pytest.mark.asyncio
async def test_mark_runtime_unavailable_with_ttl_swallows_backend_errors() -> None:
    store = RedisProviderHealthStore(_RaisingRedis())  # type: ignore[arg-type]

    await store.mark_runtime_unavailable("fake-provider", "fake-model", ttl_seconds=60)  # must not raise


@pytest.mark.asyncio
async def test_mark_healthy_swallows_backend_errors() -> None:
    store = RedisProviderHealthStore(_RaisingRedis())  # type: ignore[arg-type]

    await store.mark_healthy("fake-provider", "fake-model")  # must not raise


class _RaisingRedis:
    async def hset(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def hmget(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def hdel(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")
