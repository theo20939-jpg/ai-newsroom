"""ProviderHealthStore (docs/phase7_architecture_contract.md §18's row, §4.3 step 4, §5.4):
runtime `(provider_id, model_id) -> {unhealthy_until, runtime_unavailable}` tracking.

The contract names this component and its data shape narratively (§18's table row, §4.3's
health-filter description, §5.4's write points) but gives no explicit Protocol code block the
way §7 (LLMGateway), §13.8 (CacheStore), or §14 (RateLimiter) do - the method names below are
this implementation's own, reasonable design filling that gap.

`verified_flags` (the third field §18's row names, written by CapabilityNegotiator) is
deliberately NOT implemented here: CapabilityNegotiator is deferred past this delivery (per
your scope reduction), so there is no producer or consumer for it yet - adding unexercised
storage for a feature with zero callers would be speculative, not "the smallest useful
production-oriented Gateway core." It can be added when CapabilityNegotiator itself lands.

TTL semantics use an explicit `unhealthy_until_ms` timestamp compared at read time, never
Redis's own key-level EXPIRE - the same hash key also carries `runtime_unavailable`, which per
§4.3 step 4 "MUST NOT expire within the life of the process." Expiring the whole key would
silently clear that too.
"""
import time
from typing import Protocol

from redis.asyncio import Redis


class ProviderHealthStore(Protocol):
    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        """TRANSIENT-classified failure (§5.2, §5.4): mark unhealthy with a TTL (default 60s,
        §4.3 step 4) that expires automatically."""
        ...

    async def mark_runtime_unavailable(self, provider_id: str, model_id: str) -> None:
        """PERMANENT_INCOMPATIBLE-classified failure (§5.2, §5.4): mark runtime_unavailable
        with no TTL - persists for the life of the process."""
        ...

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        """False if currently unhealthy (TTL not yet elapsed) or runtime_unavailable is set.
        Fails open (returns True) on backend unavailability - §18's binding failure
        behavior: "Backend down -> fail open (assume healthy)"."""
        ...


class RedisProviderHealthStore:
    """The only implementation of ProviderHealthStore in this delivery. Redis-backed for
    cross-process consistency (P19) - "the one genuinely 'hot' runtime state" (§18)."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    def _redis_key(self, provider_id: str, model_id: str) -> str:
        return f"phase7:health:{provider_id}:{model_id}"

    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        key = self._redis_key(provider_id, model_id)
        unhealthy_until_ms = (time.time() + ttl_seconds) * 1000
        try:
            await self._redis.hset(key, "unhealthy_until_ms", str(unhealthy_until_ms))
        except Exception:  # noqa: BLE001 - a failed write degrades health tracking, never blocks a call
            return

    async def mark_runtime_unavailable(self, provider_id: str, model_id: str) -> None:
        key = self._redis_key(provider_id, model_id)
        try:
            await self._redis.hset(key, "runtime_unavailable", "1")
        except Exception:  # noqa: BLE001 - a failed write degrades health tracking, never blocks a call
            return

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        key = self._redis_key(provider_id, model_id)
        try:
            unhealthy_until_raw, runtime_unavailable_raw = await self._redis.hmget(
                key, "unhealthy_until_ms", "runtime_unavailable"
            )
        except Exception:  # noqa: BLE001 - §18 binding failure behavior: fail open
            return True

        if runtime_unavailable_raw == "1":
            return False
        if unhealthy_until_raw is not None and time.time() * 1000 < float(unhealthy_until_raw):
            return False
        return True
