from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional, Set, Type, TypeVar
from uuid import uuid4

from tenacity import (
    AsyncRetrying,
    RetryError,
    before_sleep_log,
    stop_after_attempt,
    wait_exponential_jitter,
    retry_if_exception_type,
    retry_if_result,
)

from .interfaces import (
    BaseEngine as BaseEngineProtocol,
    EngineConfig,
    EngineMetadata,
    HTTPRequest,
    HTTPResponse,
    BrowserRequest,
    BrowserResponse,
    InteractionSequence,
    InteractionResult,
    APIEndpoint,
    CrawlStrategy,
    PageResult,
)
from .browser_pool import AdaptiveBrowserPool
from .session_manager import SessionManager
from ..utils.rate_limiter import RateLimiter, RateLimitConfig
from ..utils.retry import RetryPolicy, create_retry_policy
from ..utils.observability import get_logger, get_tracer, MetricsCollector
from ..config.schemas import TimeoutConfig, ProxyConfig, EngineCapability, ObservabilityConfig


T = TypeVar("T", bound="BaseEngineV2")


@dataclass
class EngineMetrics:
    engine_name: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    last_request_time: Optional[datetime] = None
    circuit_breaker_state: str = "closed"
    consecutive_failures: int = 0
    consecutive_successes: int = 0
    last_error: Optional[str] = None
    errors_by_type: Dict[str, int] = field(default_factory=dict)

    def record_request(self, success: bool, latency_ms: int, error: Optional[str] = None):
        self.total_requests += 1
        self.total_latency_ms += latency_ms
        self.avg_latency_ms = self.total_latency_ms / self.total_requests
        self.last_request_time = datetime.utcnow()

        if success:
            self.successful_requests += 1
            self.consecutive_successes += 1
            self.consecutive_failures = 0
        else:
            self.failed_requests += 1
            self.consecutive_failures += 1
            self.consecutive_successes = 0
            self.last_error = error
            if error:
                self.errors_by_type[error] = self.errors_by_type.get(error, 0) + 1

        self.success_rate = self.successful_requests / self.total_requests if self.total_requests > 0 else 0.0


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 3,
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        self.state = "closed"
        self.failure_count = 0
        self.last_failure_time: Optional[float] = None
        self.half_open_calls = 0
        self._lock = asyncio.Lock()

    async def call(self, coro_func, *args, **kwargs):
        async with self._lock:
            if self.state == "open":
                if time.time() - self.last_failure_time > self.recovery_timeout:
                    self.state = "half_open"
                    self.half_open_calls = 0
                else:
                    raise RuntimeError("Circuit breaker OPEN")

            if self.state == "half_open":
                if self.half_open_calls >= self.half_open_max_calls:
                    raise RuntimeError("Circuit breaker HALF_OPEN limit")
                self.half_open_calls += 1

        try:
            result = await coro_func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    async def _on_success(self):
        async with self._lock:
            self.failure_count = 0
            if self.state != "closed":
                self.state = "closed"

    async def _on_failure(self):
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.failure_count >= self.failure_threshold:
                self.state = "open"

    def get_state(self) -> str:
        return self.state


class BaseEngineV2(ABC):
    metadata: EngineMetadata

    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        retry_policy: Optional[RetryPolicy] = None,
        session_manager: Optional[SessionManager] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        observability_config: Optional[ObservabilityConfig] = None,
    ):
        self._initialized = False
        self._config: Optional[EngineConfig] = None
        self._engine_config: Dict[str, Any] = {}

        self.rate_limiter = RateLimiter(rate_limit_config or RateLimitConfig())
        self.retry_policy = retry_policy or RetryPolicy()
        self.session_manager = session_manager
        self.circuit_breaker = CircuitBreaker(**(circuit_breaker_config or {}))
        self.metrics = EngineMetrics(self.metadata.name)

        self.logger = get_logger(f"engine.{self.metadata.name}")
        self.tracer = get_tracer(f"engine.{self.metadata.name}")
        self.metrics_collector = MetricsCollector(self.metadata.name, observability_config or ObservabilityConfig())

        self._health_check_cache: Optional[bool] = None
        self._health_check_time: Optional[datetime] = None
        self._health_check_ttl = 30

    @abstractmethod
    async def _initialize_impl(self, config: EngineConfig) -> None:
        pass

    @abstractmethod
    async def _shutdown_impl(self) -> None:
        pass

    @abstractmethod
    def _health_check_impl(self) -> bool:
        pass

    async def initialize(self, config: EngineConfig) -> None:
        if self._initialized:
            return

        self._config = config
        self._engine_config = config.config

        rate_limit_cfg = self._engine_config.get("rate_limit", {})
        if rate_limit_cfg:
            self.rate_limiter = RateLimiter(RateLimitConfig(**rate_limit_cfg))

        retry_cfg = self._engine_config.get("retry_policy", {})
        if retry_cfg:
            self.retry_policy = RetryPolicy(**retry_cfg)

        cb_cfg = self._engine_config.get("circuit_breaker", {})
        if cb_cfg:
            self.circuit_breaker = CircuitBreaker(**cb_cfg)

        await self._initialize_impl(config)
        self._initialized = True
        self.logger.info(f"Engine {self.metadata.name} initialized")

    async def shutdown(self) -> None:
        if not self._initialized:
            return

        await self._shutdown_impl()
        self._initialized = False
        self.logger.info(f"Engine {self.metadata.name} shutdown")

    def health_check(self) -> bool:
        now = datetime.utcnow()
        if (
            self._health_check_cache is not None
            and self._health_check_time
            and (now - self._health_check_time).total_seconds() < self._health_check_ttl
        ):
            return self._health_check_cache

        result = self._health_check_impl()
        self._health_check_cache = result
        self._health_check_time = now
        return result

    def supports(self, capability: EngineCapability) -> bool:
        return capability in self.metadata.capabilities

    def requires_external_service(self) -> bool:
        return self.metadata.requires_external_service

    def get_config(self) -> Optional[EngineConfig]:
        return self._config

    def is_initialized(self) -> bool:
        return self._initialized

    def get_metrics(self) -> EngineMetrics:
        return self.metrics

    def get_circuit_breaker_state(self) -> str:
        return self.circuit_breaker.get_state()

    @asynccontextmanager
    async def request_context(
        self,
        url: str,
        domain: Optional[str] = None,
        priority: int = 0,
    ):
        domain = domain or self._extract_domain(url)
        await self.rate_limiter.acquire(domain, priority)
        start_time = time.time()
        success = False
        error = None
        try:
            yield
            success = True
        except Exception as e:
            error = str(e)
            raise
        finally:
            latency_ms = int((time.time() - start_time) * 1000)
            self.metrics.record_request(success, latency_ms, error)
            self.metrics_collector.record_request(
                self.metadata.name, success, latency_ms, domain
            )

    def _extract_domain(self, url: str) -> str:
        from urllib.parse import urlparse
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

    async def execute_with_retry(self, coro_func, *args, **kwargs):
        retryer = self._create_retryer()
        try:
            return await retryer(coro_func, *args, **kwargs)
        except RetryError as e:
            raise e.last_attempt.exception()

    async def execute_with_circuit_breaker(self, coro_func, *args, **kwargs):
        return await self.circuit_breaker.call(coro_func, *args, **kwargs)

    async def execute_protected(self, coro_func, *args, **kwargs):
        return await self.execute_with_circuit_breaker(
            lambda: self.execute_with_retry(coro_func, *args, **kwargs)
        )


class BaseHTTPEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._client = None
        self._cookie_jar = None

    @abstractmethod
    async def _create_client(self) -> Any:
        pass

    @abstractmethod
    async def _fetch_impl(self, request: HTTPRequest) -> HTTPResponse:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        self._client = await self._create_client()
        if self.session_manager:
            self._cookie_jar = await self.session_manager.get_cookie_jar(config.name)

    async def _shutdown_impl(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _health_check_impl(self) -> bool:
        return self._client is not None

    async def fetch(self, request: HTTPRequest) -> HTTPResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        session = None
        if self.session_manager:
            session = await self.session_manager.get_session(
                self._extract_domain(request.url), self._config.name
            )
            if session:
                request.cookies.update(session.cookies)
                request.headers.update(session.headers)

        async with self.request_context(request.url):
            response = await self.execute_protected(self._fetch_impl, request)

        if self.session_manager and session:
            await self.session_manager.update_session(session.session_id, {
                "cookies": dict(response.cookies),
                "last_used": datetime.utcnow().isoformat(),
            })

        return response

    async def fetch_many(self, requests: List[HTTPRequest]) -> List[HTTPResponse]:
        semaphore = asyncio.Semaphore(self.metadata.max_concurrent)

        async def fetch_one(req: HTTPRequest) -> HTTPResponse:
            async with semaphore:
                return await self.fetch(req)

        return await asyncio.gather(*[fetch_one(req) for req in requests])

    async def crawl_sitemap(self, sitemap_url: str) -> AsyncIterator[HTTPResponse]:
        response = await self.fetch(HTTPRequest(url=sitemap_url))
        if response.error:
            return

        import xml.etree.ElementTree as ET
        root = ET.fromstring(response.content)
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        for url_elem in root.findall(".//sm:url/sm:loc", namespace) or root.findall(".//url/loc"):
            url = url_elem.text.strip()
            if url:
                yield await self.fetch(HTTPRequest(url=url))

    async def intercept_apis(self, url: str, duration_ms: int = 10000) -> List[APIEndpoint]:
        return []

    async def check_robots_txt(self, url: str, user_agent: str) -> bool:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"

        try:
            response = await self.fetch(HTTPRequest(url=robots_url))
            if response.error or response.status_code != 200:
                return True

            from urllib.robotparser import RobotFileParser
            rp = RobotFileParser()
            rp.parse(response.text.splitlines())
            return rp.can_fetch(user_agent, url)
        except Exception:
            return True


class BaseBrowserEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._browser = None
        self._pool: Optional[AdaptiveBrowserPool] = None
        self._browser_config: Dict[str, Any] = {}

    @abstractmethod
    async def _launch_browser(self) -> Any:
        pass

    @abstractmethod
    async def _create_context(self, config: Dict[str, Any]) -> Any:
        pass

    @abstractmethod
    async def _navigate_impl(self, context: Any, request: BrowserRequest) -> BrowserResponse:
        pass

    @abstractmethod
    async def _interact_impl(self, context: Any, sequence: InteractionSequence) -> InteractionResult:
        pass

    @abstractmethod
    async def _execute_cdp_impl(self, context: Any, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    async def _evaluate_impl(self, context: Any, script: str, await_promise: bool) -> Any:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        self._browser = await self._launch_browser()
        self._browser_config = self._engine_config.get("browser_engine", {})

        # Create adaptive browser pool
        browser_engine_config = self.config.browser_engine if self.config else None
        if browser_engine_config is None:
            from ..config.schemas import BrowserEngineConfig
            browser_engine_config = BrowserEngineConfig(**self._browser_config)

        self._pool = create_adaptive_pool(
            config=browser_engine_config,
            create_context_fn=self._create_context,
            engine_name=self.metadata.name,
        )
        await self._pool.start()

        self.logger.info(f"Browser engine {self.metadata.name} initialized with adaptive pool")

    async def _shutdown_impl(self) -> None:
        if self._pool:
            await self._pool.stop()
            self._pool = None

        if self._browser:
            await self._browser.close()
            self._browser = None

    def _health_check_impl(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def _get_context(self) -> Any:
        """Get a context from the adaptive pool."""
        if not self._pool:
            raise RuntimeError("Browser pool not initialized")
        return await self._pool.get_context()

    async def _return_context(self, context: Any) -> None:
        """Return context to the adaptive pool."""
        if self._pool:
            await self._pool.return_context(context)

    async def navigate(self, request: BrowserRequest) -> BrowserResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        context = await self._get_context()

        try:
            async with self.request_context(request.url):
                response = await self.execute_protected(self._navigate_impl, context, request)
            return response
        finally:
            await self._return_context(context)

    async def interact(self, sequence: InteractionSequence) -> InteractionResult:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        context = await self._get_context()

        try:
            return await self.execute_protected(self._interact_impl, context, sequence)
        finally:
            await self._return_context(context)

    async def execute_cdp(self, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        context = await self._get_context()

        try:
            return await self.execute_protected(self._execute_cdp_impl, context, commands)
        finally:
            await self._return_context(context)

    async def evaluate(self, script: str, await_promise: bool = True) -> Any:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        context = await self._get_context()

        try:
            return await self.execute_protected(self._evaluate_impl, context, script, await_promise)
        finally:
            await self._return_context(context)

    def create_context(self, config: Dict[str, Any]) -> "BrowserContextWrapper":
        return BrowserContextWrapper(self, config)

    async def get_page_count(self) -> int:
        if self._pool:
            metrics = await self._pool.get_metrics()
            return sum(c.get("pages_processed", 0) for c in metrics.get("contexts", {}).values())
        return 0

    async def get_pool_metrics(self) -> Dict[str, Any]:
        """Get adaptive pool metrics."""
        if self._pool:
            return await self._pool.get_metrics()
        return {}

    async def recycle_context(self, context_id: str) -> None:
        """Manually trigger context recycle."""
        if self._pool:
            await self._pool._recycle_context(context_id, "manual")

    async def scrape(self, request: BrowserRequest) -> BrowserResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        return await self.execute_protected(self._scrape_impl, request)

    async def crawl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        return await self.execute_protected(self._crawl_impl, urls, config)



class BrowserContextWrapper:
    def __init__(self, engine: BaseBrowserEngineV2, config: Dict[str, Any]):
        self._engine = engine
        self._config = config
        self._context = None
        self._context_id = None

    @property
    def context_id(self) -> str:
        if self._context_id is None:
            self._context_id = str(uuid4())
        return self._context_id

    @property
    def page_count(self) -> int:
        return 0

    async def _ensure_context(self):
        if self._context is None:
            self._context = await self._engine._create_context(self._config)

    async def navigate(self, request: BrowserRequest) -> BrowserResponse:
        await self._ensure_context()
        return await self._engine._navigate_impl(self._context, request)

    async def interact(self, sequence: InteractionSequence) -> InteractionResult:
        await self._ensure_context()
        return await self._engine._interact_impl(self._context, sequence)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None

    def is_healthy(self) -> bool:
        return self._context is not None


class BaseManagedEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    @abstractmethod
    async def _crawl_impl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]:
        pass

    @abstractmethod
    async def _add_urls_impl(self, urls: List[str], priority: int) -> None:
        pass

    @abstractmethod
    async def _get_statistics_impl(self) -> Dict[str, Any]:
        pass

    @abstractmethod
    async def _pause_impl(self) -> None:
        pass

    @abstractmethod
    async def _resume_impl(self) -> None:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        pass

    async def _shutdown_impl(self) -> None:
        pass

    def _health_check_impl(self) -> bool:
        return True

    async def crawl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        async for result in self._crawl_impl(strategy):
            yield result

    async def add_urls(self, urls: List[str], priority: int = 0) -> None:
        await self._add_urls_impl(urls, priority)

    async def get_statistics(self) -> Dict[str, Any]:
        return await self._get_statistics_impl()

    async def pause(self) -> None:
        await self._pause_impl()

    async def resume(self) -> None:
        await self._resume_impl()


class BaseCloudEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    @abstractmethod
    async def _scrape_impl(self, request: BrowserRequest) -> BrowserResponse:
        pass

    @abstractmethod
    async def _crawl_impl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]:
        pass

    @abstractmethod
    async def _extract_llm_impl(
        self, content: str, schema: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        pass

    async def _shutdown_impl(self) -> None:
        pass

    def _health_check_impl(self) -> bool:
        return True

    async def scrape(self, request: BrowserRequest) -> BrowserResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        return await self.execute_protected(self._scrape_impl, request)

    async def crawl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        return await self.execute_protected(self._crawl_impl, urls, config)

    async def extract_with_llm(
        self, content: str, schema: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        return await self._extract_llm_impl(content, schema, prompt)


class BaseAPIEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mock_mode = False
        self._mock_har = None

    @abstractmethod
    async def _call_impl(
        self, endpoint: APIEndpoint, auth: Optional[Dict[str, Any]]
    ) -> APIEndpoint:
        pass

    @abstractmethod
    async def _discover_endpoints_impl(self, url: str) -> List[APIEndpoint]:
        pass

    @abstractmethod
    async def _intercept_network_impl(self, url: str, duration_ms: int) -> List[APIEndpoint]:
        pass

    @abstractmethod
    async def _replay_request_impl(self, endpoint: APIEndpoint) -> APIEndpoint:
        pass

    @abstractmethod
    async def _refresh_token_impl(self, auth_config: Dict[str, Any]) -> Dict[str, Any]:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        pass

    async def _shutdown_impl(self) -> None:
        pass

    def _health_check_impl(self) -> bool:
        return True

    async def call(
        self, endpoint: APIEndpoint, auth: Optional[Dict[str, Any]] = None
    ) -> APIEndpoint:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")
        if self._mock_mode and self._mock_har:
            return await self._replay_from_har(endpoint)
        return await self.execute_protected(self._call_impl, endpoint, auth)

    async def discover_endpoints(self, url: str) -> List[APIEndpoint]:
        return await self._discover_endpoints_impl(url)

    async def intercept_network(self, url: str, duration_ms: int) -> List[APIEndpoint]:
        return await self._intercept_network_impl(url, duration_ms)

    async def replay_request(self, endpoint: APIEndpoint) -> APIEndpoint:
        return await self._replay_request_impl(endpoint)

    async def refresh_token(self, auth_config: Dict[str, Any]) -> Dict[str, Any]:
        return await self._refresh_token_impl(auth_config)

    def enable_mock_mode(self, har_file: str) -> None:
        self._mock_mode = True
        import json
        with open(har_file) as f:
            self._mock_har = json.load(f)

    def disable_mock_mode(self) -> None:
        self._mock_mode = False
        self._mock_har = None

    async def _replay_from_har(self, endpoint: APIEndpoint) -> APIEndpoint:
        if not self._mock_har:
            return endpoint

        for entry in self._mock_har.get("log", {}).get("entries", []):
            request = entry.get("request", {})
            if request.get("url") == endpoint.url and request.get("method") == endpoint.method:
                response = entry.get("response", {})
                endpoint.response_status = response.get("status", 0)
                endpoint.response_headers = {
                    h["name"]: h["value"] for h in response.get("headers", [])
                }
                content = response.get("content", {})
                endpoint.response_body = content.get("text")
                break
        return endpoint


class BaseHybridEngineV2(BaseEngineV2):
    metadata: EngineMetadata

    def __init__(self, *args, engines: Dict[str, BaseEngineV2] = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._engines = engines or {}

    @abstractmethod
    async def _coordinate_engines_impl(
        self, strategy: CrawlStrategy, engine_assignments: Dict[str, str]
    ) -> AsyncIterator[PageResult]:
        pass

    async def _initialize_impl(self, config: EngineConfig) -> None:
        for engine in self._engines.values():
            await engine.initialize(config)

    async def _shutdown_impl(self) -> None:
        for engine in self._engines.values():
            await engine.shutdown()

    def _health_check_impl(self) -> bool:
        return all(e.health_check() for e in self._engines.values())

    async def crawl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        engine_assignments = self._assign_engines(strategy)
        async for result in self._coordinate_engines_impl(strategy, engine_assignments):
            yield result

    def _assign_engines(self, strategy: CrawlStrategy) -> Dict[str, str]:
        assignments = {}
        for page_type in strategy.page_type_selectors:
            if page_type == "list":
                assignments[page_type] = "http"
            elif page_type == "detail":
                assignments[page_type] = "browser"
            elif page_type == "api":
                assignments[page_type] = "api"
            else:
                assignments[page_type] = "http"
        return assignments