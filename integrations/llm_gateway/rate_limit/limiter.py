"""RateLimiter (docs/phase7_architecture_contract.md §14): Redis-backed token-bucket rate
limiting, atomic all-or-nothing composite-key acquisition.

Atomicity across multiple buckets (provider-wide + model-specific + capability-specific,
§14 rule 1) is achieved with a single Lua script (EVAL) - Redis executes a script as one
atomic operation, so a partial throttle (some buckets decremented, others not) cannot occur
even under concurrent callers.
"""
import time
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from redis.asyncio import Redis

from core.config import Settings
from integrations.llm_gateway.errors import MissingRedisFailurePolicyError, RateLimitExceededError


class RateLimitKey(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    provider_id: str
    model_id: str | None = None  # None = provider-wide limit
    capability_name: str | None = None
    tenant_id: str | None = None  # forward-compatible only - not populated or enforced in Phase 7


class RateLimiter(Protocol):
    async def acquire(self, keys: list[RateLimitKey]) -> None:
        """Every key must have capacity, or none are consumed (atomic, all-or-nothing -
        never a partial throttle). Raises RateLimitExceededError naming which key(s) were
        exhausted."""
        ...


# KEYS = one Redis hash per bucket (fields: tokens, last_refill_ms)
# ARGV = [capacity, refill_rate_per_second, now_ms, cost]
# Returns {1, ""} if every bucket had >= cost tokens and all were atomically consumed;
# {0, "<comma-separated 0-based exhausted-bucket indices>"} otherwise - nothing is consumed.
_ACQUIRE_SCRIPT = """
local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local now_ms = tonumber(ARGV[3])
local cost = tonumber(ARGV[4])

local computed_tokens = {}
local exhausted_indices = {}

for i, key in ipairs(KEYS) do
    local bucket = redis.call("HMGET", key, "tokens", "last_refill_ms")
    local tokens = tonumber(bucket[1])
    local last_refill_ms = tonumber(bucket[2])
    if tokens == nil then
        tokens = capacity
        last_refill_ms = now_ms
    end
    local elapsed_seconds = math.max(0, (now_ms - last_refill_ms) / 1000)
    tokens = math.min(capacity, tokens + elapsed_seconds * refill_rate)
    computed_tokens[i] = tokens
    if tokens < cost then
        table.insert(exhausted_indices, tostring(i - 1))
    end
end

if #exhausted_indices > 0 then
    return {0, table.concat(exhausted_indices, ",")}
end

for i, key in ipairs(KEYS) do
    local new_tokens = computed_tokens[i] - cost
    redis.call("HSET", key, "tokens", tostring(new_tokens), "last_refill_ms", tostring(now_ms))
    redis.call("EXPIRE", key, 3600)
end

return {1, ""}
"""


def _redis_key(key: RateLimitKey) -> str:
    return ":".join(
        [
            "phase7",
            "ratelimit",
            key.provider_id,
            key.model_id or "-",
            key.capability_name or "-",
            key.tenant_id or "-",
        ]
    )


class RedisRateLimiter:
    """Token-bucket RateLimiter, Redis-backed for cross-process consistency (§14 rule 2,
    P19). Requires `settings.redis_unavailable_policy` to already be set at construction -
    raises MissingRedisFailurePolicyError otherwise, per §28 Q1's binding provisional rule
    that this is the one parameter that must never be silently defaulted.
    """

    def __init__(
        self,
        redis_client: Redis,
        settings: Settings,
        *,
        capacity: int = 60,
        refill_rate_per_second: float = 1.0,
    ) -> None:
        if settings.redis_unavailable_policy is None:
            raise MissingRedisFailurePolicyError(
                "RateLimiter requires settings.redis_unavailable_policy to be explicitly set "
                "('fail_open' or 'fail_closed') before construction (§28 Q1)."
            )
        self._redis = redis_client
        self._failure_policy: Literal["fail_open", "fail_closed"] = settings.redis_unavailable_policy
        self._capacity = capacity
        self._refill_rate_per_second = refill_rate_per_second
        self._script = redis_client.register_script(_ACQUIRE_SCRIPT)

    async def acquire(self, keys: list[RateLimitKey]) -> None:
        """Every key must have capacity, or none are consumed (atomic, all-or-nothing -
        never a partial throttle). Raises RateLimitExceededError naming which key(s) were
        exhausted."""
        if not keys:
            return
        redis_keys = [_redis_key(key) for key in keys]
        now_ms = time.time() * 1000

        try:
            acquired, exhausted_indices_raw = await self._script(
                keys=redis_keys, args=[self._capacity, self._refill_rate_per_second, now_ms, 1]
            )
        except Exception as exc:
            if self._failure_policy == "fail_open":
                return
            raise RateLimitExceededError(
                "RateLimiter backend unavailable and redis_unavailable_policy=fail_closed"
            ) from exc

        if int(acquired) == 1:
            return

        exhausted_indices = [int(i) for i in exhausted_indices_raw.split(",") if i]
        exhausted_keys = [keys[i] for i in exhausted_indices]
        raise RateLimitExceededError(
            "Rate limit exceeded for: "
            + ", ".join(_redis_key(key) for key in exhausted_keys)
        )
