from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Protocol, Set, Union
from datetime import datetime

from ..config.schemas import EngineCapability, EngineType

__all__ = [
    "EngineCapability",
    "EngineType",
    "EngineMetadata",
    "HTTPRequest",
    "HTTPResponse",
    "BrowserRequest",
    "BrowserResponse",
    "InteractionStep",
    "InteractionSequence",
    "InteractionResult",
    "APIEndpoint",
    "CrawlStrategy",
    "PageResult",
    "EngineConfig",
    "HTTPEngine",
    "BrowserEngine",
    "BrowserContext",
    "ManagedEngine",
    "CloudEngine",
    "APIEngine",
    "HybridEngine",
    "BaseEngine",
    "EngineFactory",
]


@dataclass
class EngineMetadata:
    name: str
    engine_type: str
    capabilities: Set[EngineCapability] = field(default_factory=set)
    max_concurrent: int = 5
    avg_latency_ms: int = 5000
    requires_external_service: bool = False
    cost_per_1k_pages: float = 0.0
    version: str = "1.0.0"
    description: str = ""
    supported_domains: List[str] = field(default_factory=list)
    unsupported_domains: List[str] = field(default_factory=list)


@dataclass
class HTTPRequest:
    url: str
    method: str = "GET"
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    params: Dict[str, Any] = field(default_factory=dict)
    data: Any = None
    json: Any = None
    timeout: float = 30.0
    follow_redirects: bool = True
    max_redirects: int = 10
    proxy: Optional[str] = None
    auth: Optional[tuple] = None
    stream: bool = False
    verify_ssl: bool = True


@dataclass
class HTTPResponse:
    url: str
    status_code: int
    headers: Dict[str, str]
    content: bytes
    text: str
    encoding: str = "utf-8"
    cookies: Dict[str, str] = field(default_factory=dict)
    history: List["HTTPResponse"] = field(default_factory=list)
    elapsed_ms: int = 0
    request: Optional[HTTPRequest] = None
    error: Optional[str] = None
    from_cache: bool = False


@dataclass
class BrowserRequest:
    url: str
    wait_until: str = "networkidle"
    wait_for_selector: Optional[str] = None
    wait_for_function: Optional[str] = None
    wait_for_timeout: Optional[int] = None
    viewport: Optional[Dict[str, Any]] = None
    user_agent: Optional[str] = None
    headers: Dict[str, str] = field(default_factory=dict)
    cookies: Dict[str, str] = field(default_factory=dict)
    proxy: Optional[str] = None
    timeout: int = 60000
    pagination_timeout: int = 60000
    ignore_https_errors: bool = True
    java_script_enabled: bool = True
    extra_headers: Dict[str, str] = field(default_factory=dict)
    geolocation: Optional[Dict[str, float]] = None
    permissions: List[str] = field(default_factory=list)
    color_scheme: str = "light"
    locale: str = "en-US"
    timezone_id: str = "UTC"


@dataclass
class BrowserResponse:
    url: str
    status_code: int = 200
    title: str = ""
    html: str = ""
    text: str = ""
    markdown: str = ""
    screenshot: Optional[bytes] = None
    pdf: Optional[bytes] = None
    har: Optional[Dict[str, Any]] = None
    console_logs: List[Dict[str, Any]] = field(default_factory=list)
    network_requests: List[Dict[str, Any]] = field(default_factory=list)
    cookies: Dict[str, str] = field(default_factory=dict)
    local_storage: Dict[str, str] = field(default_factory=dict)
    session_storage: Dict[str, str] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
    elapsed_ms: int = 0
    error: Optional[str] = None
    success: bool = True


@dataclass
class InteractionStep:
    action: str
    selector: Optional[str] = None
    text: Optional[str] = None
    key: Optional[str] = None
    x: Optional[int] = None
    y: Optional[int] = None
    wait_ms: int = 0
    wait_for_selector: Optional[str] = None
    wait_for_function: Optional[str] = None
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class InteractionSequence:
    steps: List[InteractionStep]
    description: str = ""
    stop_on_error: bool = True


@dataclass
class InteractionResult:
    success: bool
    results: List[Dict[str, Any]] = field(default_factory=list)
    error: Optional[str] = None
    final_url: str = ""
    final_html: str = ""
    screenshots: List[bytes] = field(default_factory=list)
    elapsed_ms: int = 0


@dataclass
class APIEndpoint:
    url: str
    method: str
    headers: Dict[str, str] = field(default_factory=dict)
    request_body: Optional[Any] = None
    response_body: Optional[Any] = None
    response_status: int = 0
    response_headers: Dict[str, str] = field(default_factory=dict)
    timing: Dict[str, float] = field(default_factory=dict)
    is_graphql: bool = False
    graphql_operation: Optional[str] = None
    graphql_variables: Optional[Dict[str, Any]] = None
    detected_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class CrawlStrategy:
    start_urls: List[str]
    max_depth: int = 3
    max_pages: int = 100
    allowed_domains: List[str] = field(default_factory=list)
    denied_domains: List[str] = field(default_factory=list)
    url_patterns: Dict[str, List[str]] = field(default_factory=dict)
    page_type_selectors: Dict[str, str] = field(default_factory=dict)
    pagination_selectors: List[str] = field(default_factory=list)
    priority_function: Optional[str] = None
    stop_conditions: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PageResult:
    url: str
    page_type: str = "unknown"
    data: Dict[str, Any] = field(default_factory=dict)
    raw_html: str = ""
    parent_url: Optional[str] = None
    depth: int = 0
    engine_used: str = ""
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    children: List[str] = field(default_factory=list)


@dataclass
class EngineConfig:
    name: str
    config: Dict[str, Any] = field(default_factory=dict)
    credentials: Dict[str, str] = field(default_factory=dict)


class HTTPEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def fetch(self, request: HTTPRequest) -> HTTPResponse: ...

    @abstractmethod
    async def fetch_many(self, requests: List[HTTPRequest]) -> List[HTTPResponse]: ...

    @abstractmethod
    async def crawl_sitemap(self, sitemap_url: str) -> AsyncIterator[HTTPResponse]: ...

    @abstractmethod
    async def intercept_apis(self, url: str, duration_ms: int = 10000) -> List[APIEndpoint]: ...

    @abstractmethod
    async def check_robots_txt(self, url: str, user_agent: str) -> bool: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class BrowserEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def navigate(self, request: BrowserRequest) -> BrowserResponse: ...

    @abstractmethod
    async def interact(self, sequence: InteractionSequence) -> InteractionResult: ...

    @abstractmethod
    async def execute_cdp(self, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def evaluate(self, script: str, await_promise: bool = True) -> Any: ...

    @abstractmethod
    def create_context(self, config: Dict[str, Any]) -> "BrowserContext": ...

    @abstractmethod
    async def get_page_count(self) -> int: ...

    @abstractmethod
    async def recycle_context(self, context_id: str) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class BrowserContext(Protocol):
    @property
    @abstractmethod
    def context_id(self) -> str: ...

    @property
    @abstractmethod
    def page_count(self) -> int: ...

    @abstractmethod
    async def navigate(self, request: BrowserRequest) -> BrowserResponse: ...

    @abstractmethod
    async def interact(self, sequence: InteractionSequence) -> InteractionResult: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    def is_healthy(self) -> bool: ...


class ManagedEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def crawl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]: ...

    @abstractmethod
    async def add_urls(self, urls: List[str], priority: int = 0) -> None: ...

    @abstractmethod
    async def get_statistics(self) -> Dict[str, Any]: ...

    @abstractmethod
    async def pause(self) -> None: ...

    @abstractmethod
    async def resume(self) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class CloudEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def scrape(self, request: BrowserRequest) -> BrowserResponse: ...

    @abstractmethod
    async def crawl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]: ...

    @abstractmethod
    async def extract_with_llm(
        self,
        content: str,
        schema: Dict[str, Any],
        prompt: str
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class APIEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def call(
        self,
        endpoint: APIEndpoint,
        auth: Optional[Dict[str, Any]] = None
    ) -> APIEndpoint: ...

    @abstractmethod
    async def discover_endpoints(self, url: str) -> List[APIEndpoint]: ...

    @abstractmethod
    async def intercept_network(self, url: str, duration_ms: int) -> List[APIEndpoint]: ...

    @abstractmethod
    async def replay_request(self, endpoint: APIEndpoint) -> APIEndpoint: ...

    @abstractmethod
    async def refresh_token(self, auth_config: Dict[str, Any]) -> Dict[str, Any]: ...

    @abstractmethod
    def enable_mock_mode(self, har_file: str) -> None: ...

    @abstractmethod
    def disable_mock_mode(self) -> None: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class HybridEngine(Protocol):
    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None: ...

    @abstractmethod
    async def crawl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]: ...

    @abstractmethod
    async def coordinate_engines(
        self,
        strategy: CrawlStrategy,
        engine_assignments: Dict[str, EngineType]
    ) -> AsyncIterator[PageResult]: ...

    @abstractmethod
    async def shutdown(self) -> None: ...

    @abstractmethod
    def health_check(self) -> bool: ...

    @property
    @abstractmethod
    def metadata(self) -> EngineMetadata: ...


class BaseEngine(ABC):
    metadata: EngineMetadata

    def __init__(self) -> None:
        self._initialized = False
        self._config: Optional[EngineConfig] = None
        self._health_check_cache: Optional[bool] = None
        self._health_check_time: Optional[datetime] = None

    @abstractmethod
    async def initialize(self, config: EngineConfig) -> None:
        self._config = config
        self._initialized = True

    @abstractmethod
    async def shutdown(self) -> None:
        self._initialized = False

    @abstractmethod
    def health_check(self) -> bool:
        pass

    def supports(self, capability: EngineCapability) -> bool:
        return capability in self.metadata.capabilities

    def requires_external_service(self) -> bool:
        return self.metadata.requires_external_service

    def get_config(self) -> Optional[EngineConfig]:
        return self._config

    def is_initialized(self) -> bool:
        return self._initialized

    def _record_metrics(self, engine_name: str, success: bool, latency_ms: int) -> None:
        try:
            from scraper.metrics import record_scrape
            record_scrape(engine_name, success, latency_ms)
        except ImportError:
            pass


class EngineFactory(Protocol):
    @abstractmethod
    def create(self, engine_type: EngineType, config: EngineConfig) -> BaseEngine: ...

    @abstractmethod
    def get_available_engines(self) -> List[EngineType]: ...

    @abstractmethod
    def register_engine(self, engine_type: EngineType, factory: Callable[[], BaseEngine]) -> None: ...