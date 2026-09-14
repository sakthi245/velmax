# Custom Scripts - Universal Scraper

## Overview
This folder contains the universal scraping system that uses **all engines with auto-fallback**:
- **Scrapy** - Fast HTTP scraping
- **Playwright** - JavaScript rendering  
- **Crawlee** - Managed browser pool
- **Firecrawl** (Docker) - Anti-bot, PDF, heavy JS

## Quick Start

### Windows (PowerShell)
```powershell
# Simple scrape
.\scrape.ps1 -Query "product info" -Url "https://example.com" -Goal "Extract title and price"

# Multi-site (Amazon + Flipkart price comparison)
.\scrape.ps1 -MultiSite `
    -Site @("amazon", "https://amazon.in/s?k=phones+20000+25000") `
    -Site @("flipkart", "https://flipkart.com/search?q=phones+20000+25000") `
    -Goal "Extract phone name, price, rating, product link" `
    -Schema '{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"rating":{"type":"string"},"link":{"type":"string"}}}'

# With Firecrawl Docker (anti-bot sites)
.\scrape.ps1 -Url "https://amazon.in/product" -Goal "Extract product details" -UseFirecrawl
```

### Windows (Batch)
```cmd
scrape.bat "product info" --url "https://example.com" --goal "extract title and price"
```

### Linux/macOS
```bash
./scrape.sh "product info" --url "https://example.com" --goal "extract title and price"
```

## Features

### 1. **Auto Engine Fallback**
- Tries engines in priority order: `crawlee` → `playwright` → `scrapy` → `firecrawl`
- Automatically selects best engine based on URL/site:
  - Amazon/Flipkart/LiinkedIn → Firecrawl (if available) + Playwright
  - Dynamic JS sites → Playwright + Crawlee
  - PDFs → Firecrawl
  - Static sites → Scrapy (fastest)

### 2. **Firecrawl Docker Auto-Management**
- Auto-starts Docker stack if not running
- Auto-repairs common issues:
  - Missing Playwright browser (installs Chromium)
  - Health check failures (restarts services)
  - OOM kills (restarts with reduced workers)
- Reports failures with diagnostics

### 3. **Multi-Site Scraping**
- Scrape multiple sites with same goal
- Aggregates results per site
- Compares prices/products across sites

### 4. **Structured Extraction (Groq LLM)**
- Uses `groq/compound` (free tier: 14,400 req/day)
- Extracts structured data from scraped content
- Schema validation

### 5. **Output Management**
- All data saved to `../output/` directory
- Formats: JSONL, CSV, meta.json
- Timestamped filenames

## Command Reference

### Basic Options
| Option | Description |
|--------|-------------|
| `-Query` / `--query` | Search query/description |
| `-Url` / `--url` | Target URL (repeatable) |
| `-Goal` / `--goal` | Extraction instruction |
| `-Schema` / `--schema` | JSON schema for LLM extraction |
| `-MaxPages` / `--max-pages` | Max pages per URL (default: 10) |
| `-Engine` / `--engine` | Force engine: scrapy/playwright/crawlee/firecrawl |

### Firecrawl Options
| Option | Description |
|--------|-------------|
| `-UseFirecrawl` | Enable Firecrawl Docker (auto-starts) |
| `-NoFirecrawl` | Disable Firecrawl Docker |

### Multi-Site Mode
| Option | Description |
|--------|-------------|
| `-MultiSite` | Enable multi-site mode |
| `-Site` | Add site: `@("name", "url")` (repeatable) |

### Structured Extraction
| Option | Description |
|--------|-------------|
| `-Schema` | JSON schema for Groq LLM extraction |

## Examples

### 1. Price Comparison (Amazon + Flipkart)
```powershell
.\scrape.ps1 -MultiSite `
    -Site @("amazon", "https://amazon.in/s?k=phones+under+25000") `
    -Site @("flipkart", "https://flipkart.com/search?q=phones+under+25000") `
    -Goal "Extract phone name, price, rating, discount, product link, availability" `
    -Schema '{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"original_price":{"type":"string"},"rating":{"type":"string"},"discount":{"type":"string"},"link":{"type":"string"},"availability":{"type":"string"}}}' `
    -UseFirecrawl
```

### 2. Product Research with LLM Extraction
```powershell
.\scrape.ps1 `
    -Url "https://example-electronics.com/laptops" `
    -Goal "Extract all laptop models with specifications, prices, and key features" `
    -Schema '{"type":"object","properties":{"laptops":{"type":"array","items":{"type":"object","properties":{"model":{"type":"string"},"price":{"type":"string"},"cpu":{"type":"string"},"ram":{"type":"string"},"storage":{"type":"string"},"display":{"type":"string"},"gpu":{"type":"string"}}}}}}'
```

### 3. Competitor Analysis
```powershell
.\scrape.ps1 -MultiSite `
    -Site @("competitor1", "https://competitor1.com/products") `
    -Site @("competitor2", "https://competitor2.com/products") `
    -Site @("competitor3", "https://competitor3.com/products") `
    -Goal "Extract product names, prices, categories, and unique selling points" `
    -Schema '{"type":"object","properties":{"products":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"category":{"type":"string"},"usp":{"type":"string"}}}}}}'
```

### 4. With Firecrawl for Anti-Bot Sites
```powershell
# Amazon, Flipkart, LinkedIn, etc.
.\scrape.ps1 -Url "https://amazon.in/product/B08N5WRWNW" -Goal "Extract full product details" -UseFirecrawl
```

## Output Files
All results saved to `../output/`:
- `firecrawl_YYYYMMDD_HHMMSS.json` - Firecrawl raw results
- `crawlee_*.jsonl` - Crawlee results
- `playwright_*.jsonl` - Playwright results
- `scrapy_*.jsonl` - Scrapy results
- `*.csv` - CSV exports
- `*.meta.json` - Metadata

## Troubleshooting

### Firecrawl Docker Issues
```powershell
# Check Docker status
docker compose -f docker-compose.firecrawl.yml ps

# View logs
docker compose -f docker-compose.firecrawl.yml logs firecrawl-api

# Restart failed services
docker compose -f docker-compose.firecrawl.yml restart

# Full reset
docker compose -f docker-compose.firecrawl.yml down -v
docker compose -f docker-compose.firecrawl.yml up -d
```

### Common Issues
| Issue | Solution |
|-------|----------|
| Firecrawl OOM kill | Reduce workers in docker-compose.yml |
| Playwright browser missing | Script auto-installs, or run `playwright install chromium` |
| Groq rate limit | Wait or reduce concurrent requests |
| Anti-bot blocking | Use `-UseFirecrawl` or add delays |

## Requirements
- Python 3.10+
- Virtual environment activated (`.venv`)
- Dependencies: `pip install -e ".[all]"`
- Playwright: `playwright install chromium`
- Groq API key in `.env.firecrawl`
- Docker Desktop (for Firecrawl)

## File Structure
```
custom_scripts/
├── universal_scraper.py    # Main orchestration engine
├── scrape.ps1              # PowerShell wrapper (Windows)
├── scrape.bat              # Batch wrapper (Windows)
├── scrape.sh               # Shell wrapper (Linux/macOS)
└── README.md               # This file
```

## Integration with Main Project
The universal scraper uses the project's core modules:
- `scraper.api.scrape()` / `scrape_async()`
- `scraper.engines.groq_llm_engine.CrawleeLLMCrawler`
- `scraper.config.ScraperConfig`
- Engine registry with fallback routing