from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4


@dataclass
class SessionConfig:
    enabled: bool = True
    persist_cookies: bool = True
    persist_auth: bool = True
    cookie_jar_path: Optional[Path] = None
    session_ttl: int = 3600
    max_sessions_per_domain: int = 10
    rotate_on_block: bool = True
    blocked_status_codes: Set[int] = field(default_factory=lambda: {403, 429, 503})
    blocked_error_patterns: List[str] = field(default_factory=lambda: [
        "captcha", "access denied", "blocked", "rate limit",
        "please verify", "unusual traffic", "challenge"
    ])
    storage_backend: str = "sqlite"
    cleanup_interval: int = 300


@dataclass
class Cookie:
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: Optional[float] = None
    secure: bool = False
    http_only: bool = False
    same_site: str = "lax"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "domain": self.domain,
            "path": self.path,
            "expires": self.expires,
            "secure": self.secure,
            "http_only": self.http_only,
            "same_site": self.same_site,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Cookie":
        return cls(**data)

    def is_expired(self) -> bool:
        if self.expires is None:
            return False
        return time.time() > self.expires

    def matches_domain(self, domain: str) -> bool:
        domain = domain.lower().lstrip(".")
        cookie_domain = self.domain.lower().lstrip(".")
        return domain == cookie_domain or domain.endswith("." + cookie_domain)

    def matches_path(self, path: str) -> bool:
        return path.startswith(self.path)


@dataclass
class AuthToken:
    token_type: str
    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[float] = None
    scopes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token_type": self.token_type,
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
            "scopes": self.scopes,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuthToken":
        return cls(**data)

    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at

    def needs_refresh(self, buffer_seconds: int = 300) -> bool:
        if self.expires_at is None:
            return False
        return time.time() > (self.expires_at - buffer_seconds)


@dataclass
class Session:
    session_id: str
    domain: str
    engine: str
    cookies: List[Cookie] = field(default_factory=list)
    headers: Dict[str, str] = field(default_factory=dict)
    auth_tokens: Dict[str, AuthToken] = field(default_factory=dict)
    proxy: Optional[str] = None
    user_agent: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    last_used: float = field(default_factory=time.time)
    use_count: int = 0
    blocked_count: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "domain": self.domain,
            "engine": self.engine,
            "cookies": [c.to_dict() for c in self.cookies],
            "headers": self.headers,
            "auth_tokens": {k: v.to_dict() for k, v in self.auth_tokens.items()},
            "proxy": self.proxy,
            "user_agent": self.user_agent,
            "created_at": self.created_at,
            "last_used": self.last_used,
            "use_count": self.use_count,
            "blocked_count": self.blocked_count,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        session = cls(
            session_id=data["session_id"],
            domain=data["domain"],
            engine=data["engine"],
            cookies=[Cookie.from_dict(c) for c in data.get("cookies", [])],
            headers=data.get("headers", {}),
            auth_tokens={k: AuthToken.from_dict(v) for k, v in data.get("auth_tokens", {}).items()},
            proxy=data.get("proxy"),
            user_agent=data.get("user_agent"),
            created_at=data.get("created_at", time.time()),
            last_used=data.get("last_used", time.time()),
            use_count=data.get("use_count", 0),
            blocked_count=data.get("blocked_count", 0),
            metadata=data.get("metadata", {}),
        )
        return session

    def is_expired(self, ttl: int) -> bool:
        return time.time() - self.last_used > ttl

    def is_blocked(self) -> bool:
        return self.blocked_count > 3

    def add_cookie(self, cookie: Cookie):
        for i, existing in enumerate(self.cookies):
            if existing.name == cookie.name and existing.domain == cookie.domain:
                self.cookies[i] = cookie
                return
        self.cookies.append(cookie)

    def get_cookies_for_url(self, url: str) -> List[Cookie]:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        domain = parsed.netloc
        path = parsed.path or "/"

        return [
            c for c in self.cookies
            if not c.is_expired() and c.matches_domain(domain) and c.matches_path(path)
        ]

    def get_cookie_header(self, url: str) -> str:
        cookies = self.get_cookies_for_url(url)
        return "; ".join(f"{c.name}={c.value}" for c in cookies)


class SessionManager:
    def __init__(self, config: Optional[SessionConfig] = None):
        self.config = config or SessionConfig()
        self._sessions: Dict[str, Session] = {}
        self._domain_sessions: Dict[str, Set[str]] = {}
        self._engine_sessions: Dict[str, Set[str]] = {}
        self._lock = asyncio.Lock()
        self._db_conn: Optional[sqlite3.Connection] = None
        self._cleanup_task: Optional[asyncio.Task] = None
        self._initialized = False

    async def initialize(self) -> None:
        if self._initialized:
            return

        if self.config.storage_backend == "sqlite":
            await self._init_sqlite()
        elif self.config.storage_backend == "redis":
            await self._init_redis()

        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._initialized = True

    async def _init_sqlite(self):
        db_path = self.config.cookie_jar_path or Path("./data/sessions.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._db_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db_conn.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                domain TEXT NOT NULL,
                engine TEXT NOT NULL,
                data TEXT NOT NULL,
                created_at REAL NOT NULL,
                last_used REAL NOT NULL,
                use_count INTEGER DEFAULT 0,
                blocked_count INTEGER DEFAULT 0
            )
        """)
        self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON sessions(domain)")
        self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_engine ON sessions(engine)")
        self._db_conn.execute("CREATE INDEX IF NOT EXISTS idx_last_used ON sessions(last_used)")
        self._db_conn.commit()

        cursor = self._db_conn.execute("SELECT session_id, domain, engine, data FROM sessions")
        for row in cursor:
            session = Session.from_dict(json.loads(row[3]))
            self._sessions[session.session_id] = session
            self._domain_sessions.setdefault(session.domain, set()).add(session.session_id)
            self._engine_sessions.setdefault(session.engine, set()).add(session.session_id)

    async def _init_redis(self):
        pass

    async def close(self) -> None:
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass

        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None

    async def _cleanup_loop(self):
        while True:
            try:
                await asyncio.sleep(self.config.cleanup_interval)
                await self._cleanup_expired()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _cleanup_expired(self):
        async with self._lock:
            expired = []
            for session_id, session in self._sessions.items():
                if session.is_expired(self.config.session_ttl):
                    expired.append(session_id)

            for session_id in expired:
                await self._remove_session(session_id)

            if self._db_conn:
                cutoff = time.time() - self.config.session_ttl
                self._db_conn.execute("DELETE FROM sessions WHERE last_used < ?", (cutoff,))
                self._db_conn.commit()

    async def _remove_session(self, session_id: str):
        session = self._sessions.pop(session_id, None)
        if session:
            self._domain_sessions.get(session.domain, set()).discard(session_id)
            self._engine_sessions.get(session.engine, set()).discard(session_id)

            if self._db_conn:
                self._db_conn.execute("DELETE FROM sessions WHERE session_id = ?", (session_id,))
                self._db_conn.commit()

    async def get_session(
        self,
        domain: str,
        engine: str,
        create_if_missing: bool = True,
    ) -> Optional[Session]:
        async with self._lock:
            domain_sessions = self._domain_sessions.get(domain, set())
            engine_sessions = self._engine_sessions.get(engine, set())

            candidates = domain_sessions & engine_sessions
            for session_id in candidates:
                session = self._sessions.get(session_id)
                if session and not session.is_expired(self.config.session_ttl) and not session.is_blocked():
                    session.last_used = time.time()
                    session.use_count += 1
                    await self._persist_session(session)
                    return session

            if create_if_missing:
                return await self._create_session(domain, engine)

        return None

    async def _create_session(self, domain: str, engine: str) -> Session:
        domain_sessions = self._domain_sessions.get(domain, set())
        if len(domain_sessions) >= self.config.max_sessions_per_domain:
            oldest = min(domain_sessions, key=lambda sid: self._sessions[sid].last_used)
            await self._remove_session(oldest)

        session = Session(
            session_id=f"{domain}_{engine}_{uuid4().hex[:8]}",
            domain=domain,
            engine=engine,
        )

        self._sessions[session.session_id] = session
        self._domain_sessions.setdefault(domain, set()).add(session.session_id)
        self._engine_sessions.setdefault(engine, set()).add(session.session_id)

        await self._persist_session(session)
        return session

    async def _persist_session(self, session: Session):
        if not self._db_conn:
            return

        self._db_conn.execute(
            """
            INSERT OR REPLACE INTO sessions
            (session_id, domain, engine, data, created_at, last_used, use_count, blocked_count)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session.session_id,
                session.domain,
                session.engine,
                json.dumps(session.to_dict()),
                session.created_at,
                session.last_used,
                session.use_count,
                session.blocked_count,
            )
        )
        self._db_conn.commit()

    async def update_session(self, session_id: str, updates: Dict[str, Any]):
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return

            if "cookies" in updates:
                for cookie_data in updates["cookies"]:
                    cookie = Cookie.from_dict(cookie_data)
                    session.add_cookie(cookie)

            if "headers" in updates:
                session.headers.update(updates["headers"])

            if "auth_tokens" in updates:
                for key, token_data in updates["auth_tokens"].items():
                    session.auth_tokens[key] = AuthToken.from_dict(token_data)

            if "proxy" in updates:
                session.proxy = updates["proxy"]

            if "user_agent" in updates:
                session.user_agent = updates["user_agent"]

            if "blocked" in updates and updates["blocked"]:
                session.blocked_count += 1

            session.last_used = time.time()
            await self._persist_session(session)

    async def mark_blocked(self, session_id: str):
        await self.update_session(session_id, {"blocked": True})

    async def get_cookie_jar(self, engine: str):
        class CookieJar:
            def __init__(self, manager: SessionManager, engine: str):
                self.manager = manager
                self.engine = engine

            async def get_cookies(self, url: str) -> List[Dict[str, Any]]:
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                session = await self.manager.get_session(domain, self.engine, create_if_missing=False)
                if session:
                    return [c.to_dict() for c in session.get_cookies_for_url(url)]
                return []

            async def set_cookies(self, url: str, cookies: List[Dict[str, Any]]):
                from urllib.parse import urlparse
                domain = urlparse(url).netloc
                session = await self.manager.get_session(domain, self.engine)
                if session:
                    for c in cookies:
                        session.add_cookie(Cookie.from_dict(c))
                    await self.manager._persist_session(session)

        return CookieJar(self, engine)

    async def get_all_sessions(self, domain: str = None, engine: str = None) -> List[Session]:
        async with self._lock:
            sessions = list(self._sessions.values())
            if domain:
                sessions = [s for s in sessions if s.domain == domain]
            if engine:
                sessions = [s for s in sessions if s.engine == engine]
            return sessions

    async def clear_domain(self, domain: str):
        async with self._lock:
            for session_id in self._domain_sessions.get(domain, set()).copy():
                await self._remove_session(session_id)

    async def clear_engine(self, engine: str):
        async with self._lock:
            for session_id in self._engine_sessions.get(engine, set()).copy():
                await self._remove_session(session_id)

    async def clear_all(self):
        async with self._lock:
            self._sessions.clear()
            self._domain_sessions.clear()
            self._engine_sessions.clear()
            if self._db_conn:
                self._db_conn.execute("DELETE FROM sessions")
                self._db_conn.commit()

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_sessions": len(self._sessions),
            "domains": len(self._domain_sessions),
            "engines": len(self._engine_sessions),
            "sessions_by_domain": {d: len(s) for d, s in self._domain_sessions.items()},
            "sessions_by_engine": {e: len(s) for e, s in self._engine_sessions.items()},
        }


class ProxySessionManager:
    def __init__(self, config: SessionConfig):
        self.config = config
        self._proxy_sessions: Dict[str, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get_session(self, proxy_url: str, domain: str) -> Dict[str, Any]:
        async with self._lock:
            key = f"{proxy_url}:{domain}"
            if key not in self._proxy_sessions:
                self._proxy_sessions[key] = {
                    "proxy_url": proxy_url,
                    "domain": domain,
                    "cookies": {},
                    "headers": {},
                    "auth": None,
                    "created_at": time.time(),
                    "last_used": time.time(),
                    "use_count": 0,
                    "failures": 0,
                }
            session = self._proxy_sessions[key]
            session["last_used"] = time.time()
            session["use_count"] += 1
            return session

    async def update_session(self, proxy_url: str, domain: str, updates: Dict[str, Any]):
        async with self._lock:
            key = f"{proxy_url}:{domain}"
            if key in self._proxy_sessions:
                self._proxy_sessions[key].update(updates)

    async def mark_failure(self, proxy_url: str, domain: str):
        async with self._lock:
            key = f"{proxy_url}:{domain}"
            if key in self._proxy_sessions:
                self._proxy_sessions[key]["failures"] += 1

    async def get_healthy_proxies(self, domain: str, max_failures: int = 3) -> List[str]:
        async with self._lock:
            return [
                s["proxy_url"] for s in self._proxy_sessions.values()
                if s["domain"] == domain and s["failures"] < max_failures
            ]


class SessionContext:
    def __init__(self, manager: SessionManager, domain: str, engine: str):
        self.manager = manager
        self.domain = domain
        self.engine = engine
        self.session: Optional[Session] = None

    async def __aenter__(self) -> Session:
        self.session = await self.manager.get_session(self.domain, self.engine)
        return self.session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and exc_val:
            if isinstance(exc_val, Exception):
                error_str = str(exc_val).lower()
                if any(pattern in error_str for pattern in self.manager.config.blocked_error_patterns):
                    await self.manager.mark_blocked(self.session.session_id)


async def create_session_manager(config: Optional[SessionConfig] = None) -> SessionManager:
    manager = SessionManager(config)
    await manager.initialize()
    return manager