"""Tests for integrations.llm_gateway.routing.latency_tracker.RedisLatencyTracker
(docs/phase7_architecture_contract.md §4.6). Integration tests against real local Redis -
every (provider_id, model_id) pair is uuid-namespaced per test, and the index/sample keys are
deleted in each test's own teardown."""
import statistics
import uuid

import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.routing.latency_tracker import (
    _INDEX_KEY,
    _index_member,
    _sample_key,
    RedisLatencyTracker,
)


def _unique_pair() -> tuple[str, str]:
    suffix = uuid.uuid4()
    return f"test-provider-{suffix}", f"test-model-{suffix}"


async def _cleanup(redis_client: Redis, provider_id: str, model_id: str) -> None:
    await redis_client.delete(_sample_key(provider_id, model_id))
    await redis_client.srem(_INDEX_KEY, _index_member(provider_id, model_id))


@pytest.mark.asyncio
async def test_snapshot_is_empty_when_nothing_has_been_recorded_for_a_fresh_pair(redis_client: Redis) -> None:
    tracker = RedisLatencyTracker(redis_client)
    _provider_id, model_id = _unique_pair()

    snapshot = await tracker.snapshot()

    assert model_id not in snapshot.p50_latency_ms_by_model


@pytest.mark.asyncio
async def test_record_then_snapshot_reports_the_median(redis_client: Redis) -> None:
    tracker = RedisLatencyTracker(redis_client)
    provider_id, model_id = _unique_pair()
    try:
        for latency in (100.0, 200.0, 300.0):
            await tracker.record(provider_id, model_id, latency)

        snapshot = await tracker.snapshot()

        assert snapshot.p50_latency_ms_by_model[model_id] == statistics.median([100.0, 200.0, 300.0])
    finally:
        await _cleanup(redis_client, provider_id, model_id)


@pytest.mark.asyncio
async def test_rolling_window_caps_the_number_of_samples_kept(redis_client: Redis) -> None:
    tracker = RedisLatencyTracker(redis_client, rolling_window_size=3)
    provider_id, model_id = _unique_pair()
    try:
        # Record 5 samples with a window of 3 - only the most recent 3 should survive.
        for latency in (10.0, 20.0, 30.0, 40.0, 50.0):
            await tracker.record(provider_id, model_id, latency)

        raw_samples = await redis_client.lrange(_sample_key(provider_id, model_id), 0, -1)

        assert len(raw_samples) == 3
        assert {float(s) for s in raw_samples} == {30.0, 40.0, 50.0}
    finally:
        await _cleanup(redis_client, provider_id, model_id)


@pytest.mark.asyncio
async def test_two_distinct_model_pairs_do_not_interfere(redis_client: Redis) -> None:
    tracker = RedisLatencyTracker(redis_client)
    provider_a, model_a = _unique_pair()
    provider_b, model_b = _unique_pair()
    try:
        await tracker.record(provider_a, model_a, 100.0)
        await tracker.record(provider_b, model_b, 500.0)

        snapshot = await tracker.snapshot()

        assert snapshot.p50_latency_ms_by_model[model_a] == 100.0
        assert snapshot.p50_latency_ms_by_model[model_b] == 500.0
    finally:
        await _cleanup(redis_client, provider_a, model_a)
        await _cleanup(redis_client, provider_b, model_b)


@pytest.mark.asyncio
async def test_snapshot_fails_open_on_backend_error() -> None:
    tracker = RedisLatencyTracker(_RaisingRedis())  # type: ignore[arg-type]

    snapshot = await tracker.snapshot()

    assert snapshot.p50_latency_ms_by_model == {}


@pytest.mark.asyncio
async def test_record_swallows_backend_errors() -> None:
    tracker = RedisLatencyTracker(_RaisingRedis())  # type: ignore[arg-type]

    await tracker.record("fake-provider", "fake-model", 100.0)  # must not raise


class _RaisingRedis:
    async def lpush(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def ltrim(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def sadd(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")

    async def smembers(self, *args: object, **kwargs: object) -> None:
        raise ConnectionError("simulated Redis outage")
