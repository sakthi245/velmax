from __future__ import annotations

import asyncio
import json
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from urllib.parse import urlparse

import asyncpg
from asyncpg import Pool

from ..config.schemas import StateBackend, CheckpointConfig


@dataclass
class CrawlSession:
    session_id: str
    name: str
    start_urls: List[str]
    config_snapshot: Dict[str, Any]
    created_at: datetime
    updated_at: datetime
    status: str = "running"
    pages_crawled: int = 0
    pages_failed: int = 0
    current_depth: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class URLFrontierEntry:
    url: str
    depth: int
    priority: int
    parent_url: Optional[str]
    discovered_at: datetime
    scheduled_at: Optional[datetime] = None
    attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    status: str = "pending"
    error: Optional[str] = None


@dataclass
class VisitedURL:
    url: str
    session_id: str
    depth: int
    status_code: int
    content_hash: Optional[str]
    crawled_at: datetime
    response_time_ms: int
    error: Optional[str] = None


@dataclass
class Checkpoint:
    checkpoint_id: str
    session_id: str
    sequence: int
    frontier_data: Dict[str, Any]
    visited_count: int
    created_at: datetime
    metadata: Dict[str, Any] = field(default_factory=dict)


class CrawlStateManager:
    def __init__(self, config: CheckpointConfig):
        self.config = config
        self._pool: Optional[Pool] = None
        self._session_id: Optional[str] = None
        self._current_session: Optional[CrawlSession] = None
        self._checkpoint_sequence = 0
        self._last_checkpoint_time = time.time()
        self._last_checkpoint_pages = 0
        self._pages_since_checkpoint = 0

    @property
    def session_id(self) -> Optional[str]:
        return self._session_id

    @property
    def current_session(self) -> Optional[CrawlSession]:
        return self._current_session

    async def initialize(self, dsn: str) -> None:
        self._pool = await asyncpg.create_pool(
            dsn,
            min_size=2,
            max_size=10,
            command_timeout=60,
        )
        await self._create_tables()

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()
            self._pool = None

    async def _create_tables(self) -> None:
        async with self._pool.acquire() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS crawl_sessions (
                    session_id VARCHAR(64) PRIMARY KEY,
                    name VARCHAR(256) NOT NULL,
                    start_urls JSONB NOT NULL,
                    config_snapshot JSONB NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'running',
                    pages_crawled INTEGER NOT NULL DEFAULT 0,
                    pages_failed INTEGER NOT NULL DEFAULT 0,
                    current_depth INTEGER NOT NULL DEFAULT 0,
                    metadata JSONB NOT NULL DEFAULT '{}'
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS url_frontier (
                    id BIGSERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES crawl_sessions(session_id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    priority INTEGER NOT NULL DEFAULT 0,
                    parent_url TEXT,
                    discovered_at TIMESTAMPTZ NOT NULL,
                    scheduled_at TIMESTAMPTZ,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    last_attempt_at TIMESTAMPTZ,
                    status VARCHAR(32) NOT NULL DEFAULT 'pending',
                    error TEXT,
                    UNIQUE(session_id, url)
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_url_frontier_session_status
                ON url_frontier(session_id, status, priority DESC, discovered_at)
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS visited_urls (
                    id BIGSERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES crawl_sessions(session_id) ON DELETE CASCADE,
                    url TEXT NOT NULL,
                    depth INTEGER NOT NULL,
                    status_code INTEGER,
                    content_hash VARCHAR(64),
                    crawled_at TIMESTAMPTZ NOT NULL,
                    response_time_ms INTEGER NOT NULL DEFAULT 0,
                    error TEXT,
                    UNIQUE(session_id, url)
                )
            """)

            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_visited_urls_session
                ON visited_urls(session_id, crawled_at)
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS checkpoints (
                    checkpoint_id VARCHAR(64) PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES crawl_sessions(session_id) ON DELETE CASCADE,
                    sequence INTEGER NOT NULL,
                    frontier_data JSONB NOT NULL,
                    visited_count INTEGER NOT NULL,
                    created_at TIMESTAMPTZ NOT NULL,
                    metadata JSONB NOT NULL DEFAULT '{}',
                    UNIQUE(session_id, sequence)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_cookies (
                    id BIGSERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES crawl_sessions(session_id) ON DELETE CASCADE,
                    domain VARCHAR(256) NOT NULL,
                    cookies JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(session_id, domain)
                )
            """)

            await conn.execute("""
                CREATE TABLE IF NOT EXISTS session_headers (
                    id BIGSERIAL PRIMARY KEY,
                    session_id VARCHAR(64) NOT NULL REFERENCES crawl_sessions(session_id) ON DELETE CASCADE,
                    domain VARCHAR(256) NOT NULL,
                    headers JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL,
                    UNIQUE(session_id, domain)
                )
            """)

    async def create_session(
        self,
        name: str,
        start_urls: List[str],
        config_snapshot: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> CrawlSession:
        session_id = str(uuid.uuid4())[:16]
        now = datetime.now(timezone.utc)

        session = CrawlSession(
            session_id=session_id,
            name=name,
            start_urls=start_urls,
            config_snapshot=config_snapshot,
            created_at=now,
            updated_at=now,
            metadata=metadata or {},
        )

        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO crawl_sessions
                (session_id, name, start_urls, config_snapshot, created_at, updated_at, status, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
                session.session_id,
                session.name,
                json.dumps(session.start_urls),
                json.dumps(session.config_snapshot),
                session.created_at,
                session.updated_at,
                session.status,
                json.dumps(session.metadata),
            )

            for url in start_urls:
                await conn.execute("""
                    INSERT INTO url_frontier (session_id, url, depth, priority, parent_url, discovered_at, status)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (session_id, url) DO NOTHING
                """,
                    session.session_id,
                    url,
                    0,
                    100,
                    None,
                    now,
                    "pending",
                )

        self._session_id = session.session_id
        self._current_session = session
        self._checkpoint_sequence = 0
        self._last_checkpoint_time = time.time()
        self._last_checkpoint_pages = 0
        self._pages_since_checkpoint = 0

        return session

    async def resume_session(self, session_id: str) -> Optional[CrawlSession]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM crawl_sessions WHERE session_id = $1
            """, session_id)

            if not row:
                return None

            session = CrawlSession(
                session_id=row["session_id"],
                name=row["name"],
                start_urls=json.loads(row["start_urls"]),
                config_snapshot=json.loads(row["config_snapshot"]),
                created_at=row["created_at"],
                updated_at=row["updated_at"],
                status=row["status"],
                pages_crawled=row["pages_crawled"],
                pages_failed=row["pages_failed"],
                current_depth=row["current_depth"],
                metadata=json.loads(row["metadata"]),
            )

            self._session_id = session_id
            self._current_session = session
            return session

    async def get_next_urls(self, count: int = 10) -> List[URLFrontierEntry]:
        if not self._session_id:
            return []

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT * FROM url_frontier
                WHERE session_id = $1 AND status = 'pending'
                ORDER BY priority DESC, discovered_at
                LIMIT $2
                FOR UPDATE SKIP LOCKED
            """, self._session_id, count)

            urls = []
            for row in rows:
                await conn.execute("""
                    UPDATE url_frontier
                    SET status = 'processing', last_attempt_at = $1, attempts = attempts + 1
                    WHERE id = $2
                """, datetime.now(timezone.utc), row["id"])

                urls.append(URLFrontierEntry(
                    url=row["url"],
                    depth=row["depth"],
                    priority=row["priority"],
                    parent_url=row["parent_url"],
                    discovered_at=row["discovered_at"],
                    scheduled_at=row["scheduled_at"],
                    attempts=row["attempts"],
                    last_attempt_at=row["last_attempt_at"],
                    status="processing",
                    error=row["error"],
                ))

            return urls

    async def mark_url_completed(
        self,
        url: str,
        status_code: int,
        content_hash: Optional[str] = None,
        response_time_ms: int = 0,
        error: Optional[str] = None,
        new_urls: Optional[List[tuple[str, int, int, Optional[str]]]] = None,
    ) -> None:
        if not self._session_id:
            return

        now = datetime.now(timezone.utc)
        is_error = error is not None or status_code >= 400

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute("""
                    INSERT INTO visited_urls
                    (session_id, url, depth, status_code, content_hash, crawled_at, response_time_ms, error)
                    VALUES ($1, $2, (
                        SELECT depth FROM url_frontier WHERE session_id = $1 AND url = $2
                    ), $3, $4, $5, $6, $7)
                    ON CONFLICT (session_id, url) DO UPDATE SET
                        status_code = EXCLUDED.status_code,
                        content_hash = EXCLUDED.content_hash,
                        crawled_at = EXCLUDED.crawled_at,
                        response_time_ms = EXCLUDED.response_time_ms,
                        error = EXCLUDED.error
                """,
                    self._session_id,
                    url,
                    status_code,
                    content_hash,
                    now,
                    response_time_ms,
                    error,
                )

                await conn.execute("""
                    UPDATE url_frontier
                    SET status = $1, error = $2
                    WHERE session_id = $3 AND url = $4
                """,
                    "completed" if not is_error else "failed",
                    error,
                    self._session_id,
                    url,
                )

                if self._current_session:
                    if is_error:
                        self._current_session.pages_failed += 1
                    else:
                        self._current_session.pages_crawled += 1

                    await conn.execute("""
                        UPDATE crawl_sessions
                        SET pages_crawled = $1, pages_failed = $2, updated_at = $3
                        WHERE session_id = $4
                    """,
                        self._current_session.pages_crawled,
                        self._current_session.pages_failed,
                        now,
                        self._session_id,
                    )

                self._pages_since_checkpoint += 1

                if new_urls:
                    for new_url, depth, priority, parent in new_urls:
                        await conn.execute("""
                            INSERT INTO url_frontier (session_id, url, depth, priority, parent_url, discovered_at, status)
                            VALUES ($1, $2, $3, $4, $5, $6, 'pending')
                            ON CONFLICT (session_id, url) DO NOTHING
                        """,
                            self._session_id,
                            new_url,
                            depth,
                            priority,
                            parent,
                            now,
                        )

    async def should_checkpoint(self) -> bool:
        if not self.config.enabled:
            return False

        pages_trigger = self._pages_since_checkpoint >= self.config.interval_pages
        time_trigger = (time.time() - self._last_checkpoint_time) >= self.config.interval_seconds

        return pages_trigger or time_trigger

    async def create_checkpoint(self, frontier_data: Dict[str, Any], metadata: Optional[Dict[str, Any]] = None) -> Checkpoint:
        if not self._session_id:
            raise RuntimeError("No active session")

        self._checkpoint_sequence += 1
        checkpoint_id = str(uuid.uuid4())[:16]
        now = datetime.now(timezone.utc)

        visited_count = 0
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as count FROM visited_urls WHERE session_id = $1
            """, self._session_id)
            visited_count = row["count"]

            await conn.execute("""
                INSERT INTO checkpoints
                (checkpoint_id, session_id, sequence, frontier_data, visited_count, created_at, metadata)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
                checkpoint_id,
                self._session_id,
                self._checkpoint_sequence,
                json.dumps(frontier_data),
                visited_count,
                now,
                json.dumps(metadata or {}),
            )

            await self._cleanup_old_checkpoints()

        checkpoint = Checkpoint(
            checkpoint_id=checkpoint_id,
            session_id=self._session_id,
            sequence=self._checkpoint_sequence,
            frontier_data=frontier_data,
            visited_count=visited_count,
            created_at=now,
            metadata=metadata or {},
        )

        self._last_checkpoint_time = time.time()
        self._last_checkpoint_pages = self._current_session.pages_crawled if self._current_session else 0
        self._pages_since_checkpoint = 0

        return checkpoint

    async def _cleanup_old_checkpoints(self) -> None:
        if not self._session_id:
            return

        async with self._pool.acquire() as conn:
            await conn.execute("""
                DELETE FROM checkpoints
                WHERE session_id = $1
                AND sequence NOT IN (
                    SELECT sequence FROM checkpoints
                    WHERE session_id = $1
                    ORDER BY sequence DESC
                    LIMIT $2
                )
            """, self._session_id, self.config.max_checkpoints)

            cutoff = datetime.now(timezone.utc).timestamp() - (self.config.retention_days * 86400)
            await conn.execute("""
                DELETE FROM checkpoints
                WHERE session_id = $1 AND created_at < to_timestamp($2)
            """, self._session_id, cutoff)

    async def get_latest_checkpoint(self) -> Optional[Checkpoint]:
        if not self._session_id:
            return None

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT * FROM checkpoints
                WHERE session_id = $1
                ORDER BY sequence DESC
                LIMIT 1
            """, self._session_id)

            if not row:
                return None

            return Checkpoint(
                checkpoint_id=row["checkpoint_id"],
                session_id=row["session_id"],
                sequence=row["sequence"],
                frontier_data=json.loads(row["frontier_data"]),
                visited_count=row["visited_count"],
                created_at=row["created_at"],
                metadata=json.loads(row["metadata"]),
            )

    async def get_visited_count(self) -> int:
        if not self._session_id:
            return 0

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as count FROM visited_urls WHERE session_id = $1
            """, self._session_id)
            return row["count"]

    async def get_pending_count(self) -> int:
        if not self._session_id:
            return 0

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as count FROM url_frontier
                WHERE session_id = $1 AND status = 'pending'
            """, self._session_id)
            return row["count"]

    async def get_failed_count(self) -> int:
        if not self._session_id:
            return 0

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT COUNT(*) as count FROM url_frontier
                WHERE session_id = $1 AND status = 'failed'
            """, self._session_id)
            return row["count"]

    async def save_cookies(self, domain: str, cookies: List[Dict[str, Any]]) -> None:
        if not self._session_id:
            return

        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO session_cookies (session_id, domain, cookies, updated_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (session_id, domain) DO UPDATE SET
                    cookies = EXCLUDED.cookies,
                    updated_at = EXCLUDED.updated_at
            """,
                self._session_id,
                domain,
                json.dumps(cookies),
                now,
            )

    async def load_cookies(self, domain: str) -> List[Dict[str, Any]]:
        if not self._session_id:
            return []

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT cookies FROM session_cookies
                WHERE session_id = $1 AND domain = $2
            """, self._session_id, domain)

            if row:
                return json.loads(row["cookies"])
            return []

    async def save_headers(self, domain: str, headers: Dict[str, str]) -> None:
        if not self._session_id:
            return

        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO session_headers (session_id, domain, headers, updated_at)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (session_id, domain) DO UPDATE SET
                    headers = EXCLUDED.headers,
                    updated_at = EXCLUDED.updated_at
            """,
                self._session_id,
                domain,
                json.dumps(headers),
                now,
            )

    async def load_headers(self, domain: str) -> Dict[str, str]:
        if not self._session_id:
            return {}

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT headers FROM session_headers
                WHERE session_id = $1 AND domain = $2
            """, self._session_id, domain)

            if row:
                return json.loads(row["headers"])
            return {}

    async def get_session_stats(self) -> Dict[str, Any]:
        if not self._session_id:
            return {}

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM visited_urls WHERE session_id = $1) as visited,
                    (SELECT COUNT(*) FROM url_frontier WHERE session_id = $1 AND status = 'pending') as pending,
                    (SELECT COUNT(*) FROM url_frontier WHERE session_id = $1 AND status = 'failed') as failed,
                    (SELECT COUNT(*) FROM checkpoints WHERE session_id = $1) as checkpoints
            """, self._session_id)

            return dict(row) if row else {}

    async def mark_session_completed(self, status: str = "completed") -> None:
        if not self._session_id:
            return

        now = datetime.now(timezone.utc)
        async with self._pool.acquire() as conn:
            await conn.execute("""
                UPDATE crawl_sessions
                SET status = $1, updated_at = $2
                WHERE session_id = $3
            """, status, now, self._session_id)


@asynccontextmanager
async def create_state_manager(config: CheckpointConfig, dsn: str):
    manager = CrawlStateManager(config)
    await manager.initialize(dsn)
    try:
        yield manager
    finally:
        await manager.close()