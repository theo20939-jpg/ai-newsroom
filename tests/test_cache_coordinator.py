"""Tests for integrations.llm_gateway.cache.coordinator.CacheCoordinator
(docs/phase7_architecture_contract.md §13.1-§13.7). Unit tests against an in-memory fake
CacheStore, plus one integration test against the real Redis-backed store."""
import pytest
from redis.asyncio import Redis

from integrations.llm_gateway.cache.coordinator import CacheCoordinator
from integrations.llm_gateway.cache.store import RedisCacheStore
from integrations.llm_gateway.protocol import ContentPart, GenerateRequest, GenerateResponse, Message
from schemas.capability import CapabilityUsage


class _InMemoryCacheStore:
    def __init__(self) -> None:
        self.data: dict[str, bytes] = {}

    async def get(self, key: str) -> bytes | None:
        return self.data.get(key)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        self.data[key] = value

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class _RaisingCacheStore:
    async def get(self, key: str) -> bytes | None:
        raise RuntimeError("simulated Redis outage")

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        raise RuntimeError("simulated Redis outage")

    async def delete(self, key: str) -> None:
        raise RuntimeError("simulated Redis outage")


def _request(**metadata: object) -> GenerateRequest:
    return GenerateRequest(
        messages=[Message(role="user", content=[ContentPart(type="text", text="hello")])],
        metadata=metadata,
    )


def _response(finish_reason: str = "stop", artifacts: list | None = None) -> GenerateResponse:
    return GenerateResponse(
        text="a cacheable response",
        structured_output=None,
        finish_reason=finish_reason,  # type: ignore[arg-type]
        model_used="fake-model-a",
        usage=CapabilityUsage(input_tokens=10, output_tokens=5),
        artifacts=artifacts,
    )


@pytest.mark.asyncio
async def test_store_then_lookup_round_trips_a_cacheable_response() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()
    response = _response()

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is not None
    assert hit.text == response.text
    assert hit.model_used == response.model_used


@pytest.mark.asyncio
async def test_lookup_returns_none_on_a_genuine_miss() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())

    hit = await coordinator.lookup(_request(), "fake-provider", "fake-model-a")

    assert hit is None


@pytest.mark.asyncio
async def test_different_resolved_model_never_collides_with_the_same_request() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()
    response = _response()

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit_for_other_model = await coordinator.lookup(request, "fake-provider", "fake-model-b")

    assert hit_for_other_model is None


@pytest.mark.asyncio
async def test_different_resolved_provider_never_collides_with_the_same_request() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()
    response = _response()

    await coordinator.store(request, "fake-provider-a", "fake-model-a", response)
    hit_for_other_provider = await coordinator.lookup(request, "fake-provider-b", "fake-model-a")

    assert hit_for_other_provider is None


@pytest.mark.asyncio
async def test_store_is_a_no_op_when_finish_reason_is_not_stop() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()
    response = _response(finish_reason="length")

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is None


@pytest.mark.asyncio
async def test_store_is_a_no_op_when_artifacts_are_present() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()
    response = _response(artifacts=[{"uri": "s3://bucket/x", "mime_type": "image/png"}])

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is None


@pytest.mark.asyncio
async def test_store_is_a_no_op_when_cache_policy_is_not_read_write() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request(cache_policy="bypass")
    response = _response()

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is None


@pytest.mark.asyncio
async def test_store_defaults_to_cacheable_when_cache_policy_is_absent_from_metadata() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()  # no cache_policy key at all
    response = _response()

    await coordinator.store(request, "fake-provider", "fake-model-a", response)
    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is not None


@pytest.mark.asyncio
async def test_lookup_fails_open_when_cache_store_raises() -> None:
    coordinator = CacheCoordinator(_RaisingCacheStore())

    hit = await coordinator.lookup(_request(), "fake-provider", "fake-model-a")

    assert hit is None


@pytest.mark.asyncio
async def test_store_fails_open_and_swallows_when_cache_store_raises() -> None:
    coordinator = CacheCoordinator(_RaisingCacheStore())

    await coordinator.store(_request(), "fake-provider", "fake-model-a", _response())  # must not raise


@pytest.mark.asyncio
async def test_lookup_fails_open_on_a_corrupt_cached_payload() -> None:
    store = _InMemoryCacheStore()
    coordinator = CacheCoordinator(store)
    request = _request()
    key = coordinator._build_key_components(request, "fake-provider", "fake-model-a").cache_key()  # noqa: SLF001
    store.data[key] = b"not valid json at all {{{"

    hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

    assert hit is None


def test_cache_key_is_deterministic_for_identical_components() -> None:
    coordinator = CacheCoordinator(_InMemoryCacheStore())
    request = _request()

    key_1 = coordinator._build_key_components(request, "fake-provider", "fake-model-a").cache_key()  # noqa: SLF001
    key_2 = coordinator._build_key_components(request, "fake-provider", "fake-model-a").cache_key()  # noqa: SLF001

    assert key_1 == key_2


@pytest.mark.asyncio
async def test_integration_round_trip_against_real_redis(redis_client: Redis) -> None:
    coordinator = CacheCoordinator(RedisCacheStore(redis_client))
    request = _request()
    response = _response()
    key = coordinator._build_key_components(request, "fake-provider", "fake-model-a").cache_key()  # noqa: SLF001
    try:
        await coordinator.store(request, "fake-provider", "fake-model-a", response)

        hit = await coordinator.lookup(request, "fake-provider", "fake-model-a")

        assert hit is not None
        assert hit.text == response.text
    finally:
        await coordinator._cache_store.delete(key)  # noqa: SLF001 - isolated-key cleanup
