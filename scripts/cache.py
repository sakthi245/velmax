from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from enum import Enum

from scraper.config.schemas import (
    StateBackend,
    CacheConfig,
    CachedScript,
    CacheEntry,
    GeneratedScript,
    ProfileDepth,
)
from scraper.storage.backends import (
    StorageBackend,
    StorageConfig,
    create_storage_backend,
)


class StateBackend(Enum):
    SQLITE = "sqlite"
    REDIS = "redis"
    POSTGRESQL = "postgresql"


@dataclass
class ScriptCache:
    config: CacheConfig
    _storage: Optional[StorageBackend] = None
    _index_db: Optional[Any] = None

    def __post_init__(self):
        self._init_storage()

    def _init_storage(self):
        storage_config = StorageConfig(
            backend=StateBackend(self.config.backend),
            local_path=self.config.cache_dir,
        )
        self._storage = create_storage_backend(storage_config)

        if self.config.backend == "sqlite":
            self._init_sqlite_index()

    def _init_sqlite_index(self):
        import sqlite3
        db_path = self.config.cache_dir / "cache_index.db"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._index_db = sqlite3.connect(str(db_path), check_same_thread=False)
        self._index_db.execute("""
            CREATE TABLE IF NOT EXISTS cache_index (
                key TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                profile_hash TEXT NOT NULL,
                script_path TEXT NOT NULL,
                created_at TEXT NOT NULL,
                ttl_days INTEGER NOT NULL,
                success_count INTEGER DEFAULT 0,
                failure_count INTEGER DEFAULT 0,
                last_used TEXT
            )
        """)
        self._index_db.execute("CREATE INDEX IF NOT EXISTS idx_url ON cache_index(url)")
        self._index_db.execute("CREATE INDEX IF NOT EXISTS idx_profile_hash ON cache_index(profile_hash)")
        self._index_db.commit()

    async def get(self, key: str) -> Optional[CachedScript]:
        entry = await self._get_index_entry(key)
        if not entry:
            return None

        if self._is_expired(entry):
            await self.invalidate(key)
            return None

        if self.config.change_detection:
            current_hash = await self._compute_site_hash(entry.url)
            if current_hash != entry.profile_hash:
                await self.invalidate(key)
                return None

        script = await self._load_script(entry.script_path)
        if script:
            return CachedScript(script=script, metadata=entry)
        return None

    async def set(self, key: str, cached_script: CachedScript):
        script_path = await self._save_script(key, cached_script.script)

        entry = CacheEntry(
            key=key,
            url=cached_script.script.metadata.get("target_url", ""),
            profile_hash=cached_script.metadata.profile_hash,
            script_path=script_path,
            created_at=datetime.utcnow().isoformat(),
            ttl_days=self.config.ttl_days,
        )

        await self._set_index_entry(entry)

    async def invalidate(self, key: str):
        entry = await self._get_index_entry(key)
        if entry:
            try:
                os.remove(entry.script_path)
            except OSError:
                pass
            await self._delete_index_entry(key)

    def _should_regenerate(self, cached: CachedScript, context: Dict[str, Any]) -> bool:
        if context.get("force_regenerate"):
            return True
        if cached.metadata.failure_count >= self.config.max_failures_before_regenerate:
            return True
        return False

    async def record_success(self, key: str):
        await self._update_counts(key, success=True)

    async def record_failure(self, key: str):
        await self._update_counts(key, success=False)

    async def _get_index_entry(self, key: str) -> Optional[CacheEntry]:
        if self._index_db:
            cursor = self._index_db.execute(
                "SELECT * FROM cache_index WHERE key = ?", (key,)
            )
            row = cursor.fetchone()
            if row:
                return CacheEntry(
                    key=row[0], url=row[1], profile_hash=row[2],
                    script_path=row[3], created_at=row[4],
                    ttl_days=row[5], success_count=row[6],
                    failure_count=row[7], last_used=row[8],
                )
        return None

    async def _set_index_entry(self, entry: CacheEntry):
        if self._index_db:
            self._index_db.execute(
                """INSERT OR REPLACE INTO cache_index
                (key, url, profile_hash, script_path, created_at, ttl_days,
                 success_count, failure_count, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (entry.key, entry.url, entry.profile_hash, entry.script_path,
                 entry.created_at, entry.ttl_days, entry.success_count,
                 entry.failure_count, entry.last_used)
            )
            self._index_db.commit()

    async def _delete_index_entry(self, key: str):
        if self._index_db:
            self._index_db.execute("DELETE FROM cache_index WHERE key = ?", (key,))
            self._index_db.commit()

    async def _update_counts(self, key: str, success: bool):
        if self._index_db:
            if success:
                self._index_db.execute(
                    "UPDATE cache_index SET success_count = success_count + 1, last_used = ? WHERE key = ?",
                    (datetime.utcnow().isoformat(), key)
                )
            else:
                self._index_db.execute(
                    "UPDATE cache_index SET failure_count = failure_count + 1, last_used = ? WHERE key = ?",
                    (datetime.utcnow().isoformat(), key)
                )
            self._index_db.commit()

    def _is_expired(self, entry: CacheEntry) -> bool:
        created = datetime.fromisoformat(entry.created_at)
        return datetime.utcnow() > created + timedelta(days=entry.ttl_days)

    async def _compute_site_hash(self, url: str) -> str:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(url)
                content = resp.text[:10000]
                return hashlib.sha256(content.encode()).hexdigest()[:16]
        except Exception:
            return ""

    async def _save_script(self, key: str, script: GeneratedScript) -> str:
        script_path = self.config.cache_dir / "scripts" / f"{key}.json"
        script_path.parent.mkdir(parents=True, exist_ok=True)
        script_path.write_text(script.model_dump_json(indent=2))
        return str(script_path)

    async def _load_script(self, path: str) -> Optional[GeneratedScript]:
        try:
            data = json.loads(Path(path).read_text())
            return GeneratedScript(**data)
        except Exception:
            return None