# Engine Guide

## Overview

The hybrid-web-scraper uses a multi-engine architecture with automatic fallback. Each engine has specific strengths and use cases.

## Engine Comparison

| Engine | Type | JS Support | Anti-Bot | Concurrency | Best For |
|--------|------|------------|----------|-------------|----------|
| **scrapy** | HTTP | ❌ | Low | 16+ | Static pages, APIs, sitemaps |
| **playwright** | Browser | ✅ | Medium | 5 | Dynamic pages, auth flows |
| **crawlee** | Managed Browser | ✅ | High | 10-20 | Large crawls, session persistence |
| **firecrawl** | Cloud | ✅ | Very High | 5 | Anti-bot sites, PDFs, screenshots |
| **apify** | Cloud | ✅ | Very High | 10 | Actor-based workflows |
| **api** | API Client | ✅ | High | 16+ | Direct API/GraphQL endpoints |

## Engine Selection Logic

The selector automatically chooses the best engine based on:

1. **Explicit engine** (`--engine` flag) - overrides everything
2. **Routing rules** (from config.yaml) - domain/pattern matching
3. **Capability inference** from request:
   - `.pdf` URLs → Firecrawl
   - JavaScript frameworks detected → Playwright/Crawlee
   - Anti-bot indicators → Firecrawl
   - GraphQL/API endpoints → API engine
   - Large crawls → Crawlee

## Engine Details

### Scrapy (HTTP Engine)
- **Type**: HTTP-based static HTML parser
- **Dependencies**: `requests`, `PyYAML`, `parsel`, `selectolax`
- **Strengths**: Fast, low memory, handles sitemaps/robots.txt natively
- **Limitations**: No JavaScript execution, no auth flows
- **Best for**: Static sites, RSS feeds, sitemaps, REST APIs

```python
# Auto-selected for static sites
result = await scrape("https://example.com", "Extract page text", engine="scrapy")
```

### Playwright Engine
- **Type**: Browser automation (Chromium/Firefox/WebKit)
- **Dependencies**: `playwright`, `playwright-stealth`
- **Features**: Stealth mode, CDP access, screenshots, PDF, HAR recording
- **Concurrency**: 5 concurrent browsers (configurable)
- **Stealth**: Automatic fingerprint masking, stealth.js injection

```python
# Use for JS-heavy sites, login flows
result = await scrape(url, goal, engine="playwright")

# With interactions
result = await scrape(url, goal, engine="playwright", interactions=[
    {"action": "click", "selector": ".login-btn"},
    {"action": "fill", "selector": "#username", "text": "user"},
    {"action": "fill", "selector": "#password", "text": "pass"},
    {"action": "click", "selector": ".submit-btn"},
])
```

### Crawlee (Managed Engine)
- **Type**: Managed browser pool with session persistence
- **Dependencies**: `crawlee[playwright]`
- **Features**: Session pool, proxy rotation, request queue, dataset export
- **Concurrency**: 10-20 concurrent (configurable)
- **Session Management**: Automatic cookie/cookie persistence

```python
# Best for large crawls with session persistence
result = await scrape(url, goal, engine="crawlee", max_pages=1000)
```

### Firecrawl (Cloud)
- **Type**: Self-hosted/cloud scraping service
- **Dependencies**: `firecrawl-py`, Docker (self-hosted)
- **Features**: Built-in anti-bot bypass, PDF extraction, screenshots, LLM extraction
- **API**: Self-hosted (localhost:3002) or cloud API

```python
# Auto-selected for anti-bot sites, PDFs, screenshots
result = await scrape(url, goal, engine="firecrawl")

# With LLM extraction
result = await scrape(url, goal, engine="firecrawl", 
    extract_schema={"type": "object", "properties": {"title": {"type": "string"}}})
```

### API Engine
- **Type**: Direct API/GraphQL client
- **Features**: Network interception, GraphQL introspection, token refresh, mock mode
- **Use case**: Direct API access, GraphQL endpoints

```python
# Direct API calls
result = await scrape(url, goal, engine="api")

# GraphQL query
result = await client.graphql_query(
    url="https://api.example.com/graphql",
    query="query { products { name price } }"
)
```

## Engine Selection Priority

Default priority (configurable in `config.yaml`):

```yaml
engine_priority:
  - firecrawl      # Best anti-bot, PDF, screenshots
  - apify          # Actor-based, good for complex workflows
  - playwright     # General JS rendering
  - crawlee        # Large crawls with sessions
  - scrapy         # Static content, fast
```

## Fallback Behavior

The fallback chain activates on:
- HTTP 403, 429, 5xx errors
- CAPTCHA/challenge pages
- Empty/invalid responses
- Timeouts
- Circuit breaker open

Default fallback chain (configurable):
```
firecrawl → playwright → http → crawlee → api
```

For anti-bot sites:
```
firecrawl → playwright → crawlee
```

## Custom Engine Registration

```python
from scraper.engines import EngineRegistry, BaseEngine
from scraper.engines.interfaces import EngineMetadata, EngineType

class CustomEngine(BaseEngine):
    metadata = EngineMetadata(
        name="custom",
        type=EngineType.HTTP,
        capabilities=[EngineCapability.JAVASCRIPT],
        max_concurrent=10
    )
    
    async def scrape(self, request):
        # Implementation
        pass

# Register
from scraper.engines import EngineRegistry
EngineRegistry.register("custom", CustomEngine, CustomEngine.metadata)

# Use
result = await scrape(url, goal, engine="custom")
```

## Engine Configuration Reference

### Playwright Config
```yaml
playwright:
  headless: true
  stealth_mode: true
  browser: "chromium"
  pool_min: 2
  pool_max: 5
  pool_idle_timeout_ms: 60000
  pool_recycle_after_pages: 50
  resource_blocking:
    images: true
    fonts: true
    media: true
  wait_until: "networkidle"
  infinite_scroll: false
```

### Crawlee Config
```yaml
crawlee:
  headless: true
  browser_type: "chromium"
  max_requests_per_crawl: 100
  max_concurrency: 10
  session_pool_size: 50
  session_max_usage: 15
  session_max_age_hours: 2
  rpm: 120
  follow_links: false
```

### Firecrawl Config
```yaml
firecrawl:
  enabled: true
  api_url: "http://localhost:3002"
  api_key: "local-dev"
  formats: ["markdown", "html"]
  only_main_content: true
  proxy: "auto"
  timeout: 120000
  wait_for_selector: null
  wait_for_timeout: 5000
  screenshot: false
  pdf: false
  extract_with_llm: false
```

### HTTP Engine (Scrapy)
```yaml
scrapy:
  download_delay: 1
  concurrent_requests: 16
  autothrottle_enabled: true
  autothrottle_start_delay: 1
  autothrottle_max_delay: 60
  autothrottle_target_concurrency: 2.0
```

## Choosing the Right Engine

| Scenario | Recommended Engine |
|----------|-------------------|
| Static blog/article | `scrapy` |
| E-commerce product pages | `playwright` or `firecrawl` |
| Large e-commerce crawl | `crawlee` |
| Cloudflare/Akamai protected | `firecrawl` |
| PDF documents | `firecrawl` |
| Screenshots/PDFs needed | `firecrawl` |
| LLM-structured extraction | `firecrawl` |
| GraphQL/REST API | `api` |
| Large catalog crawl (10k+ pages) | `crawlee` |
| Authenticated areas | `playwright` or `crawlee` |
| Simple static site | `scrapy` |