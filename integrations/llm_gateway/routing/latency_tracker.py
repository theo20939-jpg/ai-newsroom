"""LatencyTracker (docs/phase7_architecture_contract.md §4.6, formalized during the Phase 7
contract audit pass): owns the rolling p50-latency-per-model sample the FASTEST objective
ranks by.

Storage design: a bounded Redis LIST of the most recent `rolling_window_size` raw latency
samples per (provider_id, model_id) - LPUSH + LTRIM - plus a Redis SET index of every
`"{provider_id}|{model_id}"` pair ever recorded, so `snapshot()` can enumerate exactly the
models with data without an O(keyspace) `KEYS`/`SCAN` over unrelated keys. `record()` takes
both provider_id and model_id (matching the audited Protocol exactly) even though the
snapshot's output field is `p50_latency_ms_by_model` (model_id-keyed only, per §4.2's
`RoutingTelemetrySnapshot`) - in the ordinary case one model_id belongs to exactly one
provider (ModelDescriptor.provider_id is a required FK), so this rarely matters; in the rare
case two providers coincidentally reuse the same model_id string, snapshot() merges their raw
samples before computing the median, rather than silently dropping one provider's data.
"""
import statistics
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field
from redis.asyncio import Redis

DEFAULT_ROLLING_WINDOW_SIZE = 20
_INDEX_KEY = "phase7:latency:index"


class RoutingTelemetrySnapshot(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    p50_latency_ms_by_model: dict[str, float] = Field(default_factory=dict)  # empty = no data yet


class LatencyTracker(Protocol):
    async def record(self, provider_id: str, model_id: str, latency_ms: float) -> None:
        """Called once per completed provider attempt (success or failure) - the sole write
        path. provider_id/model_id are opaque strings only (P19, §18) - never resolved
        against ProviderRegistry/ModelRegistry content."""
        ...

    async def snapshot(self) -> RoutingTelemetrySnapshot:
        """Returns the current rolling p50-latency-per-model sample. Missing data for a model,
        or backend unavailability, is simply omitted from the snapshot - never an error, never
        a blocking read (§4.6 binding rule)."""
        ...


def _index_member(provider_id: str, model_id: str) -> str:
    return f"{provider_id}|{model_id}"


def _sample_key(provider_id: str, model_id: str) -> str:
    return f"phase7:latency:samples:{provider_id}:{model_id}"


class RedisLatencyTracker:
    """The only implementation of LatencyTracker in this delivery. Redis-backed for
    cross-process consistency (P19)."""

    def __init__(self, redis_client: Redis, *, rolling_window_size: int = DEFAULT_ROLLING_WINDOW_SIZE) -> None:
        self._redis = redis_client
        self._rolling_window_size = rolling_window_size

    async def record(self, provider_id: str, model_id: str, latency_ms: float) -> None:
        key = _sample_key(provider_id, model_id)
        try:
            await self._redis.lpush(key, str(latency_ms))
            await self._redis.ltrim(key, 0, self._rolling_window_size - 1)
            await self._redis.sadd(_INDEX_KEY, _index_member(provider_id, model_id))
        except Exception:  # noqa: BLE001 - recording a sample must never block or fail a dispatch
            return

    async def snapshot(self) -> RoutingTelemetrySnapshot:
        try:
            members = await self._redis.smembers(_INDEX_KEY)
        except Exception:  # noqa: BLE001 - backend down -> fail open, empty snapshot (§4.6)
            return RoutingTelemetrySnapshot()

        samples_by_model: dict[str, list[float]] = {}
        for member in members:
            provider_id, _, model_id = str(member).partition("|")
            try:
                raw_samples = await self._redis.lrange(_sample_key(provider_id, model_id), 0, -1)
            except Exception:  # noqa: BLE001 - this one model's data omitted, never an error
                continue
            if not raw_samples:
                continue
            samples_by_model.setdefault(model_id, []).extend(float(s) for s in raw_samples)

        p50_by_model = {
            model_id: statistics.median(samples) for model_id, samples in samples_by_model.items()
        }
        return RoutingTelemetrySnapshot(p50_latency_ms_by_model=p50_by_model)
