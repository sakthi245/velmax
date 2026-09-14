from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from contextlib import asynccontextmanager


@dataclass
class HTTPCacheConfig:
    cache_dir: Optional[Path] = None
    ttl: int = 86400
    max_size: int = 1_000_000_000
    use_compression: bool = True
    persist_metadata: bool = True


class HTTPCache:
    """Disk-based HTTP cache with TTL and size limits."""

    def __init__(self, config: HTTPCacheConfig):
        self.config = config
        self._db_path = (config.cache_dir or Path("./cache/http")) / "cache.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self):
        if self._initialized:
            return

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS http_cache (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                response_data TEXT NOT NULL,
                created_at REAL NOT NULL,
                expires_at REAL NOT NULL,
                size_bytes INTEGER NOT NULL
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_expires ON http_cache(expires_at)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON http_cache(url)")
        self._conn.commit()
        self._initialized = True

        # Start cleanup task
        asyncio.create_task(self._cleanup_loop())

    async def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None

    def make_key(self, url: str, headers: Dict[str, str]) -> str:
        """Generate cache key from URL and relevant headers."""
        # Only include headers that affect response
        relevant_headers = {
            k: v for k, v in headers.items()
            if k.lower() in ("accept", "accept-language", "accept-encoding", "user-agent")
        }
        content = f"{url}|{json.dumps(relevant_headers, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()

    async def get(self, key: str) -> Optional[Dict[str, Any]]:
        if not self._initialized or not self._conn:
            return None

        async with self._lock:
            cursor = self._conn.execute(
                "SELECT response_data, expires_at FROM http_cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            if not row:
                return None

            expires_at = row[1]
            if time.time() > expires_at:
                # Expired, delete
                await self.delete(key)
                return None

            try:
                return json.loads(row[0])
            except json.JSONDecodeError:
                return None

    async def set(self, key: str, data: Dict[str, Any]):
        if not self._initialized or not self._conn:
            return

        response_data = json.dumps(data, ensure_ascii=False)
        size = len(response_data.encode("utf-8"))
        created_at = time.time()
        expires_at = created_at + self.config.ttl

        async with self._lock:
            self._conn.execute(
                """INSERT OR REPLACE INTO http_cache
                (key, url, response_data, created_at, expires_at, size_bytes)
                VALUES (?, ?, ?, ?, ?, ?)""",
                (key, data.get("url", ""), response_data, created_at, expires_at, size)
            )
            self._conn.commit()

        # Check size limit
        await self._enforce_size_limit()

    async def delete(self, key: str):
        if not self._conn:
            return
        async with self._lock:
            self._conn.execute("DELETE FROM http_cache WHERE key = ?", (key,))
            self._conn.commit()

    async def _enforce_size_limit(self):
        if not self._conn:
            return

        cursor = self._conn.execute("SELECT SUM(size_bytes) FROM http_cache")
        total_size = cursor.fetchone()[0] or 0

        if total_size > self.config.max_size:
            # Delete oldest entries until under limit
            target_size = self.config.max_size * 0.8
            cursor = self._conn.execute(
                "SELECT key FROM http_cache ORDER BY created_at ASC"
            )
            for row in cursor:
                self._conn.execute("DELETE FROM http_cache WHERE key = ?", (row[0],))
                self._conn.commit()

                cursor2 = self._conn.execute("SELECT SUM(size_bytes) FROM http_cache")
                new_size = cursor2.fetchone()[0] or 0
                if new_size <= target_size:
                    break

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(3600)  # Run every hour
                if not self._conn:
                    break

                cutoff = time.time()
                async with self._lock:
                    self._conn.execute("DELETE FROM http_cache WHERE expires_at < ?", (cutoff,))
                    self._conn.commit()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def get_stats(self) -> Dict[str, Any]:
        if not self._conn:
            return {}

        cursor = self._conn.execute("SELECT COUNT(*), SUM(size_bytes) FROM http_cache")
        count, total_size = cursor.fetchone()
        return {
            "entries": count or 0,
            "total_size_mb": round((total_size or 0) / (1024 * 1024), 2),
            "max_size_mb": round(self.config.max_size / (1024 * 1024), 2),
        }