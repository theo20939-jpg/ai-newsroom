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

Phase 15 runtime reliability fix (docs/phase15_runtime_reliability_report.md): a recurring
production incident showed `runtime_unavailable` staying latched long after the underlying
account/region condition had cleared, with no automatic recovery mechanism - manual Redis key
deletion was the only remedy (docs/llm_runtime_availability_recovery_report.md). `mark_runtime_
unavailable()` now accepts an OPTIONAL `ttl_seconds` (default `None`, preserving the exact old
"no TTL, permanent until manual clear" behavior for genuinely permanent configuration failures -
backward compatible with every existing caller). A bounded caller (`FallbackPolicy`, for a
`ProviderRegionalUnavailableError`) passes a real TTL, stored in a second field,
`runtime_unavailable_until_ms`, using the same explicit-timestamp-at-read-time pattern as
`unhealthy_until_ms` above (never Redis's own key-level EXPIRE, for the same co-located-fields
reason). `mark_healthy()` is new: clears all three fields on a real, observed successful call -
the other half of automatic recovery, so a model does not have to wait out its full cooldown if
it turns out to already be working again.
"""
import logging
import time
from typing import Protocol

from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class ProviderHealthStore(Protocol):
    async def mark_unhealthy(self, provider_id: str, model_id: str, ttl_seconds: int = 60) -> None:
        """TRANSIENT-classified failure (§5.2, §5.4): mark unhealthy with a TTL (default 60s,
        §4.3 step 4) that expires automatically."""
        ...

    async def mark_runtime_unavailable(
        self, provider_id: str, model_id: str, ttl_seconds: int | None = None
    ) -> None:
        """PERMANENT_INCOMPATIBLE-classified failure (§5.2, §5.4): mark runtime_unavailable.
        `ttl_seconds=None` (default) persists for the life of the process, exactly as before -
        the correct behavior for a genuinely permanent configuration failure. A caller that
        knows the failure is bounded/recoverable (Phase 15 runtime reliability fix - a
        `ProviderRegionalUnavailableError`) passes a real `ttl_seconds`, after which `is_healthy()`
        automatically re-admits the candidate with no manual intervention."""
        ...

    async def mark_healthy(self, provider_id: str, model_id: str) -> None:
        """Phase 15 runtime reliability fix: clears any unhealthy/runtime_unavailable state for
        this candidate. Called after a real, observed successful dispatch - the other half of
        automatic recovery, letting a model recover immediately on proof-of-health rather than
        only once its cooldown TTL elapses."""
        ...

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        """False if currently unhealthy (TTL not yet elapsed) or runtime_unavailable is set (and,
        if it was set with a bounded TTL, that TTL has not yet elapsed either). Fails open
        (returns True) on backend unavailability - §18's binding failure behavior: "Backend down
        -> fail open (assume healthy)"."""
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

    async def mark_runtime_unavailable(
        self, provider_id: str, model_id: str, ttl_seconds: int | None = None
    ) -> None:
        key = self._redis_key(provider_id, model_id)
        try:
            if ttl_seconds is None:
                # Genuinely permanent: write only the flag, no expiry field at all - the exact
                # pre-existing behavior, untouched.
                await self._redis.hset(key, "runtime_unavailable", "1")
            else:
                runtime_unavailable_until_ms = (time.time() + ttl_seconds) * 1000
                await self._redis.hset(
                    key,
                    mapping={
                        "runtime_unavailable": "1",
                        "runtime_unavailable_until_ms": str(runtime_unavailable_until_ms),
                    },
                )
            logger.info(
                "provider_marked_runtime_unavailable",
                extra={"provider_id": provider_id, "model_id": model_id, "ttl_seconds": ttl_seconds},
            )
        except Exception:  # noqa: BLE001 - a failed write degrades health tracking, never blocks a call
            return

    async def mark_healthy(self, provider_id: str, model_id: str) -> None:
        key = self._redis_key(provider_id, model_id)
        try:
            await self._redis.hdel(
                key, "unhealthy_until_ms", "runtime_unavailable", "runtime_unavailable_until_ms"
            )
        except Exception:  # noqa: BLE001 - a failed write degrades health tracking, never blocks a call
            return

    async def is_healthy(self, provider_id: str, model_id: str) -> bool:
        key = self._redis_key(provider_id, model_id)
        try:
            unhealthy_until_raw, runtime_unavailable_raw, runtime_unavailable_until_raw = await self._redis.hmget(
                key, "unhealthy_until_ms", "runtime_unavailable", "runtime_unavailable_until_ms"
            )
        except Exception:  # noqa: BLE001 - §18 binding failure behavior: fail open
            return True

        if runtime_unavailable_raw == "1":
            if runtime_unavailable_until_raw is None:
                return False  # no bound - the genuinely-permanent case, unchanged
            if time.time() * 1000 < float(runtime_unavailable_until_raw):
                return False  # bounded, but the cooldown has not yet elapsed
            # else: bounded and expired - falls through, no longer treated as unavailable for
            # this reason (a stale latch self-clearing, the fix's whole point).
        if unhealthy_until_raw is not None and time.time() * 1000 < float(unhealthy_until_raw):
            return False
        return True
