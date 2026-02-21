"""Redis Cache Service"""

import redis
import json
import logging
from app.config import Settings
from typing import Any, Optional

logger = logging.getLogger(__name__)

settings = Settings()


class CacheService:
    """Service for caching with Redis"""
    
    def __init__(self):
        self.redis_client = redis.from_url(settings.REDIS_URL)
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache"""
        
        try:
            value = self.redis_client.get(key)
            if value:
                return json.loads(value)
            return None
        except Exception as e:
            logger.error(f"Error getting cache key {key}: {str(e)}")
            return None
    
    async def set(
        self,
        key: str,
        value: Any,
        ttl: int = 3600  # Default 1 hour
    ):
        """Set value in cache"""
        
        try:
            self.redis_client.setex(
                key,
                ttl,
                json.dumps(value)
            )
            logger.debug(f"Cached key {key} with TTL {ttl}s")
        except Exception as e:
            logger.error(f"Error setting cache key {key}: {str(e)}")
    
    async def delete(self, key: str):
        """Delete value from cache"""
        
        try:
            self.redis_client.delete(key)
            logger.debug(f"Deleted cache key {key}")
        except Exception as e:
            logger.error(f"Error deleting cache key {key}: {str(e)}")
    
    async def clear_pattern(self, pattern: str):
        """Delete all keys matching pattern"""
        
        try:
            keys = self.redis_client.keys(pattern)
            if keys:
                self.redis_client.delete(*keys)
                logger.debug(f"Cleared {len(keys)} keys matching {pattern}")
        except Exception as e:
            logger.error(f"Error clearing cache pattern {pattern}: {str(e)}")
    
    async def health_check(self) -> bool:
        """Check if Redis is running"""
        
        try:
            self.redis_client.ping()
            return True
        except:
            return False
