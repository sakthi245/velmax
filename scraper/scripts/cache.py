from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import pickle
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class LLMResponseCache:
    """Redis-backed cache for LLM responses with memory fallback."""

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/1",
        memory_fallback: bool = True,
        max_memory_mb: int = 100,
        default_ttl: int = 3600,
    ):
        self.redis_url = redis_url
        self.redis = None
        self.memory_fallback = memory_fallback
        self.max_memory_bytes = max_memory_mb * 1024 * 1024
        self.default_ttl = default_ttl
        self.memory_cache: Dict[str, tuple] = {}  # key -> (value, expires_at)
        self._redis_available = False
        self._init_redis()

    def _init_redis(self):
        """Initialize Redis connection."""
        try:
            import redis.asyncio as redis
            self.redis = redis.from_url(self.redis_url, decode_responses=True)
            self._redis_available = True
            logger.info(f"LLM cache: Redis connected at {self.redis_url}")
        except Exception as e:
            logger.warning(f"LLM cache: Redis unavailable, using memory fallback: {e}")
            self._redis_available = False

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        # Try Redis first
        if self._redis_available and self.redis:
            try:
                data = await self.redis.get(key)
                if data:
                    return json.loads(data)
            except Exception as e:
                logger.debug(f"LLM cache Redis get failed: {e}")

        # Fallback to memory
        if self.memory_fallback:
            entry = self.memory_cache.get(key)
            if entry:
                value, expires_at = entry
                if expires_at is None or datetime.utcnow() < expires_at:
                    return value
                else:
                    # Expired
                    del self.memory_cache[key]
        return None

    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache."""
        ttl = ttl or self.default_ttl
        data = json.dumps(value, default=str)

        # Try Redis first
        if self._redis_available and self.redis:
            try:
                await self.redis.setex(key, ttl, data)
                return True
            except Exception as e:
                logger.debug(f"LLM cache Redis set failed: {e}")

        # Fallback to memory
        if self.memory_fallback:
            # Simple LRU eviction
            if len(self.memory_cache) > 10000:
                # Remove oldest 20%
                items = list(self.memory_cache.items())
                items.sort(key=lambda x: x[1][1] or datetime.max)
                to_remove = int(len(items) * 0.2)
                for k, _ in items[:to_remove]:
                    del self.memory_cache[k]

            expires_at = datetime.utcnow() + timedelta(seconds=ttl) if ttl else None
            self.memory_cache[key] = (value, expires_at)
        return True

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if self._redis_available and self.redis:
            try:
                await self.redis.delete(key)
            except Exception:
                pass
        if self.memory_fallback:
            self.memory_cache.pop(key, None)
        return True

    async def close(self):
        """Close Redis connection."""
        if self.redis:
            try:
                await self.redis.close()
            except Exception:
                pass


@dataclass
class CacheConfig:
    """Configuration for script cache."""
    cache_dir: str = "./scripts_cache"
    max_entries: int = 1000
    ttl_hours: int = 168  # 1 week
    enable_compression: bool = True
    max_size_mb: int = 100
    cleanup_interval_hours: int = 24


@dataclass
class CacheEntry:
    """A cache entry with metadata."""
    key: str
    value: Any
    created_at: str
    expires_at: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    last_accessed: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    access_count: int = 0

    def is_expired(self) -> bool:
        """Check if entry is expired."""
        if self.expires_at is None:
            return False
        return datetime.fromisoformat(self.expires_at) < datetime.utcnow()

    def touch(self) -> None:
        """Update last accessed time and increment access count."""
        self.last_accessed = datetime.utcnow().isoformat()
        self.access_count += 1


class ScriptCache:
    """Cache for storing generated scripts and profiles."""

    def __init__(self, config: Optional[CacheConfig] = None):
        self.config = config or CacheConfig()
        self._cache: Dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None
        self._initialized = False

        # Create cache directory
        self.cache_dir = Path(self.config.cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        # Load existing cache
        self._load_cache()

        # Start cleanup task
        self._start_cleanup_task()

    def _get_cache_file(self, key: str) -> Path:
        """Get cache file path for a key."""
        safe_key = hashlib.sha256(key.encode()).hexdigest()[:32]
        return self.cache_dir / f"{safe_key}.pkl"

    def _load_cache(self):
        """Load cache from disk."""
        try:
            for cache_file in self.cache_dir.glob("*.pkl"):
                try:
                    with open(cache_file, "rb") as f:
                        entry = pickle.load(f)
                        if not entry.is_expired():
                            self._cache[entry.key] = entry
                        else:
                            cache_file.unlink()
                except Exception as e:
                    logger.warning(f"Failed to load cache entry {cache_file}: {e}")
        except Exception as e:
            logger.warning(f"Failed to load cache: {e}")

    def _save_entry(self, entry: CacheEntry):
        """Save entry to disk."""
        try:
            cache_file = self._get_cache_file(entry.key)
            with open(cache_file, "wb") as f:
                pickle.dump(entry, f)
        except Exception as e:
            logger.warning(f"Failed to save cache entry {entry.key}: {e}")

    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        async with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                # Try loading from disk
                cache_file = self._get_cache_file(key)
                if cache_file.exists():
                    try:
                        with open(cache_file, "rb") as f:
                            entry = pickle.load(f)
                            if not entry.is_expired():
                                self._cache[key] = entry
                            else:
                                # Expired, remove
                                self._remove_file(key)
                                return None
                    except Exception:
                        return None

            if entry is None or entry.is_expired():
                return None

            entry.touch()
            self._save_entry(entry)
            return entry.value

    async def set(
        self,
        key: str,
        value: Any,
        ttl_hours: Optional[int] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Set value in cache."""
        async with self._lock:
            now = datetime.utcnow()
            expires_at = None
            if ttl_hours is not None:
                expires_at = (datetime.utcnow() + timedelta(hours=ttl_hours)).isoformat()
            elif self.config.ttl_hours:
                expires_at = (datetime.utcnow() + timedelta(hours=self.config.ttl_hours)).isoformat()

            entry = CacheEntry(
                key=key,
                value=value,
                created_at=datetime.utcnow().isoformat(),
                expires_at=expires_at,
                metadata=metadata or {},
            )

            self._cache[key] = entry
            self._save_entry(entry)

            # Check cache size
            await self._enforce_size_limit()

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        async with self._lock:
            if key in self._cache:
                del self._cache[key]
            self._remove_file(key)
            return True

    def _remove_file(self, key: str):
        """Remove cache file from disk."""
        cache_file = self._get_cache_file(key)
        if cache_file.exists():
            try:
                cache_file.unlink()
            except Exception:
                pass

    async def _enforce_size_limit(self):
        """Enforce cache size limit by removing oldest entries."""
        if len(self._cache) <= self.config.max_entries:
            return

        # Sort by last accessed time
        sorted_entries = sorted(
            self._cache.items(),
            key=lambda x: x[1].last_accessed
        )

        # Remove oldest 20%
        to_remove = int(len(self._cache) * 0.2)
        for key, _ in sorted_entries[:to_remove]:
            del self._cache[key]
            self._remove_file(key)

    def _start_cleanup_task(self):
        """Start background cleanup task."""
        if self._cleanup_task is None or self._cleanup_task.done():
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def _cleanup_loop(self):
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval_hours * 3600)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.warning(f"Cache cleanup error: {e}")

    async def _cleanup_expired(self):
        """Remove expired entries."""
        async with self._lock:
            expired_keys = [
                key for key, entry in self._cache.items()
                if entry.is_expired()
            ]

            for key in expired_keys:
                del self._cache[key]
                self._remove_file(key)

            if expired_keys:
                logger.info(f"Cleaned up {len(expired_keys)} expired cache entries")

    def set_cookie_storage(self, storage: Any):
        """Set external cookie storage (e.g., SessionManager)."""
        self._cookie_storage = storage