"""Durable, per-source Telegram ingestion checkpoints backed by existing Redis.

The checkpoint is an external monotonic message id, not process memory. Keys have no TTL so
ordinary source deactivation/reactivation and automation-worker recreation retain the boundary.
Redis errors and malformed values deliberately propagate: collection fails closed rather than
falling back to a historical fetch.
"""
from __future__ import annotations

import uuid
from typing import Protocol

from core.redis import get_redis_client

_KEY_PREFIX = "ninja:pulse:telegram:checkpoint:v1"
_ADVANCE_SCRIPT = """
local current = redis.call('GET', KEYS[1])
if not current then
  return -1
end
local current_number = tonumber(current)
local candidate_number = tonumber(ARGV[1])
if not current_number or not candidate_number then
  return -2
end
if candidate_number > current_number then
  redis.call('SET', KEYS[1], ARGV[1])
  return candidate_number
end
return current_number
"""


class TelegramCheckpointError(RuntimeError):
    """Checkpoint is absent at an unsafe stage, malformed, or otherwise unusable."""


class RedisCheckpointClient(Protocol):
    async def get(self, key: str) -> object: ...

    async def set(self, key: str, value: str, *, nx: bool = False) -> object: ...

    async def eval(self, script: str, numkeys: int, *keys_and_args: object) -> object: ...


class TelegramCheckpointStore:
    """Atomic monotonic cursor storage, isolated by the durable NewsSource UUID."""

    def __init__(self, redis_client: RedisCheckpointClient | None = None) -> None:
        self._redis = redis_client if redis_client is not None else get_redis_client()

    @staticmethod
    def key_for(source_id: uuid.UUID) -> str:
        return f"{_KEY_PREFIX}:{source_id}"

    async def get(self, source_id: uuid.UUID) -> int | None:
        raw = await self._redis.get(self.key_for(source_id))
        if raw is None:
            return None
        try:
            value = int(raw)
        except (TypeError, ValueError) as error:
            raise TelegramCheckpointError(f"Malformed Telegram checkpoint for source {source_id}") from error
        if value < 0:
            raise TelegramCheckpointError(f"Negative Telegram checkpoint for source {source_id}")
        return value

    async def initialize(self, source_id: uuid.UUID, head_message_id: int) -> int:
        if head_message_id < 0:
            raise TelegramCheckpointError("Telegram head message id cannot be negative")
        key = self.key_for(source_id)
        created = await self._redis.set(key, str(head_message_id), nx=True)
        if created:
            return head_message_id
        existing = await self.get(source_id)
        if existing is None:  # defensive: SET NX lost a race but the winning value disappeared
            raise TelegramCheckpointError(f"Telegram checkpoint initialization race for source {source_id}")
        return existing

    async def advance(self, source_id: uuid.UUID, candidate_message_id: int) -> int:
        if candidate_message_id < 0:
            raise TelegramCheckpointError("Telegram checkpoint candidate cannot be negative")
        result = await self._redis.eval(
            _ADVANCE_SCRIPT, 1, self.key_for(source_id), str(candidate_message_id)
        )
        value = int(result)
        if value == -1:
            raise TelegramCheckpointError(f"Cannot advance absent Telegram checkpoint for source {source_id}")
        if value == -2:
            raise TelegramCheckpointError(f"Cannot advance malformed Telegram checkpoint for source {source_id}")
        return value
