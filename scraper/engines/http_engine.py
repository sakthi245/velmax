from __future__ import annotations

import asyncio
import hashlib
import json
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Union
from urllib.parse import urljoin, urlparse

import httpx
from parsel import Selector
from selectolax.parser import HTMLParser

from tenacity import (
    AsyncRetrying,
    before_sleep_log,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential_jitter,
)

from .base_v2 import (
    BaseEngineV2,
    BaseHTTPEngineV2,
)
from .interfaces import (
    EngineConfig,
    EngineMetadata,
    EngineCapability,
    HTTPRequest,
    HTTPResponse,
)
from ..config.schemas import EngineType
from .session_manager import SessionManager
from ..utils.rate_limiter import RateLimiter, RateLimitConfig
from ..utils.retry import RetryPolicy, create_retry_policy
from ..utils.observability import get_logger, MetricsCollector
from ..utils.dedup import DeduplicationManager, DedupConfig
from ..utils.http_cache import HTTPCache, HTTPCacheConfig
from ..config.schemas import BrowserType


@dataclass
class HTTPEngineConfig:
    enabled: bool = True
    client_type: str = "httpx"
    parser: str = "selectolax"
    follow_links: bool = False
    link_selectors: List[str] = field(default_factory=lambda: ["a[href]"])
    pagination_selectors: List[str] = field(default_factory=lambda: [
        "a[rel=next]", ".pagination a", ".next a", "a:contains('Next')"
    ])
    sitemap_enabled: bool = True
    sitemap_max_urls: int = 10000
    http_cache_enabled: bool = True
    http_cache_dir: Optional[Path] = None
    http_cache_ttl: int = 86400
    http_cache_max_size: int = 1_000_000_000
    streaming_threshold: int = 1_000_000
    autothrottle_enabled: bool = True
    autothrottle_start_delay: float = 1.0
    autothrottle_max_delay: float = 60.0
    autothrottle_target_concurrency: float = 2.0
    default_headers: Dict[str, str] = field(default_factory=lambda: {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })


class HTTPEngine(BaseHTTPEngineV2):
    metadata = EngineMetadata(
        name="http",
        engine_type=EngineType.HTTP,
        capabilities={
            EngineCapability.LARGE_CRAWL,
            EngineCapability.PROXY_ROTATION,
            EngineCapability.SESSION_PERSISTENCE,
        },
        max_concurrent=16,
        avg_latency_ms=2000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        retry_policy: Optional[RetryPolicy] = None,
        session_manager: Optional[SessionManager] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._client: Optional[httpx.AsyncClient] = None
        self._engine_config = HTTPEngineConfig()
        self._http_cache: Optional[HTTPCache] = None
        self._dedup: Optional[DeduplicationManager] = None
        self._autothrottle_delays: Dict[str, float] = {}
        self._domain_concurrency: Dict[str, asyncio.Semaphore] = {}

    async def _initialize_impl(self, config: EngineConfig) -> None:
        self._engine_config = HTTPEngineConfig(**config.config.get("http_engine", {}))

        # Initialize HTTP client with connection pooling
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=30.0,
            pool=5.0,
        )
        self._client = httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=True,
            http2=True,
        )

        # Initialize HTTP cache
        if self._engine_config.http_cache_enabled:
            cache_config = HTTPCacheConfig(
                cache_dir=self._engine_config.http_cache_dir,
                ttl=self._engine_config.http_cache_ttl,
                max_size=self._engine_config.http_cache_max_size,
            )
            self._http_cache = HTTPCache(cache_config)
            await self._http_cache.initialize()

        # Initialize deduplication
        self._dedup = DeduplicationManager(DedupConfig(
            strategy="url_content",
            persistent_storage=True,
        ))

        # Rate limiter
        rate_limit_cfg = config.config.get("rate_limit", {})
        if rate_limit_cfg:
            self.rate_limiter = RateLimiter(RateLimitConfig(**rate_limit_cfg))

        # Retry policy
        retry_cfg = config.config.get("retry_policy", {})
        if retry_cfg:
            self.retry_policy = RetryPolicy(**retry_cfg)

        self.logger.info("HTTP engine initialized", parser=self._engine_config.parser)

    async def _shutdown_impl(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._http_cache:
            await self._http_cache.close()

    def _health_check_impl(self) -> bool:
        return self._client is not None and not self._client.is_closed

    async def _create_client(self) -> httpx.AsyncClient:
        """Create HTTP client with connection pooling."""
        limits = httpx.Limits(
            max_keepalive_connections=20,
            max_connections=100,
            keepalive_expiry=30.0,
        )
        timeout = httpx.Timeout(
            connect=10.0,
            read=30.0,
            write=30.0,
            pool=5.0,
        )
        return httpx.AsyncClient(
            limits=limits,
            timeout=timeout,
            follow_redirects=True,
            http2=True,
        )

    async def _fetch_impl(self, request: HTTPRequest) -> HTTPResponse:
        """Internal fetch implementation used by base class."""
        start_time = time.time()
        try:
            response = await self._client.request(
                method=request.method,
                url=request.url,
                headers=request.headers,
                params=request.params,
                data=request.data,
                json=request.json,
                cookies=request.cookies,
                auth=request.auth,
                timeout=request.timeout,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            return HTTPResponse(
                url=str(response.url),
                status_code=response.status_code,
                headers=dict(response.headers),
                content=response.content,
                text=response.text,
                encoding=response.encoding or "utf-8",
                cookies=dict(response.cookies),
                elapsed_ms=elapsed_ms,
            )

        except httpx.TimeoutException as e:
            raise TimeoutError(f"Request timeout: {e}")
        except httpx.HTTPStatusError as e:
            raise
        except Exception as e:
            raise

    async def fetch(self, request: HTTPRequest) -> HTTPResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        # Session management
        session = None
        if self.session_manager:
            session = await self.session_manager.get_session(
                self._extract_domain(request.url), self._config.name
            )
            if session:
                request.cookies.update(session.cookies)
                request.headers.update(session.headers)

        # Apply default headers
        headers = {**self._engine_config.default_headers, **request.headers}

        # Check cache first
        cache_key = None
        if self._http_cache and request.method == "GET":
            cache_key = self._http_cache.make_key(request.url, headers)
            cached = await self._http_cache.get(cache_key)
            if cached:
                return HTTPResponse(
                    url=cached["url"],
                    status_code=cached["status_code"],
                    headers=cached["headers"],
                    content=cached["content"],
                    text=cached["text"],
                    encoding=cached.get("encoding", "utf-8"),
                    elapsed_ms=0,
                    from_cache=True,
                )

        # Deduplication check
        if self._dedup and self._dedup.is_duplicate(request.url):
            self.logger.debug("URL already seen, skipping", url=request.url)

        domain = self._extract_domain(request.url)

        # Get or create domain semaphore for concurrency control
        if domain not in self._domain_concurrency:
            # Access _config from base class (EngineConfig) or use default
            max_per_domain = 3
            if self._config and hasattr(self._config, 'config') and 'concurrency' in self._config.config:
                max_per_domain = self._config.config['concurrency'].get('max_concurrent_per_domain', 3)
            self._domain_concurrency[domain] = asyncio.Semaphore(max_per_domain)

        async with self._domain_concurrency[domain]:
            async with self.request_context(request.url, domain):
                response = await self._execute_with_retry_and_throttle(request, headers)

        # Handle empty responses
        if not response.content and response.status_code == 200:
            self.logger.warning("Empty response received", url=request.url)
            response = HTTPResponse(
                url=request.url,
                status_code=204,
                headers=response.headers,
                content=b"",
                text="",
                error="Empty response body",
                elapsed_ms=response.elapsed_ms,
            )

        # Handle encoding issues
        if response.encoding and response.encoding.lower() not in ('utf-8', 'utf8', 'ascii', 'latin-1', 'iso-8859-1'):
            self.logger.debug("Non-standard encoding detected", encoding=response.encoding, url=request.url)

        # Handle excessive redirects
        if len(response.history) > 10:
            self.logger.warning("Excessive redirects detected", url=request.url, redirect_count=len(response.history))

        # Update session
        if self.session_manager and session:
            await self.session_manager.update_session(session.session_id, {
                "cookies": dict(response.cookies),
                "last_used": datetime.utcnow().isoformat(),
            })

        # Store in cache
        if self._http_cache and cache_key and response.status_code == 200:
            await self._http_cache.set(cache_key, {
                "url": response.url,
                "status_code": response.status_code,
                "headers": dict(response.headers),
                "content": response.content,
                "text": response.text,
                "encoding": response.encoding,
            })

        return response

    async def _execute_with_retry_and_throttle(
        self, request: HTTPRequest, headers: Dict[str, str]
    ) -> HTTPResponse:
        domain = self._extract_domain(request.url)

        # Apply autothrottle delay
        if self._engine_config.autothrottle_enabled and domain in self._autothrottle_delays:
            delay = self._autothrottle_delays[domain]
            if delay > 0:
                await asyncio.sleep(delay)

        retryer = self._create_retryer()

        async def _fetch():
            start = time.time()
            try:
                response = await self._client.request(
                    method=request.method,
                    url=request.url,
                    headers=headers,
                    params=request.params,
                    data=request.data,
                    json=request.json,
                    cookies=request.cookies,
                    auth=request.auth,
                    timeout=request.timeout,
                )

                elapsed_ms = int((time.time() - start) * 1000)

                # Update autothrottle based on response
                if self._engine_config.autothrottle_enabled:
                    self._update_autothrottle(domain, response.status_code, elapsed_ms)

                return HTTPResponse(
                    url=str(response.url),
                    status_code=response.status_code,
                    headers=dict(response.headers),
                    content=response.content,
                    text=response.text,
                    encoding=response.encoding or "utf-8",
                    cookies=dict(response.cookies),
                    elapsed_ms=elapsed_ms,
                )

            except httpx.TimeoutException as e:
                raise TimeoutError(f"Request timeout: {e}")
            except httpx.HTTPStatusError as e:
                # Re-raise for retry logic
                raise
            except Exception as e:
                raise

        try:
            return await retryer(_fetch)
        except Exception as e:
            elapsed_ms = 0
            return HTTPResponse(
                url=request.url,
                status_code=0,
                headers={},
                content=b"",
                text="",
                error=str(e),
                elapsed_ms=elapsed_ms,
            )

    def _update_autothrottle(self, domain: str, status_code: int, latency_ms: int):
        """Update autothrottle delay based on response."""
        current_delay = self._autothrottle_delays.get(domain, self._engine_config.autothrottle_start_delay)

        if status_code >= 500 or status_code == 429:
            # Increase delay
            new_delay = min(
                current_delay * 1.5,
                self._engine_config.autothrottle_max_delay
            )
        elif status_code == 200 and latency_ms < 1000:
            # Decrease delay slightly
            new_delay = max(
                current_delay * 0.9,
                self._engine_config.autothrottle_start_delay
            )
        else:
            new_delay = current_delay

        self._autothrottle_delays[domain] = new_delay

    async def fetch_many(self, requests: List[HTTPRequest]) -> List[HTTPResponse]:
        semaphore = asyncio.Semaphore(self.metadata.max_concurrent)

        async def fetch_one(req: HTTPRequest) -> HTTPResponse:
            async with semaphore:
                return await self.fetch(req)

        return await asyncio.gather(*[fetch_one(req) for req in requests])

    async def crawl_sitemap(self, sitemap_url: str) -> AsyncIterator[HTTPResponse]:
        response = await self.fetch(HTTPRequest(url=sitemap_url))
        if response.error or response.status_code != 200:
            return

        urls = self._parse_sitemap(response.content)
        count = 0
        for url in urls:
            if count >= self._engine_config.sitemap_max_urls:
                break
            yield await self.fetch(HTTPRequest(url=url))
            count += 1

    def _parse_sitemap(self, content: bytes) -> List[str]:
        urls = []
        if not content:
            self.logger.warning("Empty sitemap content")
            return urls
            
        try:
            # Handle encoding issues
            if isinstance(content, bytes):
                # Try to detect encoding
                try:
                    content_str = content.decode('utf-8')
                except UnicodeDecodeError:
                    try:
                        content_str = content.decode('latin-1')
                    except UnicodeDecodeError:
                        content_str = content.decode('utf-8', errors='replace')
            else:
                content_str = content
                
            root = ET.fromstring(content_str.encode('utf-8') if isinstance(content_str, str) else content_str)
            namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

            # Handle sitemap index
            for sitemap in root.findall(".//sm:sitemap/sm:loc", namespace) or root.findall(".//sitemap/loc"):
                url = sitemap.text.strip()
                if url:
                    urls.append(url)

            # Handle urlset
            for url_elem in root.findall(".//sm:url/sm:loc", namespace) or root.findall(".//url/loc"):
                url = url_elem.text.strip()
                if url:
                    urls.append(url)

        except ET.ParseError as e:
            self.logger.warning("Failed to parse sitemap", error=str(e))
        except Exception as e:
            self.logger.error("Unexpected error parsing sitemap", error=str(e))

        return urls

    async def intercept_apis(self, url: str, duration_ms: int = 10000) -> List[Any]:
        # HTTP engine doesn't intercept APIs (requires browser)
        return []

    async def check_robots_txt(self, url: str, user_agent: str) -> bool:
        from urllib.parse import urlparse
        from urllib.robotparser import RobotFileParser

        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        try:
            response = await self.fetch(HTTPRequest(url=robots_url))
            if response.error or response.status_code != 200:
                return True

            rp = RobotFileParser()
            rp.parse(response.text.splitlines())
            return rp.can_fetch(user_agent, url)
        except Exception:
            return True

    def _extract_domain(self, url: str) -> str:
        return urlparse(url).netloc.lower()

    def _create_retryer(self):
        return AsyncRetrying(
            stop=stop_after_attempt(self.retry_policy.max_attempts),
            wait=wait_exponential_jitter(
                initial=self.retry_policy.base_delay,
                max=self.retry_policy.max_delay,
                jitter=self.retry_policy.jitter_factor,
            ),
            retry=(
                retry_if_exception_type(tuple(self.retry_policy.get_retryable_exceptions()))
                | retry_if_result(lambda r: self._is_retryable_response(r))
            ),
            before_sleep=before_sleep_log(self.logger, "WARNING"),
            reraise=True,
        )

    def _is_retryable_response(self, response: Any) -> bool:
        if hasattr(response, "status_code"):
            return response.status_code in self.retry_policy.retryable_status_codes
        if hasattr(response, "error") and response.error:
            return any(
                pattern in response.error.lower()
                for pattern in self.retry_policy.retryable_error_patterns
            )
        return False

    async def get_stats(self) -> Dict[str, Any]:
        return {
            "engine": self.metadata.name,
            "active_domains": len(self._autothrottle_delays),
            "autothrottle_delays": self._autothrottle_delays,
            "cache_stats": await self._http_cache.get_stats() if self._http_cache else {},
        }


async def create_http_engine(config: EngineConfig) -> HTTPEngine:
    """Factory function to create HTTP engine."""
    engine = HTTPEngine()
    await engine.initialize(config)
    return engine