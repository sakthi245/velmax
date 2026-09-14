from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Union
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic.types import SecretStr


class QueryExpanderConfig(BaseModel):
    """Configuration for query expander."""
    enabled: bool = True
    model: str = "groq/compound"
    api_key: str = ""
    max_queries_per_goal: int = 5
    temperature: float = 0.3
    max_tokens: int = 500
    timeout: float = 30.0


class RelevanceRankerConfig(BaseModel):
    """Configuration for relevance ranker."""
    model: str = "groq/compound"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 200
    max_results_to_rank: int = 20


class EngineType(str, Enum):
    HTTP = "http"
    BROWSER = "browser"
    MANAGED = "managed"
    CLOUD = "cloud"
    API = "api"
    HYBRID = "hybrid"
    SEARCH = "search"


class OutputFormat(str, Enum):
    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"
    PARQUET = "parquet"
    DB = "db"
    EXCEL = "excel"
    ALL = "all"


class LogLevel(str, Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class StateBackend(str, Enum):
    SQLITE = "sqlite"
    REDIS = "redis"
    POSTGRESQL = "postgresql"


class ExecutionMode(str, Enum):
    IN_PROCESS = "in_process"
    SUBPROCESS = "subprocess"


class ProfileDepth(str, Enum):
    QUICK = "quick"
    STANDARD = "standard"
    DEEP = "deep"


class RoutingRule(BaseModel):
    pattern: Optional[str] = None
    domain: Optional[str] = None
    path_prefix: Optional[str] = None
    engine: str
    reason: str = ""


class RoutingConfig(BaseModel):
    default: str = "crawlee"
    rules: List[RoutingRule] = Field(default_factory=list)


class ValidationMode(str, Enum):
    STRICT = "strict"
    SOFT = "soft"
    FIX = "fix"


class AntiBotLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    EXTREME = "extreme"


class ProxyType(str, Enum):
    NONE = "none"
    DATACENTER = "datacenter"
    RESIDENTIAL = "residential"
    MOBILE = "mobile"
    AUTO = "auto"


class BrowserType(str, Enum):
    CHROMIUM = "chromium"
    FIREFOX = "firefox"
    WEBKIT = "webkit"


class EngineCapability(str, Enum):
    HTTP = "http"
    JAVASCRIPT = "javascript"
    AUTH_FLOWS = "auth_flows"
    STEALTH = "stealth"
    SCREENSHOT = "screenshot"
    HAR_RECORDING = "har_recording"
    PDF_PARSING = "pdf_parsing"
    INFINITE_SCROLL = "infinite_scroll"
    IFRAME_HANDLING = "iframe_handling"
    CDP_ACCESS = "cdp_access"
    SESSION_PERSISTENCE = "session_persistence"
    PROXY_ROTATION = "proxy_rotation"
    COOKIE_MANAGEMENT = "cookie_management"
    DOM_INTERACTION = "dom_interaction"
    NETWORK_INTERCEPTION = "network_interception"
    GRAPHQL = "graphql"
    REST_API = "rest_api"
    WEBSOCKET = "websocket"
    ANTI_BOT = "anti_bot"
    LLM_EXTRACTION = "llm_extraction"
    LARGE_CRAWL = "large_crawl"
    API_INTERCEPTION = "api_interception"
    MOCK_MODE = "mock_mode"
    SEARCH = "search"


class RateLimitConfig(BaseModel):
    requests_per_second: float = 2.0
    requests_per_minute: Optional[float] = None
    requests_per_hour: Optional[float] = None
    burst_allowance: int = 5
    per_domain: bool = True
    adaptive: bool = True
    respect_retry_after: bool = True
    respect_rate_limit_headers: bool = True


class SessionManager(BaseModel):
    enabled: bool = True
    persist_cookies: bool = True
    persist_auth: bool = True
    cookie_jar_path: Optional[Path] = None
    session_ttl: int = 3600
    max_sessions_per_domain: int = 10
    rotate_on_block: bool = True
    blocked_status_codes: Set[int] = Field(default_factory=lambda: {403, 429, 503})
    blocked_error_patterns: List[str] = Field(default_factory=lambda: [
        "captcha", "access denied", "blocked", "rate limit",
        "please verify", "unusual traffic", "challenge"
    ])


class UserAgentPool(BaseModel):
    enabled: bool = True
    pool: List[str] = Field(default_factory=list)
    rotate_per_request: bool = False
    rotate_per_session: bool = True
    custom_ua_string: Optional[str] = None

    @field_validator("pool", mode="before")
    @classmethod
    def default_pool(cls, v: Optional[List[str]]) -> List[str]:
        if not v:
            return [
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            ]
        return v


class TimeoutConfig(BaseModel):
    connect: float = 10.0
    read: float = 30.0
    write: float = 30.0
    total: float = 60.0
    pool: float = 5.0


class RetryPolicy(BaseModel):
    max_attempts: int = 3
    base_delay: float = 1.0
    max_delay: float = 60.0
    exponential_base: float = 2.0
    jitter: bool = True
    jitter_factor: float = 0.1
    retryable_status_codes: Set[int] = Field(default_factory=lambda: {408, 429, 500, 502, 503, 504})
    retryable_exceptions: List[str] = Field(default_factory=lambda: [
        "TimeoutError", "ConnectionError", "ConnectTimeout", "ReadTimeout",
        "ProxyError", "SSLError", "TooManyRedirects"
    ])
    stop_on_status: Set[int] = Field(default_factory=lambda: {400, 401, 403, 404})


class RateLimit(BaseModel):
    requests_per_second: float = 2.0
    requests_per_minute: Optional[float] = None
    requests_per_hour: Optional[float] = None
    burst_allowance: int = 5
    per_domain: bool = True
    adaptive: bool = True
    respect_retry_after: bool = True
    respect_rate_limit_headers: bool = True


class ConcurrencyConfig(BaseModel):
    max_concurrent_requests: int = 10
    max_concurrent_browsers: int = 5
    max_concurrent_per_domain: int = 3
    semaphore_timeout: float = 30.0
    queue_size: int = 1000


class ProxyConfig(BaseModel):
    enabled: bool = False
    proxy_type: ProxyType = ProxyType.AUTO
    proxy_url: Optional[str] = None
    proxy_list: List[str] = Field(default_factory=list)
    rotation_strategy: Literal["round_robin", "random", "sticky_session", "least_used"] = "round_robin"
    sticky_session_ttl: int = 300
    geo_targeting: Optional[str] = None
    auth_username: Optional[str] = None
    auth_password: Optional[SecretStr] = None
    health_check_interval: int = 60
    health_check_url: str = "http://httpbin.org/ip"
    fallback_to_direct: bool = True


class SessionConfig(BaseModel):
    enabled: bool = True
    persist_cookies: bool = True
    persist_auth: bool = True
    cookie_jar_path: Optional[Path] = None
    session_ttl: int = 3600
    max_sessions_per_domain: int = 10
    rotate_on_block: bool = True
    blocked_status_codes: Set[int] = Field(default_factory=lambda: {403, 429, 503})
    blocked_error_patterns: List[str] = Field(default_factory=lambda: [
        "captcha", "access denied", "blocked", "rate limit",
        "please verify", "unusual traffic", "challenge"
    ])


class ErrorHandling(BaseModel):
    log_errors: bool = True
    log_level: LogLevel = LogLevel.WARNING
    capture_screenshots: bool = True
    capture_har: bool = False
    capture_on_status: Set[int] = Field(default_factory=lambda: {403, 429, 500, 502, 503, 504})
    max_error_logs: int = 100
    continue_on_error: bool = True
    error_callback: Optional[Callable[[Exception, str], None]] = None


class DomainRules(BaseModel):
    allowed_domains: List[str] = Field(default_factory=list)
    blocked_domains: List[str] = Field(default_factory=list)
    respect_robots_txt: bool = True
    robots_txt_user_agent: str = "HybridScraper/1.0"
    max_depth: int = 3
    max_pages_per_domain: int = 100
    follow_redirects: bool = True
    max_redirects: int = 10
    canonicalize_urls: bool = True
    strip_query_params: List[str] = Field(default_factory=lambda: ["utm_*", "fbclid", "gclid", "ref"])


class RobotsConfig(BaseModel):
    respect: bool = True
    user_agent: str = "HybridScraper/1.0"


class ContentFilters(BaseModel):
    allowed_mime_types: Set[str] = Field(default_factory=lambda: {
        "text/html", "application/xhtml+xml", "application/json",
        "application/xml", "text/xml", "text/plain"
    })
    blocked_mime_types: Set[str] = Field(default_factory=lambda: {
        "image/", "video/", "audio/", "application/pdf",
        "application/zip", "application/octet-stream"
    })
    max_content_size: int = 50_000_000
    min_content_size: int = 100
    require_content: bool = True
    encoding_detection: bool = True
    force_encoding: Optional[str] = None


class DataValidation(BaseModel):
    validation_schema: Optional[Dict[str, Any]] = None
    schema_file: Optional[Path] = None
    validation_mode: ValidationMode = ValidationMode.SOFT
    required_fields: List[str] = Field(default_factory=list)
    cleaning_rules: Dict[str, List[str]] = Field(default_factory=dict)
    normalization_rules: Dict[str, str] = Field(default_factory=dict)
    dedup_keys: List[str] = Field(default_factory=lambda: ["url"])
    enrichment_steps: List[str] = Field(default_factory=list)
    null_handling: Literal["default", "skip", "mark"] = "default"
    default_values: Dict[str, Any] = Field(default_factory=dict)


class DeduplicationConfig(BaseModel):
    enabled: bool = True
    strategy: Literal["url", "content_hash", "url_content", "custom"] = "url_content"
    url_normalize: bool = True
    content_hash_algorithm: Literal["md5", "sha256", "xxhash"] = "xxhash"
    bloom_filter_size: int = 1_000_000
    bloom_filter_fp_rate: float = 0.01
    persistent_storage: bool = True
    storage_path: Optional[Path] = None
    ttl_days: int = 30


class StorageConfig(BaseModel):
    backend: StateBackend = StateBackend.SQLITE
    local_path: Path = Path("./output")
    s3_bucket: Optional[str] = None
    s3_prefix: str = "scrapes/"
    s3_region: str = "us-east-1"
    s3_access_key: Optional[SecretStr] = None
    s3_secret_key: Optional[SecretStr] = None
    postgres_dsn: Optional[SecretStr] = None
    redis_url: Optional[SecretStr] = None
    kafka_bootstrap_servers: Optional[str] = None
    kafka_topic: str = "scraped_data"
    batch_size: int = 100
    batch_timeout: float = 5.0
    compression: bool = True
    partition_by: Literal["date", "domain", "engine", "none"] = "date"


class ObservabilityConfig(BaseModel):
    enabled: bool = True
    log_level: LogLevel = LogLevel.INFO
    structured_logging: bool = True
    log_format: Literal["json", "console"] = "json"
    metrics_enabled: bool = True
    metrics_port: int = 9090
    metrics_path: str = "/metrics"
    tracing_enabled: bool = False
    tracing_endpoint: Optional[str] = None
    tracing_sample_rate: float = 0.1
    screenshot_on_error: bool = True
    har_on_error: bool = False
    alert_on_error_rate: float = 0.1
    alert_on_latency_p99: float = 30.0


class HTTPEngineConfig(BaseModel):
    enabled: bool = True
    client: Literal["httpx", "aiohttp", "requests"] = "httpx"
    parser: Literal["selectolax", "parsel", "lxml", "beautifulsoup"] = "selectolax"
    follow_links: bool = False
    link_selectors: List[str] = Field(default_factory=lambda: ["a[href]"])
    pagination_selectors: List[str] = Field(default_factory=lambda: [
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
    default_headers: Dict[str, str] = Field(default_factory=lambda: {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })


class BrowserContextConfig(BaseModel):
    viewport_width: int = 1920
    viewport_height: int = 1080
    device_scale_factor: float = 1.0
    is_mobile: bool = False
    has_touch: bool = False
    locale: str = "en-US"
    timezone_id: str = "America/New_York"
    geolocation: Optional[Dict[str, float]] = None
    permissions: List[str] = Field(default_factory=list)
    color_scheme: Literal["light", "dark", "no-preference"] = "light"
    reduced_motion: Literal["reduce", "no-preference"] = "no-preference"
    forced_colors: Literal["active", "none"] = "none"


class BrowserEngineConfig(BaseModel):
    enabled: bool = True
    browser_type: BrowserType = BrowserType.CHROMIUM
    headless: bool = True
    stealth_mode: bool = True
    stealth_config: Dict[str, Any] = Field(default_factory=dict)
    context_config: BrowserContextConfig = Field(default_factory=BrowserContextConfig)
    
    # Pool sizing (adaptive defaults for low-memory)
    pool_min: int = 1
    pool_max: int = 3
    pool_idle_timeout_ms: int = 30_000
    pool_recycle_after_pages: int = 20
    pool_max_memory_mb: int = 512
    
    # Adaptive pool behavior
    adaptive_pool: bool = True
    scale_up_on_queue: int = 3
    scale_down_idle_ratio: float = 0.5
    min_idle_timeout_ms: int = 120_000
    max_idle_timeout_ms: int = 600_000
    
    # Memory-based recycling
    recycle_after_memory_mb: int = 150
    recycle_after_pages: int = 20
    recycle_on_error_rate: float = 0.1
    
    resource_blocking: Dict[str, bool] = Field(default_factory=lambda: {
        "images": True,
        "fonts": True,
        "css": False,
        "media": True,
        "websocket": True,
        "xhr": False,
        "fetch": False,
    })
    wait_until: Literal["load", "domcontentloaded", "networkidle", "commit"] = "networkidle"
    wait_for_selector: Optional[str] = None
    wait_for_function: Optional[str] = None
    wait_for_timeout: Optional[int] = None
    navigation_timeout: int = 60_000
    extra_wait_ms: int = 0
    interaction_sequences: List[Dict[str, Any]] = Field(default_factory=list)
    infinite_scroll: bool = False
    infinite_scroll_max_iterations: int = 10
    infinite_scroll_wait_ms: int = 1000
    infinite_scroll_selector: Optional[str] = None
    iframe_handling: bool = True
    iframe_max_depth: int = 3
    iframe_selectors: List[str] = Field(default_factory=list)
    cdp_enabled: bool = False
    cdp_commands: List[Dict[str, Any]] = Field(default_factory=list)
    har_recording: bool = False
    har_path: Optional[Path] = None
    screenshot_on_error: bool = True
    video_recording: bool = False
    video_dir: Optional[Path] = None
    ignore_https_errors: bool = True
    java_script_enabled: bool = True
    service_workers: Literal["allow", "block"] = "allow"
    anti_bot_evasion: bool = True
    mouse_movement: bool = True
    realistic_timing: bool = True
    referer_chain: bool = True


class PlaywrightSearchConfig(BaseModel):
    """Configuration for Playwright-based search engine."""
    enabled: bool = True
    search_engine: str = "duckduckgo"
    headless: bool = True
    stealth_mode: bool = True
    stealth_config: Dict[str, Any] = Field(default_factory=dict)
    max_pages_per_query: int = 2
    results_per_page: int = 10
    captcha_timeout: int = 60000
    request_timeout: float = 60.0
    delay_between_pages: float = 1.5
    resource_blocking: Dict[str, bool] = Field(default_factory=lambda: {
        "images": True,
        "fonts": True,
        "css": False,
        "media": True,
    })
    viewport_width: int = 1920
    viewport_height: int = 1080
    locale: str = "en-US"
    timezone_id: str = "UTC"
    ignore_https_errors: bool = True
    java_script_enabled: bool = True


class TinyFishSearchConfig(BaseModel):
    """Configuration for TinyFish Search Engine (Primary - Free, 30 req/min)."""
    enabled: bool = True
    api_key: str = ""
    base_url: str = "https://api.search.tinyfish.ai"
    timeout: float = 30.0
    max_results_per_query: int = 10
    rate_limit_delay: float = 2.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    verify_ssl: bool = True
    default_location: str = "US"
    default_language: str = "en"
    default_purpose: str = ""
    default_domain_type: str = "web"
    include_domains: str = ""
    exclude_domains: str = ""
    recency_minutes: int = 0
    page: int = 0
    include_thumbnail: bool = False
    fetch: bool = False


class SerpAPISearchConfig(BaseModel):
    """Configuration for SerpAPI Search Engine (Fallback - 100 free/month)."""
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://serpapi.com/search"
    timeout: float = 30.0
    max_results_per_query: int = 10
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    verify_ssl: bool = True
    engine: str = "google"
    location: str = "United States"
    language: str = "en"
    gl: str = "us"
    hl: str = "en"
    google_domain: str = "google.com"
    safe_search: bool = True
    num_results: int = 10
    device: str = "desktop"


class ManagedEngineConfig(BaseModel):
    enabled: bool = True
    headless: bool = True
    browser_type: BrowserType = BrowserType.CHROMIUM
    max_requests_per_crawl: int = 100
    max_concurrency: int = 10
    request_queue_size: int = 10000
    session_pool_size: int = 50
    session_max_usage: int = 15
    session_max_age_hours: int = 2
    proxy_tiers: List[List[Optional[str]]] = Field(default_factory=lambda: [[None]])  # type: ignore[arg-type]
    blocked_status_codes: Set[int] = Field(default_factory=lambda: {403, 429, 503})
    blocked_error_patterns: List[str] = Field(default_factory=lambda: [
        "captcha", "access denied", "blocked", "rate limit"
    ])
    persist_storage: bool = True
    storage_dir: Optional[Path] = None
    dataset_export: bool = True
    key_value_store_export: bool = False
    follow_links: bool = False
    link_selector: str = "a[href]"
    rpm: int = 120


class CloudEngineConfig(BaseModel):
    enabled: bool = True
    api_url: str = "http://localhost:3002"
    api_key: str = "local-dev"
    formats: List[str] = Field(default_factory=lambda: ["markdown", "html"])
    only_main_content: bool = True
    proxy: Literal["auto", "datacenter", "residential", "none"] = "auto"
    timeout: int = 120000
    wait_for_selector: Optional[str] = None
    wait_for_timeout: int = 5000
    screenshot: bool = False
    pdf: bool = False
    extract_with_llm: bool = False
    llm_schema: Optional[Dict[str, Any]] = None
    llm_prompt: Optional[str] = None
    failure_threshold: int = 3
    recovery_timeout: int = 60
    health_check_interval: int = 30
    
    # Auto-management for Docker Firecrawl
    auto_start: bool = True
    auto_stop_idle_min: int = 30


class APIEngineConfig(BaseModel):
    enabled: bool = True
    intercept_network: bool = True
    intercept_types: List[str] = Field(default_factory=lambda: ["XHR", "Fetch", "WebSocket"])
    endpoint_patterns: List[str] = Field(default_factory=lambda: [
        "*/api/*", "*/graphql", "*/graphql/", "*/rest/*", "*/v*/"
    ])
    auth_methods: List[str] = Field(default_factory=lambda: ["bearer", "api_key", "cookie", "oauth2"])
    token_refresh_enabled: bool = True
    token_refresh_endpoint: Optional[str] = None
    token_refresh_method: Literal["POST", "GET"] = "POST"
    mock_mode: bool = False
    mock_har_path: Optional[Path] = None
    graphql_introspection: bool = True
    rate_limit_per_endpoint: int = 60
    response_validation: bool = True
    request_templates: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


class ScriptGenConfig(BaseModel):
    enabled: bool = True
    cache: "CacheConfig" = Field(default_factory=lambda: CacheConfig())
    execution: "ExecutionConfig" = Field(default_factory=lambda: ExecutionConfig())
    template_dir: Optional[Path] = None
    force_regenerate: bool = False
    validate_generated: bool = True
    validation_tools: List[str] = Field(default_factory=lambda: ["ruff", "mypy", "pytest"])
    llm_assisted: bool = True
    llm_model: str = "groq/compound"


class CacheConfig(BaseModel):
    backend: StateBackend = StateBackend.SQLITE
    cache_dir: Path = Path("./scripts_cache")
    ttl_days: int = 7
    max_entries: int = 1000
    change_detection: bool = True
    change_detection_sample_pages: int = 3
    max_failures_before_regenerate: int = 3
    cleanup_interval_hours: int = 24
    enable_compression: bool = True
    max_size_mb: int = 100


class ExecutionConfig(BaseModel):
    mode: ExecutionMode = ExecutionMode.IN_PROCESS
    timeout: int = 300
    memory_limit_mb: int = 1024
    cpu_limit: float = 1.0
    capture_output: bool = True
    working_dir: Optional[Path] = None
    env_vars: Dict[str, str] = Field(default_factory=dict)


class FallbackConfig(BaseModel):
    enabled: bool = True
    quality_threshold: float = 0.7
    completeness_threshold: float = 0.5
    accuracy_threshold: float = 0.7
    max_fallback_attempts: int = 3
    fallback_on: List[str] = Field(default_factory=lambda: [
        "network_error", "http_error", "blocking", "empty_content",
        "parsing_error", "engine_error", "quality_below_threshold"
    ])
    prefer_local_engines: bool = True
    cloud_as_last_resort: bool = True


class CheckpointConfig(BaseModel):
    enabled: bool = True
    interval_pages: int = 100
    interval_seconds: int = 300
    backend: StateBackend = StateBackend.POSTGRESQL
    retention_days: int = 30
    max_checkpoints: int = 10


class TaskPriority(str, Enum):
    DETAIL = "detail"
    LIST = "list"
    OTHER = "other"


class QueueConfig(BaseModel):
    host: str = "localhost"
    port: int = 5672
    username: str = "guest"
    password: str = "guest"
    vhost: str = "/"
    priority_exchange: str = "scrapy.priority"
    dead_letter_exchange: str = "scrapy.dlx"
    prefetch_count: int = 10
    connection_timeout: int = 30
    heartbeat: int = 60
    publisher_confirms: bool = True


class WorkerConfig(BaseModel):
    worker_id: str = ""
    max_concurrent: int = 5
    heartbeat_interval: int = 30
    graceful_shutdown_timeout: int = 60
    metrics_port: int = 9090
    log_level: str = "INFO"


class GenerationRequirements(BaseModel):
    engine_preference: Optional[EngineType] = None
    output_formats: List[OutputFormat] = Field(default_factory=lambda: [OutputFormat.JSONL])
    enrichment_steps: List[str] = Field(default_factory=list)
    compliance_flags: List[str] = Field(default_factory=list)
    incremental: bool = True
    resume_support: bool = True
    test_generation: bool = True
    documentation: bool = True


class LLMProviderConfig(BaseModel):
    name: str = "groq"
    base_url: str = "https://api.groq.com/openai/v1"
    api_key: str = ""
    model: str = "groq/compound"
    temperature: float = 0.1
    max_tokens: int = 2000
    rpm_limit: int = 30
    tpm_limit: int = 14400


class ExtractionConfig(BaseModel):
    enabled: bool = True
    primary_llm: LLMProviderConfig = Field(default_factory=lambda: LLMProviderConfig(
        name="groq",
        base_url="https://api.groq.com/openai/v1",
        api_key="",
        model="groq/compound",
        temperature=0.1,
        max_tokens=2000,
        rpm_limit=30,
        tpm_limit=14400,
    ))
    fallback_llm: Optional[LLMProviderConfig] = Field(default_factory=lambda: LLMProviderConfig(
        name="nvidia",
        base_url="https://integrate.api.nvidia.com/v1",
        api_key="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",
        model="nvidia/nemotron-3.5-lightning",
        temperature=0.1,
        max_tokens=2000,
        rpm_limit=60,
        tpm_limit=20000,
    ))
    temperature: float = 0.1
    max_tokens: int = 2000
    max_concurrent: int = 3
    validation_mode: ValidationMode = ValidationMode.SOFT
    max_results_to_extract: int = 0
    timeout: float = 60.0
    cache_enabled: bool = True
    cache_ttl_hours: int = 24


class UniversalConfig(BaseModel):
    target_urls: Union[str, List[str]] = Field(default_factory=list)
    output_format: Union[OutputFormat, List[OutputFormat]] = OutputFormat.ALL
    output_dir: Path = Path("./output")
    user_agent: Union[str, UserAgentPool] = Field(default_factory=UserAgentPool)
    headers: Dict[str, str] = Field(default_factory=dict)
    cookies: Dict[str, str] = Field(default_factory=dict)
    proxy_config: ProxyConfig = Field(default_factory=ProxyConfig)
    request_timeout: TimeoutConfig = Field(default_factory=TimeoutConfig)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    rate_limit: RateLimit = Field(default_factory=RateLimit)
    concurrency: ConcurrencyConfig = Field(default_factory=ConcurrencyConfig)
    session_config: SessionConfig = Field(default_factory=SessionConfig)
    error_handling: ErrorHandling = Field(default_factory=ErrorHandling)
    domain_rules: DomainRules = Field(default_factory=DomainRules)
    content_filters: ContentFilters = Field(default_factory=ContentFilters)
    data_validation: DataValidation = Field(default_factory=DataValidation)
    deduplication: DeduplicationConfig = Field(default_factory=DeduplicationConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    observability: ObservabilityConfig = Field(default_factory=ObservabilityConfig)
    http_engine: HTTPEngineConfig = Field(default_factory=HTTPEngineConfig)
    browser_engine: BrowserEngineConfig = Field(default_factory=BrowserEngineConfig)
    playwright_search: PlaywrightSearchConfig = Field(default_factory=PlaywrightSearchConfig)
    tinyfish_search: TinyFishSearchConfig = Field(default_factory=TinyFishSearchConfig)
    serpapi_search: SerpAPISearchConfig = Field(default_factory=SerpAPISearchConfig)
    query_expander: QueryExpanderConfig = Field(default_factory=QueryExpanderConfig)
    relevance_ranker: RelevanceRankerConfig = Field(default_factory=RelevanceRankerConfig)
    engines: Dict[str, Any] = Field(default_factory=dict)
    managed_engine: ManagedEngineConfig = Field(default_factory=ManagedEngineConfig)
    cloud_engine: CloudEngineConfig = Field(default_factory=CloudEngineConfig)
    api_engine: APIEngineConfig = Field(default_factory=APIEngineConfig)
    script_generation: ScriptGenConfig = Field(default_factory=ScriptGenConfig)
    fallback: FallbackConfig = Field(default_factory=FallbackConfig)
    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    robots: RobotsConfig = Field(default_factory=lambda: RobotsConfig(respect=True, user_agent="HybridScraper/1.0"))
    checkpoint: CheckpointConfig = Field(default_factory=CheckpointConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    worker: WorkerConfig = Field(default_factory=WorkerConfig)
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)

    @field_validator("target_urls", mode="before")
    @classmethod
    def normalize_urls(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            return [v]
        return v

    @field_validator("output_format", mode="before")
    @classmethod
    def normalize_output_format(cls, v: Union[OutputFormat, str, List[Union[OutputFormat, str]]]) -> List[OutputFormat]:
        if isinstance(v, str):
            return [OutputFormat(v)]
        if isinstance(v, OutputFormat):
            return [v]
        if isinstance(v, list):
            return [OutputFormat(f) if isinstance(f, str) else f for f in v]
        return v

    @model_validator(mode="after")
    def validate_output_dir(self) -> "UniversalConfig":
        self.output_dir.mkdir(parents=True, exist_ok=True)
        return self

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()


class UniversalRequest(BaseModel):
    url: Optional[str] = None
    goal: str = ""
    request_schema: Optional[Dict[str, Any]] = None
    schema_file: Optional[Path] = None
    engine: Optional[EngineType] = None
    engine_options: Dict[str, Any] = Field(default_factory=dict)
    max_pages: int = 10
    depth: int = 0
    output_formats: List[OutputFormat] = Field(default_factory=lambda: [OutputFormat.JSONL])
    output_dir: Optional[Path] = None
    use_proxy: bool = False
    render_js: bool = False
    pdf: bool = False
    screenshot: bool = False
    extract_schema: Optional[Dict[str, Any]] = None
    prompt: Optional[str] = None
    priority: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)
    config_override: Optional[UniversalConfig] = None
    headers: Dict[str, str] = Field(default_factory=dict)
    force_rescrape: bool = False


class UniversalResult(BaseModel):
    success: bool
    url: Optional[str] = None
    data: Any = None
    raw_data: Any = None
    cleaned_data: Any = None
    validation_report: Optional[Dict[str, Any]] = None
    formatted_outputs: Dict[str, Any] = Field(default_factory=dict)
    engine_used: str = ""
    engine_attempts: List[Dict[str, Any]] = Field(default_factory=list)
    quality_score: float = 0.0
    completeness: float = 0.0
    accuracy: float = 0.0
    duplicate_rate: float = 0.0
    latency_ms: int = 0
    error: Optional[str] = None
    errors: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    fallback_triggered: bool = False
    script_generated: bool = False
    cache_hit: bool = False
    normalization_stats: Optional[Dict[str, int]] = None

    def to_legacy_format(self) -> List[Dict[str, Any]]:
        if self.success and self.data:
            if isinstance(self.data, list):
                return self.data
            return [self.data]
        return []


class SiteProfile(BaseModel):
    url: str
    category: str = "unknown"
    js_framework: Optional[str] = None
    js_framework_version: Optional[str] = None
    requires_js: bool = False
    anti_bot_level: AntiBotLevel = AntiBotLevel.NONE
    anti_bot_details: Dict[str, Any] = Field(default_factory=dict)
    has_pagination: bool = False
    pagination_type: Optional[str] = None
    pagination_selectors: List[str] = Field(default_factory=list)
    page_types: Dict[str, int] = Field(default_factory=dict)
    selectors: Dict[str, List[str]] = Field(default_factory=dict)
    api_endpoints: List[Dict[str, Any]] = Field(default_factory=list)
    auth_required: bool = False
    auth_type: Optional[str] = None
    performance_metrics: Dict[str, float] = Field(default_factory=dict)
    recommended_engine: EngineType = EngineType.HTTP
    confidence: float = 0.0
    analyzed_at: str = ""
    sample_pages: int = 0

    def hash(self) -> str:
        import hashlib
        content = f"{self.url}{self.category}{self.js_framework}{self.anti_bot_level}"
        content += f"{self.has_pagination}{self.page_types}{self.selectors}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class DeepSiteProfile(SiteProfile):
    llm_analysis: Optional[Dict[str, Any]] = None
    interaction_sequences: List[Dict[str, Any]] = Field(default_factory=list)
    selector_stability: Dict[str, float] = Field(default_factory=dict)
    inferred_schemas: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    fallback_context: Optional[Dict[str, Any]] = None
    profile_depth: ProfileDepth = ProfileDepth.DEEP


class FallbackContext(BaseModel):
    target_url: Optional[str] = None
    profile: SiteProfile
    attempts: List[Dict[str, Any]] = Field(default_factory=list)
    request_config: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str = ""
    error_category: Optional[str] = None
    error_severity: Optional[str] = None
    force_regenerate: bool = False


class GenerationStrategy(BaseModel):
    engine: EngineType
    template: str
    confidence: float
    reasoning: str


class GeneratedScript(BaseModel):
    strategy: Optional[GenerationStrategy] = None
    main_code: str
    config_code: str
    test_code: str
    requirements_code: str
    validation: "ValidationResult"
    metadata: "GenerationMetadata"


class ValidationResult(BaseModel):
    passed: bool
    lint_errors: List[str] = Field(default_factory=list)
    type_errors: List[str] = Field(default_factory=list)
    test_errors: List[str] = Field(default_factory=list)
    success_probability: float = 0.0
    warnings: List[str] = Field(default_factory=list)


class GenerationMetadata(BaseModel):
    profile_hash: str
    generator_version: str
    timestamp: str
    estimated_success_rate: float
    template_versions: Dict[str, str] = Field(default_factory=dict)


class CachedScript(BaseModel):
    script: GeneratedScript
    metadata: "CacheEntry"


class CacheEntry(BaseModel):
    key: str
    url: str
    profile_hash: str
    script_path: str
    created_at: str
    ttl_days: int
    success_count: int = 0
    failure_count: int = 0
    last_used: Optional[str] = None


class FailureClassification(BaseModel):
    category: str
    severity: Literal["low", "medium", "high", "critical"]
    should_fallback: bool
    context: Dict[str, Any] = Field(default_factory=dict)
    retry_suggested: bool = False
    suggested_engine: Optional[EngineType] = None


class EngineAttempt(BaseModel):
    engine: str
    success: bool
    latency_ms: int
    error: Optional[str] = None
    result_quality: Optional[float] = None
    error_category: Optional[str] = None
    timestamp: str = ""


class EngineMetrics(BaseModel):
    engine: str
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_latency_ms: int = 0
    avg_latency_ms: float = 0.0
    success_rate: float = 0.0
    last_used: Optional[str] = None
    circuit_breaker_state: str = "closed"
    consecutive_failures: int = 0
    consecutive_successes: int = 0


class OrchestratorPoolConfig(BaseModel):
    pool_size: int = 5
    shared_cache: bool = True
    shared_session_manager: bool = True
    max_queue_size: int = 1000
    task_timeout: int = 300
    retry_failed: bool = True
    max_retries: int = 1


class HealthCheckResult(BaseModel):
    engine: str
    healthy: bool
    latency_ms: int
    error: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)
    checked_at: str = ""