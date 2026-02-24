"""
Cache Service - High-level caching service for the application
==============================================================

Provides a service class with backend detection and unified interface.
Used by run.py for startup initialization.
"""

import logging
from typing import Any, Optional


class CacheService:
    """Cache service with Redis/Memory backend."""
    
    def __init__(self, backend: str = 'memory'):
        self.backend = backend
        self._cache = None
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        from app import cache as _cache
        return _cache.get(key)
    
    def set(self, key: str, value: Any, timeout: int = 300) -> bool:
        """Set value in cache."""
        from app import cache as _cache
        return _cache.set(key, value, timeout)
    
    def delete(self, key: str) -> bool:
        """Delete key from cache."""
        from app import cache as _cache
        return _cache.delete(key)
    
    def clear(self) -> bool:
        """Clear all cache entries."""
        from app import cache as _cache
        return _cache.clear()


_instance: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    """
    Get or create the cache service singleton.
    Detects Redis availability and sets backend accordingly.
    """
    global _instance
    
    if _instance is not None:
        return _instance
    
    # Determine backend
    from app import cache as _cache
    if _cache.is_redis_available():
        backend = 'redis'
        logging.info("[CACHE_SERVICE] Using Redis backend")
    else:
        backend = 'memory'
        logging.info("[CACHE_SERVICE] Using in-memory backend")
    
    _instance = CacheService(backend=backend)
    return _instance


def reset_cache_service():
    """Reset the cache service singleton (for testing)."""
    global _instance
    _instance = None
