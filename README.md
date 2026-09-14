# hybrid-web-scraper

A robots-aware, free-first web scraping pipeline that prioritizes local engines (Scrapy/Playwright) before cloud adapters (Firecrawl/Apify). Designed for public HTTP(S) pages only.

---

## ⚠️ Core Constraints (read before use)

- **Public pages only**: This package scrapes public HTTP(S) pages with a robots-aware, local-first fallback pipeline.
- **No login flows**: Authentication flows are not supported.
- **No CAPTCHA solving**: CAPTCHA handling is not supported.
- **No proxy rotation**: Proxy management is not supported.
- **No paywall bypass**: Paywall circumvention is not supported.
- **No anti-bot circumvention**: Techniques to bypass anti-bot measures are not supported.
- **Compliance required**: You are responsible for complying with each site's terms of service and applicable law.

---

## 📦 Installation

```powershell
cd hybrid_web_scraper
python -m venv .venv
\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

### Engines

| Engine | Optional deps | Description |
|--------|--------------|-------------|
| `scrapy` | `requests`, `PyYAML` | Local HTTP extractor; always available |
| `playwright` | `playwright` | JavaScript-rendered pages; install browsers with `playwright install chromium` |
| `firecrawl` | `firecrawl-py`, `FIRECRAWL_API_KEY` | Cloud adapter |
| `apify` | `apify-client`, `APIFY_TOKEN` | Cloud adapter |

Install extra dependencies:

```powershell
# Playwright support
pip install -e ".[playwright]"

# Cloud adapters (optional)
pip install -e ".[cloud]"
```

---

## 🛠️ Quick Start

### Basic CLI run (interactive)

```powershell
python -m scraper.run
```

### Non-interactive CLI

```powershell
python -m scraper.run --target https://example.com --goal "Extract page text" --mode free_only
```

### Python API

```python
from scraper import scrape
result, paths = scrape("https://example.com", "Extract page text", max_pages=1)
```

---

## ⚙️ Modes and Fallback

| Mode | Behavior |
|------|----------|
| `auto` (default) | Attempts configured cloud engines when available, then local engines. |
| `free_only` | Uses only local engines (scrapy, playwright). |
| `cloud_preferred` | Same priority as `auto`; falls back locally on quota/hard failures. |

### HTTP 402/429 and quota limits

- Cloud adapter limits are marked in `.scraper_state.json` for the run.
- The router logs the fallback and continues with the next eligible engine.
- Configurable via `config.yaml` under `limits`.

---

## 🛠️ Configuration (`config.yaml`)

Controls order, user agent, robots enforcement, timeouts, and domain overrides. `--mode` and `--engine` override config for a single command.

```yaml
mode: auto                # auto | free_only | cloud_preferred
engine_priority: [firecrawl, apify, playwright, scrapy]
fallback:
  on_limit_reached: true
  log_fallbacks: true
robots:
  user_agent: "CompliantFreeFirstScraper/0.1 (+contact@example.invalid)"
  respect: true
limits:
  timeout_seconds: 20
  requests_per_second: 1
  max_redirects: 5
output:
  directory: output
domain_overrides: {}
```

---

## 📂 Output

By default a job processes one target page. Use `--max-pages 10 --depth 1` for a bounded same-origin crawl.

Each URL is robots-checked before use. Output goes to `output/` as:

- `<target>.jsonl` — raw JSON lines
- `<target>.meta.json` — metadata (target, engine used, attempts, limits hit, item count)
- `<target>.csv` — flat table (when items contain only primitive values)

---

## 🔧 Python API

```python
from scraper import scrape

# Scrape a single page
result, paths = scrape(
    "https://example.com",
    "Extract page text",
    max_pages=1,
    mode="free_only",
    engine="scrapy",
)
```

Returns `(ScrapeResult, dict of output paths)`.

---

## 🚀 Distributed Workers (Phase 2)

For high-volume scraping, the system supports **distributed workers** with horizontal scaling:

### Quick Start

```bash
# Start distributed infrastructure (RabbitMQ, Redis, PostgreSQL, Prometheus, Grafana)
docker compose -f docker-compose.distributed.yml up -d

# Scale workers
docker compose -f docker-compose.distributed.yml up --scale worker=3 -d
```

### Features

- **Horizontal scaling**: Run multiple workers with independent browser pools
- **Task priority**: Detail pages (10) > List pages (5) > Other (1)
- **Distributed rate limiting**: Redis-backed token buckets per domain
- **Shared state**: PostgreSQL for crawl sessions, frontier, checkpoints
- **Monitoring**: Prometheus metrics + Grafana dashboards
- **Graceful shutdown**: Finish current task, re-queue unacked, save checkpoint

### Quick Start

```bash
# Start infrastructure
docker compose -f docker-compose.distributed.yml up -d

# Scale workers
docker compose -f docker-compose.distributed.yml up --scale worker=3 -d

# Access monitoring
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000 (admin/admin)
# RabbitMQ: http://localhost:15673 (guest/guest)
```

### Configuration

```bash
# Worker environment variables
WORKER_ID=worker-1              # Auto-generated if not set
MAX_CONCURRENT=5                # Max concurrent tasks
HEARTBEAT_INTERVAL=30           # Heartbeat interval (seconds)
METRICS_PORT=9090               # Prometheus metrics port
QUEUE_HOST=rabbitmq-distributed # RabbitMQ host
REDIS_URL=redis://redis-distributed:6379
POSTGRES_DSN=postgresql://scraper:scraper@postgres:5432/scraper_distributed
```

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Shared Infrastructure                     │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (crawl state)     RabbitMQ (task queue)          │
│  - crawl_sessions             - scrapy.tasks.detail (prio=10)│
│  - url_frontier               - scrapy.tasks.list   (prio=5) │
│  - visited_urls               - scrapy.tasks.other  (prio=1) │
│  - checkpoints                - scrapy.dlq (dead letter)     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │ Worker 1 │    │ Worker 2 │    │ Worker 3 │
        │ Browser  │    │ Browser  │    │ Browser  │
        │ Pool     │    │ Pool     │    │ Pool     │
        └──────────┘    └──────────┘    └──────────┘
```

---

## 🚀 Next improvements

1. Add a CLI command that resets a selected cloud adapter's local limit state.
2. Add structured metrics for engine choice, fallbacks, and request timing.
3. Build a small local dashboard for job history and output inspection.