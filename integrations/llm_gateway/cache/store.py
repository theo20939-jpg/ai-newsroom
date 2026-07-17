"""CacheStore (docs/phase7_architecture_contract.md §13.8): Redis-backed, byte-oriented
key/value store with TTL support.

`core.redis.get_redis_client()` is built with `decode_responses=True` (str in/out), while
CacheStore's own frozen Protocol is byte-oriented (`get`/`set` exchange `bytes`, never `str`).
This module base64-encodes at that boundary so CacheStore's contract is honored exactly,
without needing a second, non-decoding Redis client alongside the one `core/redis.py` already
provides and the rest of the app already depends on.
"""
import base64
from typing import Protocol

from redis.asyncio import Redis


class CacheStore(Protocol):
    async def get(self, key: str) -> bytes | None:
        """Returns the raw cached payload, or None. A miss - key never written, or expired
        since written - is a normal, first-class outcome, never an error; the two cases are
        indistinguishable and MUST remain so."""
        ...

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        """Writes value under key. ttl_seconds=None means no expiry; every other caller MUST
        pass an explicit TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Removes key if present; deleting an absent key is a no-op, never an error."""
        ...


class RedisCacheStore:
    """The only implementation of CacheStore in this delivery."""

    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    async def get(self, key: str) -> bytes | None:
        encoded = await self._redis.get(key)
        if encoded is None:
            return None
        return base64.b64decode(encoded)

    async def set(self, key: str, value: bytes, ttl_seconds: int | None) -> None:
        encoded = base64.b64encode(value).decode("ascii")
        if ttl_seconds is None:
            await self._redis.set(key, encoded)
        else:
            await self._redis.set(key, encoded, ex=ttl_seconds)

    async def delete(self, key: str) -> None:
        await self._redis.delete(key)
