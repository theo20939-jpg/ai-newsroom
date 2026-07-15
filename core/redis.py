"""Async Redis client factory."""
from functools import lru_cache

from redis.asyncio import Redis

from core.config import settings


@lru_cache
def get_redis_client() -> Redis:
    """Return a cached async Redis client instance."""
    return Redis.from_url(settings.redis_url, decode_responses=True)
