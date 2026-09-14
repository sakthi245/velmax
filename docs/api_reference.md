# API Reference

Complete API reference for the Hybrid Web Scraper.

## Table of Contents
- [Core Classes](#core-classes)
- [Configuration](#configuration)
- [Engines](#engines)
- [Utilities](#utilities)
- [Security](#security)
- [Observability](#observability)

---

## Core Classes

### `SecurityManager`
Central security manager coordinating all security features.

```python
from scraper.utils.security import SecurityManager, SecurityConfig

config = SecurityConfig(
    enable_ssrf_protection=True,
    block_private_ips=True,
    allowed_ip_ranges=["10.0.0.0/8", "192.168.0.0/16"]
)

manager = SecurityManager(config)
```

#### Methods

| Method | Description |
|--------|-------------|
| `validate_request(request_data)` | Validate an incoming request |
| `validate_url(url)` | Validate a URL against security policies |
| `sanitize_input(data, context)` | Sanitize input based on context |
| `get_cors_headers(origin, method, request_headers)` | Get CORS headers |
| `handle_preflight(origin, method, headers)` | Handle preflight request |
| `get_csp_header()` | Get CSP header value |
| `get_secret(key, default)` | Get a secret value |
| `set_secret(key, value)` | Set a secret value |
| `rotate_secret(key)` | Rotate a secret |
| `generate_api_key(prefix)` | Generate an API key |
| `get_metrics()` | Get security metrics |

### `SecurityConfig`
Configuration for security features.

```python
from scraper.utils.security import SecurityConfig

config = SecurityConfig(
    enable_ssrf_protection=True,
    block_private_ips=True,
    allowed_ip_ranges=["10.0.0.0/8", "192.168.0.0/16"],
    blocked_ip_ranges=["10.0.0.0/8"],  # This would conflict with allowed
    block_private_ips=True,
    block_loopback=True,
    max_body_size=10 * 1024 * 1024,  # 10MB
    max_header_count=100,
    cors_enabled=True,
    cors_allowed_origins=["https://example.com"],
    csp_enabled=True,
    csp_policy=None,  # Use default strict CSP
    secrets_backend="env",
    secret_rotation_days=90,
)
```

---

## Engines

### `UniversalRunner`
Main orchestrator for scraping operations.

```python
from scraper.universal_runner import UniversalRunner

runner = UniversalRunner(config)

# Scrape a URL
result = await runner.scrape(
    url="https://example.com",
    goal="Extract product prices",
    max_pages=10,
    depth=2
)
```

### `FallbackStrategyRouter`
Routes requests through multiple engines with fallback.

```python
from scraper.strategy import FallbackStrategyRouter

router = FallbackStrategyRouter(config)
result = await router.scrape(url, goal, schema)
```

### Engine Types

| Engine | Class | Use Case |
|--------|-------|----------|
| HTTP | `HTTPEngine` | Fast static content |
| Browser | `BrowserEngine` | JavaScript-rendered pages |
| Managed | `ManagedEngine` | Crawlee-based crawling |
| Cloud | `CloudEngine` | Firecrawl API |
| API | `APIEngine` | GraphQL/REST endpoints |

---

## Configuration

### `UniversalConfig`
Main configuration class.

```python
from scraper.config.schemas import UniversalConfig

config = UniversalConfig(
    target_urls=["https://example.com"],
    output_format=["jsonl", "csv"],
    output_dir="./output",
    max_pages=100,
    depth=2,
    mode="auto",  # auto, free_only, cloud_preferred
    engine="auto",  # auto, firecrawl, crawlee, playwright, scrapy
)
```

### Engine Configurations

Each engine has its own config:

```python
from scraper.config.schemas import (
    HTTPEngineConfig,
    BrowserEngineConfig,
    ManagedEngineConfig,
    CloudEngineConfig,
    APIEngineConfig,
)

http_config = HTTPEngineConfig(
    enabled=True,
    client="httpx",
    parser="selectolax",
    follow_links=False,
)

browser_config = BrowserEngineConfig(
    enabled=True,
    headless=True,
    browser_type="chromium",
    stealth_mode=True,
    pool_max=3,
)
```

---

## Utilities

### Rate Limiting

```python
from scraper.utils.rate_limiter import RateLimiter, RateLimitConfig, create_rate_limiter

config = RateLimitConfig(
    requests_per_second=2.0,
    burst_allowance=5,
    per_domain=True,
    adaptive=True,
)

limiter = create_rate_limiter(config)
await limiter.acquire("example.com")
```

### Caching

```python
from scraper.utils.rate_limiter import LRUCache, CacheConfig

cache = LRUCache(max_size=1000, ttl=3600)
await cache.set("GET", "https://example.com", response)
response = await cache.get("GET", "https://example.com")
```

### Deduplication

```python
from scraper.utils.dedup import DeduplicationManager, DedupConfig

dedup = DeduplicationManager(DedupConfig(
    strategy="url_content",
    persistent_storage=True,
))
is_dup = dedup.is_duplicate("https://example.com/page1")
dedup.mark_seen("https://example.com/page1")
```

### Retry & Circuit Breaker

```python
from scraper.utils.retry import RetryPolicy, CircuitBreaker, execute_with_retry

policy = RetryPolicy(
    max_attempts=3,
    base_delay=1.0,
    max_delay=60.0,
    exponential_base=2.0,
)

breaker = CircuitBreaker(
    failure_threshold=5,
    recovery_timeout=60.0,
)

result = await execute_with_retry(coro_func, policy=policy)
```

---

## Security

### Input Sanitization

```python
from scraper.utils.security import (
    sanitize_html,
    sanitize_sql,
    sanitize_path,
    sanitize_filename,
    sanitize_text,
)

# HTML sanitization
safe_html = sanitize_html("<script>alert(1)</script>Hello")

# SQL sanitization
safe_sql = sanitize_sql("1; DROP TABLE users")

# Path traversal prevention
safe_path = sanitize_path("../../../etc/passwd")

# Filename sanitization
safe_name = sanitize_filename("file<script>.txt")
```

### URL Validation

```python
from scraper.utils.security import validate_url, SecurityManager, SecurityConfig

config = SecurityConfig(enable_ssrf_protection=True, block_private_ips=True)
manager = SecurityManager(SecurityConfig(
    enable_ssrf_protection=True,
    block_private_ips=True,
))

# Validate URL
is_valid = validate_url("https://example.com", config)

# Or use manager directly
valid = manager.validate_url("https://example.com")
```

### URL Validation

```python
from scraper.utils.security import SecurityManager, SecurityConfig

config = SecurityConfig(
    enable_ssrf_protection=True,
    block_private_ips=True,
    allowed_ip_ranges=["10.0.0.0/8", "192.168.0.0/16"],
)

manager = SecurityManager(SecurityConfig(
    enable_ssrf_protection=True,
    block_private_ips=True,
))

# Test URLs
urls = [
    "https://example.com",      # VALID
    "http://localhost:8080",    # BLOCKED (loopback)
    "http://192.168.1.1",       # BLOCKED (private)
    "http://10.0.0.1",          # BLOCKED (private)
    "file:///etc/passwd",       # BLOCKED (blocked scheme)
    "javascript:alert(1)",      # BLOCKED (blocked scheme)
]

for url in urls:
    valid = manager.validate_url(url)
    print(f"{url}: {'VALID' if valid else 'BLOCKED'}")
```

### Secret Management

```python
from scraper.utils.security import SecretManager, SecurityConfig

config = SecurityConfig(secrets_backend="env")
manager = SecretManager(SecurityConfig(secrets_backend="env"))

# Get secret
api_key = manager.get_secret("OPENAI_API_KEY")

# Generate API key
api_key = manager.generate_api_key("sk")

# Generate secret
secret = manager.generate_secret(32)

# Hash secret for storage
hashed = manager.hash_secret("my-secret")

# Verify
valid = manager.verify_secret("my-secret", hashed)
```

### Rate Limiting

```python
from scraper.utils.rate_limiter import RateLimiter, RateLimitConfig, create_rate_limiter

config = RateLimitConfig(
    requests_per_second=2.0,
    burst_allowance=5,
    per_domain=True,
    adaptive=True,
)

limiter = create_rate_limiter(config)
await limiter.acquire("example.com")
```

---

## Observability

### Metrics

```python
from scraper.utils.observability import (
    MetricsCollector,
    ObservabilityConfig,
    get_metrics_collector,
)

config = ObservabilityConfig(
    metrics_enabled=True,
    metrics_port=9090,
    metrics_path="/metrics",
)

collector = MetricsCollector("my-engine", ObservabilityConfig(
    metrics_enabled=True,
))

# Record metrics
collector.record_request("my-engine", True, 150, "example.com")
collector.record_cache("my-engine", "http", True)
collector.record_quality("my-engine", 0.95)
```

### Structured Logging

```python
from scraper.utils.observability import get_logger, configure_observability

configure_observability(log_level="INFO", structured=True)
logger = get_logger("my-module")

logger.info("Request started", url="https://example.com")
logger.warning("Rate limit hit", domain="example.com")
logger.error("Request failed", error="Timeout")
```

### Tracing

```python
from scraper.utils.observability import trace_span, traced

@traced("scrape_page", attributes={"url": "https://example.com"})
async def scrape_page(url):
    async with trace_span("fetch", {"url": url}) as span:
        # Your code here
        pass
```

---

## CLI Usage

```bash
# Basic scrape
python -m scraper.run --target https://example.com --goal "Extract prices"

# With options
python -m scraper.run \
    --target https://example.com \
    --goal "Extract product prices" \
    --mode auto \
    --engine auto \
    --max-pages 10 \
    --depth 2 \
    --output-path ./output

# Distributed workers
docker compose -f docker-compose.distributed.yml up --scale worker=3
```

---

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `SCRAPER_LOG_LEVEL` | Log level | `INFO` |
| `SCRAPER_OUTPUT_DIR` | Output directory | `./output` |
| `SCRAPER_MODE` | Scraping mode | `auto` |
| `FIRECRAWL_API_KEY` | Firecrawl API key | - |
| `OPENAI_API_KEY` | OpenAI API key | - |
| `POSTGRES_DSN` | PostgreSQL connection | - |
| `REDIS_URL` | Redis connection | `redis://localhost:6379` |
| `RABBITMQ_URL` | RabbitMQ connection | - |
| `SECRETS_BACKEND` | Secrets backend | `env` |
| `LOG_LEVEL` | Log level | `INFO` |

---

## Error Handling

### Exception Hierarchy

```
SecurityError
├── SSRFProtectionError
├── InputValidationError
└── SecretNotFoundError
```

```python
from scraper.utils.security import (
    SecurityError,
    SSRFProtectionError,
    InputValidationError,
    SecretNotFoundError,
)

try:
    validate_url("http://192.168.1.1")
except SSRFProtectionError:
    # Blocked by SSRF protection
    pass

try:
    sanitize_path("../../../etc/passwd")
except InputValidationError:
    pass
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_selector.py -v

# Run with coverage
pytest tests/ --cov=scraper --cov-report=html

# Run integration tests
pytest tests/integration/ -v
```

---

## Version Compatibility

| Component | Minimum Version |
|-----------|----------------|
| Python | 3.10+ |
| Playwright | 1.40+ |
| aiohttp | 3.9+ |
| httpx | 0.25+ |
| playwright | 1.40+ |
| aiohttp | 3.9+ |
| redis | 5.0+ (for distributed rate limiting) |

---

## Support

- **Issues**: [GitHub Issues](https://github.com/your-repo/issues)
- **Documentation**: [Full Docs](https://your-docs-url)
- **Security**: [Security Policy](https://your-repo/security)

---

*Last updated: 2026-08-25*
*Version: 1.0.0*