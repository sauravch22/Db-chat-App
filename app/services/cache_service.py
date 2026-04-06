"""Async Redis Cache Service"""

import json
import logging
from typing import Any, Optional

import redis.asyncio as aioredis

from app.config import Settings

logger = logging.getLogger(__name__)

settings = Settings()


class CacheService:
    """Async Redis cache used for SQL-level and result-level caching."""

    def __init__(self):
        self._redis: Optional[aioredis.Redis] = None

    async def _get_redis(self) -> aioredis.Redis:
        if self._redis is None:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
                socket_connect_timeout=5,
            )
        return self._redis

    async def get(self, key: str) -> Optional[Any]:
        try:
            r = await self._get_redis()
            value = await r.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.debug("Cache GET miss/error for %s: %s", key, e)
            return None

    async def set(self, key: str, value: Any, ttl: int = 3600):
        try:
            r = await self._get_redis()
            await r.setex(key, ttl, json.dumps(value, default=str))
        except Exception as e:
            logger.debug("Cache SET error for %s: %s", key, e)

    async def delete(self, key: str):
        try:
            r = await self._get_redis()
            await r.delete(key)
        except Exception as e:
            logger.debug("Cache DELETE error for %s: %s", key, e)

    async def clear_pattern(self, pattern: str):
        """Delete keys matching *pattern* using SCAN (production-safe)."""
        try:
            r = await self._get_redis()
            cursor = 0
            while True:
                cursor, keys = await r.scan(cursor, match=pattern, count=200)
                if keys:
                    await r.delete(*keys)
                if cursor == 0:
                    break
        except Exception as e:
            logger.debug("Cache CLEAR error for %s: %s", pattern, e)

    async def health_check(self) -> bool:
        try:
            r = await self._get_redis()
            return await r.ping()
        except Exception:
            return False

    async def close(self):
        if self._redis:
            await self._redis.close()
            self._redis = None
