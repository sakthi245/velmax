from __future__ import annotations

import asyncio
import time
import json
import weakref
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Callable, Awaitable
from collections import OrderedDict, defaultdict
from threading import Lock

import httpx
import aiohttp
from aiohttp import TCPConnector, ClientTimeout, ClientSession
from aiohttp.client_exceptions import ClientError, ServerDisconnectedError

from ..config.schemas import HTTPEngineConfig
from ..utils.observability import get_logger


@dataclass
class RateLimitConfig:
    requests_per_second: float = 2.0
    requests_per_minute: Optional[float] = None
    requests_per_hour: Optional[float] = None
    burst_allowance: int = 5
    per_domain: bool = True
    adaptive: bool = True
    respect_retry_after: bool = True
    respect_rate_limit_headers: bool = True
    default_retry_after: float = 60.0


@dataclass
class TokenBucket:
    capacity: float
    tokens: float
    refill_rate: float
    last_refill: float = field(default_factory=time.time)
    lock: Lock = field(default_factory=Lock)

    def consume(self, tokens: int = 1) -> bool:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            return False

    def get_wait_time(self, tokens: int = 1) -> float:
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

            if self.tokens >= tokens:
                return 0.0

            needed = tokens - self.tokens
            return needed / self.refill_rate

    def add_tokens(self, tokens: float):
        with self.lock:
            self.tokens = min(self.capacity, self.tokens + tokens)


class RateLimiter:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._buckets: Dict[str, TokenBucket] = {}
        self._domain_locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        self._global_bucket = TokenBucket(
            capacity=config.burst_allowance,
            tokens=config.burst_allowance,
            refill_rate=config.requests_per_second,
        )
        self._retry_after: Dict[str, float] = {}
        self._rate_limit_headers: Dict[str, Dict[str, str]] = {}
        self._lock = Lock()

    def _get_bucket(self, domain: str) -> TokenBucket:
        with self._lock:
            if domain not in self._buckets:
                self._buckets[domain] = TokenBucket(
                    capacity=self.config.burst_allowance,
                    tokens=self.config.burst_allowance,
                    refill_rate=self.config.requests_per_second,
                )
            return self._buckets[domain]

    async def acquire(self, domain: str, priority: int = 0, tokens: int = 1) -> None:
        if not self.config.per_domain:
            domain = "global"

        if domain in self._retry_after:
            retry_after = self._retry_after[domain]
            if time.time() < retry_after:
                wait_time = retry_after - time.time()
                await asyncio.sleep(wait_time)
            del self._retry_after[domain]

        bucket = self._get_bucket(domain)
        lock = self._domain_locks[domain]

        async with lock:
            while True:
                if bucket.consume(tokens):
                    if not self._global_bucket.consume(tokens):
                        bucket.add_tokens(tokens)
                        await asyncio.sleep(0.01)
                        continue
                    return

                wait_time = bucket.get_wait_time(tokens)
                if wait_time > 0:
                    await asyncio.sleep(min(wait_time, 1.0))
                else:
                    await asyncio.sleep(0.01)

    def update_from_response(
        self,
        domain: str,
        status_code: int,
        headers: Dict[str, str],
    ) -> None:
        if not self.config.adaptive:
            return

        if self.config.respect_retry_after and status_code == 429:
            retry_after = headers.get("Retry-After") or headers.get("retry-after")
            if retry_after:
                try:
                    wait_time = float(retry_after)
                    self._retry_after[domain] = time.time() + wait_time
                except ValueError:
                    if retry_after.isdigit():
                        self._retry_after[domain] = time.time() + float(retry_after)

        if self.config.respect_rate_limit_headers:
            rate_limit_remaining = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
            rate_limit_reset = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")
            rate_limit_limit = headers.get("X-RateLimit-Limit") or headers.get("x-ratelimit-limit")

            if rate_limit_remaining is not None and rate_limit_reset is not None:
                try:
                    remaining = int(rate_limit_remaining)
                    reset_time = float(rate_limit_reset)
                    limit = int(rate_limit_limit) if rate_limit_limit else None

                    if remaining <= 1:
                        self._retry_after[domain] = max(
                            self._retry_after.get(domain, 0),
                            reset_time
                        )

                    if limit and remaining > 0:
                        bucket = self._get_bucket(domain)
                        bucket.refill_rate = max(0.1, limit / 60.0)
                        bucket.capacity = max(1, limit // 60)
                except (ValueError, TypeError):
                    pass

    def get_stats(self, domain: str) -> Dict[str, Any]:
        bucket = self._buckets.get(domain)
        if not bucket:
            return {"domain": domain, "available": False}

        return {
            "domain": domain,
            "tokens_available": bucket.tokens,
            "capacity": bucket.capacity,
            "refill_rate": bucket.refill_rate,
            "retry_after": self._retry_after.get(domain, 0),
            "is_limited": domain in self._retry_after and time.time() < self._retry_after[domain],
        }

    def reset_domain(self, domain: str) -> None:
        with self._lock:
            if domain in self._buckets:
                del self._buckets[domain]
            if domain in self._retry_after:
                del self._retry_after[domain]
            if domain in self._rate_limit_headers:
                del self._rate_limit_headers[domain]

    def reset_all(self) -> None:
        with self._lock:
            self._buckets.clear()
            self._retry_after.clear()
            self._rate_limit_headers.clear()
            self._global_bucket = TokenBucket(
                capacity=self.config.burst_allowance,
                tokens=self.config.burst_allowance,
                refill_rate=self.config.requests_per_second,
            )


class AdaptiveRateLimiter(RateLimiter):
    def __init__(self, config: RateLimitConfig):
        super().__init__(config)
        self._latency_history: Dict[str, List[float]] = defaultdict(list)
        self._error_history: Dict[str, List[bool]] = defaultdict(list)
        self._adjustment_interval = 30
        self._last_adjustment = time.time()
        self._min_rate = 0.1
        self._max_rate = config.requests_per_second * 2

    async def acquire(self, domain: str, priority: int = 0, tokens: int = 1) -> None:
        await super().acquire(domain, priority, tokens)
        self._maybe_adjust_rates(domain)

    def record_latency(self, domain: str, latency_ms: float) -> None:
        self._latency_history[domain].append(latency_ms)
        if len(self._latency_history[domain]) > 100:
            self._latency_history[domain] = self._latency_history[domain][-100:]

    def record_error(self, domain: str, is_error: bool) -> None:
        self._error_history[domain].append(is_error)
        if len(self._error_history[domain]) > 100:
            self._error_history[domain] = self._error_history[domain][-100:]

    def _maybe_adjust_rates(self, domain: str) -> None:
        now = time.time()
        if now - self._last_adjustment < self._adjustment_interval:
            return

        self._last_adjustment = now
        bucket = self._buckets.get(domain)
        if not bucket:
            return

        latencies = self._latency_history.get(domain, [])
        errors = self._error_history.get(domain, [])

        if not latencies or not errors:
            return

        avg_latency = sum(latencies) / len(latencies)
        error_rate = sum(errors) / len(errors)

        current_rate = bucket.refill_rate

        if error_rate > 0.1 or avg_latency > 10000:
            new_rate = max(self._min_rate, current_rate * 0.8)
        elif error_rate < 0.01 and avg_latency < 1000:
            new_rate = min(self._max_rate, current_rate * 1.1)
        else:
            new_rate = current_rate

        if abs(new_rate - current_rate) / current_rate > 0.05:
            bucket.refill_rate = new_rate
            bucket.capacity = max(1, int(new_rate * 2))


class DomainRateLimiter:
    def __init__(self, default_config: RateLimitConfig):
        self.default_config = default_config
        self._limiters: Dict[str, RateLimiter] = {}
        self._lock = Lock()

    def get_limiter(self, domain: str) -> RateLimiter:
        with self._lock:
            if domain not in self._limiters:
                self._limiters[domain] = RateLimiter(self.default_config)
            return self._limiters[domain]

    async def acquire(self, domain: str, priority: int = 0, tokens: int = 1) -> None:
        limiter = self.get_limiter(domain)
        await limiter.acquire(domain, priority, tokens)

    def update_from_response(self, domain: str, status_code: int, headers: Dict[str, str]) -> None:
        limiter = self.get_limiter(domain)
        limiter.update_from_response(domain, status_code, headers)

    def get_all_stats(self) -> Dict[str, Dict[str, Any]]:
        with self._lock:
            return {domain: limiter.get_stats(domain) for domain, limiter in self._limiters.items()}


class PriorityRateLimiter:
    def __init__(self, config: RateLimitConfig):
        self.config = config
        self._queues: Dict[int, asyncio.Queue] = defaultdict(asyncio.Queue)
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._limiter = RateLimiter(config)

    async def start(self):
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._process_queues())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def acquire(self, domain: str, priority: int = 0, tokens: int = 1) -> None:
        future = asyncio.Future()
        await self._queues[priority].put((domain, tokens, future))
        await future

    async def _process_queues(self):
        while self._running:
            try:
                for priority in sorted(self._queues.keys(), reverse=True):
                    queue = self._queues[priority]
                    if not queue.empty():
                        domain, tokens, future = await queue.get()
                        try:
                            await self._limiter.acquire(domain, priority, tokens)
                            future.set_result(None)
                        except Exception as e:
                            future.set_exception(e)
                        break
                else:
                    await asyncio.sleep(0.01)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(0.01)


def create_rate_limiter(config: RateLimitConfig) -> RateLimiter:
    if config.adaptive:
        return AdaptiveRateLimiter(config)
    return RateLimiter(config)


@dataclass
class ConnectionPoolConfig:
    """Configuration for connection pool."""
    max_connections: int = 100
    max_keepalive_connections: int = 20
    keepalive_timeout: float = 30.0
    timeout_connect: float = 10.0
    timeout_read: float = 30.0
    timeout_write: float = 30.0
    timeout_pool: float = 5.0
    max_redirects: int = 10
    verify_ssl: bool = True
    use_dns_cache: bool = True
    ttl_dns_cache: int = 300
    limit_per_host: int = 10
    enable_cleanup_closed: bool = True


@dataclass
class CacheConfig:
    """Configuration for response caching."""
    enabled: bool = True
    max_size: int = 1000
    ttl: float = 3600.0  # 1 hour
    max_entry_size: int = 10 * 1024 * 1024  # 10 MB
    cacheable_status_codes: Set[int] = field(default_factory=lambda: {200, 201, 204, 301, 302, 304})
    cacheable_methods: Set[str] = field(default_factory=lambda: {"GET", "HEAD"})
    vary_headers: List[str] = field(default_factory=lambda: ["Accept", "Accept-Encoding", "Authorization"])
    ignored_query_params: Set[str] = field(default_factory=lambda: {"utm_*", "fbclid", "gclid", "ref", "source", "medium", "campaign"})


class LRUCache:
    """Thread-safe LRU cache with TTL support."""
    
    def __init__(self, max_size: int = 1000, ttl: float = 3600.0):
        self.max_size = max_size
        self.ttl = ttl
        self._cache: OrderedDict = OrderedDict()
        self._timestamps: Dict[str, float] = {}
        self._lock = asyncio.Lock()
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}
    
    def _make_key(self, method: str, url: str, headers: Dict[str, str] = None, vary_headers: List[str] = None) -> str:
        """Generate cache key from request."""
        parts = [method.upper(), url]
        if headers and vary_headers:
            vary_data = {k: v for k, v in headers.items() if k in vary_headers}
            if vary_data:
                parts = [f"{k}:{v}" for k, v in sorted(vary_data.items())]
                parts.append("|".join(parts))
        return "|".join(parts)
    
    def _is_expired(self, key: str) -> bool:
        if key not in self._timestamps:
            return True
        return time.time() - self._timestamps[key] > self.ttl
    
    def _evict_expired(self):
        """Remove expired entries."""
        now = time.time()
        expired_keys = [k for k, ts in self._timestamps.items() if now - ts > self.ttl]
        for key in expired_keys:
            self._cache.pop(key, None)
            self._timestamps.pop(key, None)
            self._stats["evictions"] += 1
    
    def _evict_lru(self):
        """Evict least recently used entry."""
        if self._cache:
            key, _ = self._cache.popitem(last=False)
            self._timestamps.pop(key, None)
            self._stats["evictions"] += 1
    
    async def get(self, method: str, url: str, headers: Dict[str, str] = None, vary_headers: List[str] = None) -> Optional[Any]:
        """Get cached response."""
        key = self._make_key(method, url, headers)
        
        async with self._lock:
            self._evict_expired()
            
            if key in self._cache and not self._is_expired(key):
                # Move to end (most recently used)
                value = self._cache.pop(key)
                self._cache[key] = value
                self._stats["hits"] += 1
                return value
            
            self._stats["misses"] += 1
            return None
    
    async def set(self, method: str, url: str, response: Any, headers: Dict[str, str] = None, vary_headers: List[str] = None) -> None:
        """Cache response."""
        key = self._make_key(method, url, headers)
        
        async with self._lock:
            self._evict_expired()
            
            # Check size limit
            import sys
            import json
            try:
                size = len(json.dumps(response).encode())
            except:
                size = 1024  # fallback estimate
            
            if size > 10 * 1024 * 1024:  # 10 MB limit
                return
            
            # Evict LRU if at capacity
            while len(self._cache) >= self.max_size:
                self._evict_lru()
            
            self._cache[key] = response
            self._timestamps[key] = time.time()
    
    async def invalidate(self, method: str = None, url: str = None, pattern: str = None) -> int:
        """Invalidate cache entries."""
        count = 0
        async with self._lock:
            keys_to_remove = []
            for key in self._cache:
                # Parse key
                parts = key.split("|", 2)
                if len(parts) >= 2:
                    method_part = parts[0]
                    url_part = parts[1]
                    
                    match = True
                    if method and method_part.upper() != method.upper():
                        match = False
                    if url and url_part not in url:
                        match = False
                    if pattern and pattern not in url:
                        match = False
                    
                    if match:
                        keys_to_remove.append(key)
            
            for key in keys_to_remove:
                self._cache.pop(key, None)
                self._timestamps.pop(key, None)
                count += 1
            
        return count
    
    async def clear(self):
        """Clear all cache."""
        async with self._lock:
            self._cache.clear()
            self._timestamps.clear()
    
    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "size": len(self._cache),
            "max_size": self.max_size,
            "ttl": self.ttl,
        }
    
    async def close(self):
        await self.clear()


class DistributedRateLimiter:
    """Redis-backed distributed rate limiter."""
    
    def __init__(self, redis_url: str, config: RateLimitConfig):
        self.redis_url = redis_url
        self.config = config
        self._redis: Optional[Any] = None
        self._lua_scripts_loaded = False
    
    async def initialize(self) -> None:
        import redis.asyncio as redis
        self._redis = redis.from_url(self.redis_url, decode_responses=True)
        await self._load_lua_scripts()
    
    async def _load_lua_scripts(self) -> None:
        if self._lua_scripts_loaded:
            return
        
        # Lua script for atomic token bucket consume
        self._consume_script = self._redis.register_script("""
            local key = KEYS[1]
            local capacity = tonumber(ARGV[1])
            local tokens = tonumber(ARGV[2])
            local refill_rate = tonumber(ARGV[3])
            local now = tonumber(ARGV[4])
            
            local bucket = redis.call('HMGET', key, 'tokens', 'last_refill')
            local current_tokens = tonumber(bucket[1])
            local last_refill = tonumber(bucket[2])
            
            if current_tokens == nil then
                current_tokens = capacity
                last_refill = now
            end
            
            local elapsed = now - last_refill
            current_tokens = math.min(capacity, current_tokens + elapsed * refill_rate)
            
            if current_tokens >= tokens then
                current_tokens = current_tokens - tokens
                redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill', now)
                redis.call('EXPIRE', key, 86400)
                return {1, current_tokens}
            else
                redis.call('HMSET', key, 'tokens', current_tokens, 'last_refill', now)
                redis.call('EXPIRE', key, 86400)
                local wait_time = (tokens - current_tokens) / refill_rate
                return {0, wait_time}
            end
        """)
        self._lua_scripts_loaded = True
    
    async def acquire(self, domain: str, priority: int = 0, tokens: int = 1) -> None:
        if not self.config.per_domain:
            domain = "global"
        
        key = f"ratelimit:{domain}"
        capacity = self.config.burst_allowance
        refill_rate = self.config.requests_per_second
        now = time.time()
        
        while True:
            result = await self._consume_script(
                keys=[key],
                args=[capacity, tokens, refill_rate, now]
            )
            success = result[0]
            if success == 1:
                return
            
            wait_time = result[1]
            if wait_time > 0:
                await asyncio.sleep(min(wait_time, 1.0))
            else:
                await asyncio.sleep(0.01)
    
    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            self._redis = None