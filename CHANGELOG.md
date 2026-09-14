# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0] - 2024-XX-XX

### Added
- **Hybrid Architecture**: Option A (Universal Runner) + Option B (Script Generator) with smart fallback
- **Multi-Engine Support**: Playwright, Crawlee, HTTP, Firecrawl, Scrapy, API engines
- **Structured LLM Extraction**: JSON schema-based extraction with Groq models
- **Search Pipeline**: TinyFish + SerpAPI with query expansion and relevance ranking
- **Browser Pool**: Adaptive browser pool with resource blocking and stealth modes
- **Distributed Workers**: Horizontal scaling with RabbitMQ, Redis, PostgreSQL
- **Output Pipeline**: JSONL, CSV, Parquet, Excel output formats
- **Deduplication**: SQLite-based URL deduplication with TTL
- **Circuit Breakers**: Per-engine circuit breakers with automatic recovery
- **Rate Limiting**: Token bucket rate limiting per domain
- **Observability**: Prometheus metrics, structured logging, OpenTelemetry support

### Changed
- **Breaking**: Refactored engine registry to v2 with health monitoring
- **Breaking**: Updated configuration schema to Pydantic v2
- **Breaking**: Changed CLI entry point to `velmax` command
- Improved fallback chain with quality-based engine selection
- Enhanced error handling with structured error categories

### Fixed
- Engine registry test pollution (singleton state isolation)
- Schema validation for array-type JSON schemas
- Mutable default arguments in dataclasses
- Jinja2 autoescape breaking generated Python code

### Known Issues
- Relevance ranker JSON validation with Groq `openai/gpt-oss-20b`
- Playwright CAPTCHA handling for DuckDuckGo search
- Firecrawl Docker integration requires Docker Desktop

## [0.2.0] - 2024-XX-XX

### Added
- Universal Runner with multi-engine fallback
- Basic Firecrawl and Apify cloud adapters
- Robots.txt compliance
- Basic output formats (JSONL, CSV)

### Changed
- Migrated from Scrapy-only to multi-engine architecture

## [0.1.0] - 2024-XX-XX

### Added
- Initial Scrapy-based scraper
- Basic CLI interface
- Configuration via YAML
- Robots.txt checking