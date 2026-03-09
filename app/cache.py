"""
Cache Module - Enterprise Grade with Redis Auto-Recovery
=========================================================

Provides robust caching mechanism with:
1. Redis backend with Connection Pooling (primary)
2. In-memory fallback with Thread-safe locking (secondary)
3. Automatic serialization (JSON)
4. Auto-recovery: Redis reconnect after failure
5. Graceful degradation on any Redis error
"""

import os
import json
import logging
import threading
import time
from typing import Any, Optional, Union
from datetime import datetime, timedelta, timezone

# Global objects
_redis_pool = None
_redis_client = None
_memory_cache: dict = {}
_expiry_cache: dict = {}
_lock = threading.RLock()
_redis_available = False

# Reconnect cooldown (prevent spam reconnect)
_last_redis_failure: float = 0.0
_RECONNECT_COOLDOWN_SECONDS = 10  # Tunggu 10 detik sebelum coba reconnect


def _reset_redis_client():
    """
    Reset Redis client state agar panggilan berikutnya mencoba reconnect.
    
    Dipanggil saat operasi Redis gagal (get/set/delete).
    Ini memastikan:
    1. Client lama yang 'busuk' (dead connection) dibuang
    2. Panggilan _get_redis_client() berikutnya akan coba koneksi baru
    3. Sementara itu, operasi fallback ke memory cache
    """
    global _redis_client, _redis_available, _last_redis_failure
    _redis_client = None
    _redis_available = False
    _last_redis_failure = time.monotonic()


def _get_redis_client():
    """
    Get or create Redis client with connection pool.
    
    Flow:
    1. Jika client sudah ada → health-check dengan ping()
    2. Jika ping gagal → reset client, fallback ke memory
    3. Jika client None → coba koneksi baru (dengan cooldown)
    4. Jika semua gagal → return None (memory cache akan dipakai)
    """
    global _redis_pool, _redis_client, _redis_available, _last_redis_failure

    # Fast path: client sudah ada dan sehat
    if _redis_client:
        try:
            _redis_client.ping()
            return _redis_client
        except Exception:
            # Client ada tapi dead → reset
            logging.warning("[CACHE] Redis connection lost. Resetting client...")
            _reset_redis_client()
            return None

    # Cooldown: jangan spam reconnect
    if _last_redis_failure > 0:
        elapsed = time.monotonic() - _last_redis_failure
        if elapsed < _RECONNECT_COOLDOWN_SECONDS:
            return None  # Masih dalam cooldown, pakai memory

    redis_url = os.environ.get('REDIS_URL')
    if not redis_url:
        _redis_available = False
        return None

    try:
        import redis
        if not _redis_pool:
            _redis_pool = redis.ConnectionPool.from_url(redis_url, decode_responses=True)

        _redis_client = redis.Redis(connection_pool=_redis_pool)
        _redis_client.ping()  # Fail fast check
        _redis_available = True
        _last_redis_failure = 0.0  # Reset cooldown
        # Mask credentials in log output
        from urllib.parse import urlparse
        parsed = urlparse(redis_url)
        safe_url = f"{parsed.scheme}://{parsed.hostname}:{parsed.port or 6379}/{parsed.path.lstrip('/')}"
        logging.info(f"[CACHE] Connected to Redis at {safe_url}")
        return _redis_client
    except ImportError:
        logging.warning("[CACHE] 'redis' library not installed. Using memory cache.")
        _redis_available = False
        return None
    except Exception as e:
        logging.error(f"[CACHE] Redis connection failed: {e}. Fallback to memory.")
        _reset_redis_client()
        return None


def is_redis_available() -> bool:
    """Check if Redis is currently available/connected."""
    _get_redis_client()
    return _redis_available


def get(key: str) -> Optional[Any]:
    """
    Retrieve value from cache.
    Strategy: Try Redis → on failure, reset client & fallthrough to Memory.
    """
    client = _get_redis_client()

    # 1. Try Redis
    if client:
        try:
            val = client.get(key)
            if val is not None:
                return json.loads(val)
            return None  # Key not found in Redis
        except Exception as e:
            logging.error(f"[CACHE] Redis get error: {e}")
            _reset_redis_client()
            # Fallthrough ke memory cache

    # 2. Memory Cache (Fallback)
    with _lock:
        if key not in _memory_cache:
            return None

        # Check expiry
        expiry = _expiry_cache.get(key)
        if expiry and datetime.now(timezone.utc) > expiry:
            del _memory_cache[key]
            del _expiry_cache[key]
            return None

        return _memory_cache[key]


def set(key: str, value: Any, timeout: int = 300) -> bool:
    """
    Set value in cache.
    Strategy: Try Redis → on failure, reset client & write to Memory.
    Always writes to memory as backup when Redis fails.
    """
    client = _get_redis_client()

    success = False

    # 1. Redis
    if client:
        try:
            client.setex(key, timeout, json.dumps(value))
            success = True
        except TypeError as e:
            logging.error(f"[CACHE] Serialization error for key {key}: {e}")
            return False
        except Exception as e:
            logging.error(f"[CACHE] Redis set error: {e}")
            _reset_redis_client()
            # Fallthrough to memory on Redis failure

    # 2. Memory (write if Redis failed or not available)
    if not success:
        with _lock:
            _memory_cache[key] = value
            _expiry_cache[key] = datetime.now(timezone.utc) + timedelta(seconds=timeout)

    return True


def delete(key: str) -> bool:
    """Delete value from cache."""
    client = _get_redis_client()

    if client:
        try:
            client.delete(key)
        except Exception as e:
            logging.error(f"[CACHE] Redis delete error: {e}")
            _reset_redis_client()

    with _lock:
        if key in _memory_cache:
            del _memory_cache[key]
        if key in _expiry_cache:
            del _expiry_cache[key]

    return True


def clear() -> bool:
    """Clear all cache."""
    client = _get_redis_client()

    if client:
        try:
            client.flushdb()
        except Exception as e:
            logging.error(f"[CACHE] Redis flush error: {e}")
            _reset_redis_client()

    with _lock:
        _memory_cache.clear()
        _expiry_cache.clear()

    return True
