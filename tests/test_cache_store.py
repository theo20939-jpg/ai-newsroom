"""Tests for integrations.llm_gateway.cache.store.RedisCacheStore
(docs/phase7_architecture_contract.md §13.8). Integration tests against the real local Redis
docker-compose already provisions - every key is uniquely namespaced (test:phase7:cache_store:
prefix + a fresh uuid per test) and deleted in each test's own teardown, per your "use
isolated keys and clean them up" instruction. No test depends on execution order.
"""
import asyncio
import uuid

import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.cache.store import RedisCacheStore


def _unique_key() -> str:
    return f"test:phase7:cache_store:{uuid.uuid4()}"


@pytest.mark.asyncio
async def test_get_returns_none_for_a_never_written_key(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()

    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_set_then_get_round_trips_bytes(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()
    try:
        await store.set(key, b"hello world", ttl_seconds=60)

        assert await store.get(key) == b"hello world"
    finally:
        await store.delete(key)


@pytest.mark.asyncio
async def test_set_round_trips_bytes_that_are_not_valid_utf8(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()
    raw = bytes(range(256))  # every possible byte value, including invalid UTF-8 sequences
    try:
        await store.set(key, raw, ttl_seconds=60)

        assert await store.get(key) == raw
    finally:
        await store.delete(key)


@pytest.mark.asyncio
async def test_set_with_no_ttl_persists_without_expiry(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()
    try:
        await store.set(key, b"no-expiry", ttl_seconds=None)

        assert await store.get(key) == b"no-expiry"
    finally:
        await store.delete(key)


@pytest.mark.asyncio
async def test_ttl_expiry_makes_a_key_indistinguishable_from_never_written(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()
    await store.set(key, b"short-lived", ttl_seconds=1)
    assert await store.get(key) == b"short-lived"

    await asyncio.sleep(1.5)

    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_delete_removes_a_present_key(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()
    await store.set(key, b"to-be-deleted", ttl_seconds=60)

    await store.delete(key)

    assert await store.get(key) is None


@pytest.mark.asyncio
async def test_delete_of_an_absent_key_is_a_no_op(redis_client: Redis) -> None:
    store = RedisCacheStore(redis_client)
    key = _unique_key()

    await store.delete(key)  # must not raise
