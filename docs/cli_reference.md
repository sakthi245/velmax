# CLI Reference

## Overview

The hybrid-web-scraper provides a command-line interface for scraping web pages with multiple engine options and fallback strategies.

## Installation

```bash
cd hybrid_web_scraper
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

## Main Commands

### `scraper.run` - Main CLI Entry Point

```bash
python -m scraper.run [OPTIONS]
```

### Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--target` / `-t` | string | (required) | Target URL to scrape |
| `--goal` / `-g` | string | "Extract page text" | Extraction goal/instruction |
| `--schema` / `-s` | string | None | JSON schema for structured extraction |
| `--schema-file` | path | None | Path to JSON schema file |
| `--output-format` / `-f` | choice | jsonl | Output format: `json`, `jsonl`, `csv`, `parquet`, `db`, `all` |
| `--output-dir` / `-o` | path | `./output` | Output directory |
| `--engine` / `-e` | choice | auto | Force specific engine: `scrapy`, `playwright`, `firecrawl`, `crawlee`, `api` |
| `--mode` | choice | auto | Execution mode: `auto`, `runner_only`, `generate_only` |
| `--max-pages` | int | 10 | Maximum pages to scrape |
| `--depth` | int | 0 | Maximum crawl depth |
| `--headless` / `--no-headless` | flag | True | Browser headless mode |
| `--stealth` | flag | True | Enable stealth mode |
| `--proxy` | string | None | Proxy URL |
| `--proxy-type` | choice | auto | Proxy type: `datacenter`, `residential`, `mobile`, `auto` |
| `--timeout` | int | 20 | Request timeout in seconds |
| `--concurrency` | int | 10 | Max concurrent requests |
| `--max-pages` | int | 10 | Max pages to scrape |
| `--depth` | int | 0 | Max crawl depth |
| `--log-level` | choice | INFO | Log level: DEBUG, INFO, WARNING, ERROR |
| `--cache-dir` | path | ./scripts_cache | Script cache directory |
| `--fallback-threshold` | float | 0.7 | Quality threshold for fallback (0-1) |

### Examples

```bash
# Basic scraping
python -m scraper.run --target "https://example.com" --goal "Extract page title and content"

# With structured extraction
python -m scraper.run \
  --target "https://example.com" \
  --goal "Extract product name, price, and rating" \
  --schema '{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"rating":{"type":"string"}}}'

# Multi-page crawl
python -m scraper.run \
  --target "https://example.com/products" \
  --goal "Extract all product listings" \
  --max-pages 50 \
  --depth 2

# Use specific engine
python -m scraper.run \
  --target "https://example.com" \
  --goal "Extract page content" \
  --engine playwright \
  --mode runner_only

# Use Firecrawl for anti-bot sites
python -m scraper.run \
  --target "https://example.com" \
  --goal "Extract product data" \
  --engine firecrawl

# Output multiple formats
python -m scraper.run \
  --target "https://example.com" \
  --goal "Extract data" \
  --output-format jsonl,csv,parquet \
  --output-dir ./my_output
```

## Configuration File (`config.yaml`)

### Core Settings

```yaml
mode: auto                          # auto | free_only | cloud_preferred
engine_priority: [firecrawl, apify, playwright, scrapy]
fallback:
  on_limit_reached: true
  log_fallbacks: true
robots:
  user_agent: "HybridScraper/1.0 (+https://github.com/yourrepo)"
  respect: true
limits:
  timeout_seconds: 30
  requests_per_second: 2
  max_redirects: 5
output:
  directory: "./output"
  format: "jsonl"
```

### Engine Configurations

```yaml
engines:
  firecrawl:
    enabled: true
    api_url: "http://localhost:3002"
    api_key: "local-dev"
    formats: ["markdown", "html"]
    proxy: "auto"
    timeout: 120000
  
  playwright:
    enabled: true
    headless: true
    browser: "chromium"
    stealth_mode: true
    
  crawlee:
    enabled: true
    headless: true
    max_concurrency: 10
    session_pool_size: 50
    
  scrapy:
    enabled: true
    download_delay: 1
    concurrent_requests: 16
    autothrottle_enabled: true
```

## Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `FIRECRAWL_API_KEY` | Firecrawl API key | `local-dev` |
| `APIFY_TOKEN` | Apify API token | None |
| `SCRAPER_LOG_LEVEL` | Log level | INFO |
| `SCRAPER_OUTPUT_DIR` | Output directory | ./output |
| `SCRAPER_PROXY` | Proxy URL | None |

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | General error |
| 2 | Invalid arguments |
| 3 | Configuration error |
| 4 | All engines failed |
| 5 | Rate limited / quota exceeded |