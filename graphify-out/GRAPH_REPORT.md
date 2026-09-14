# Graph Report - hybrid_web_scraper  (2026-09-14)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 3440 nodes · 8032 edges · 168 communities (148 shown, 18 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 610 edges (avg confidence: 0.93)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `daa8f370`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70
- Community 71
- Community 72
- Community 73
- Community 74
- Community 75
- Community 76
- Community 77
- Community 78
- Community 79
- Community 80
- Community 81
- Community 82
- Community 83
- Community 84
- Community 85
- Community 86
- Community 87
- Community 88
- Community 89
- Community 90
- Community 91
- Community 92
- Community 93
- Community 94
- Community 95
- Community 96
- Community 97
- Community 98
- Community 99
- Community 100
- Community 101
- Community 102
- Community 103
- Community 104
- Community 105
- Community 106
- Community 107
- Community 108
- Community 109
- Community 110
- Community 111
- Community 112
- Community 113
- Community 114
- Community 115
- Community 116
- Community 117
- Community 118
- Community 119
- Community 120
- Community 121
- Community 122
- Community 123
- Community 124
- Community 125
- Community 126
- Community 127
- Community 128
- Community 129
- Community 130
- Community 131
- Community 132
- Community 133
- Community 134
- Community 135
- Community 136
- Community 137
- Community 138
- Community 139
- Community 140
- Community 141
- Community 142
- Community 143
- Community 144
- Community 145
- Community 146
- Community 147
- Community 148
- Community 149
- Community 150
- Community 151
- Community 152
- Community 153
- Community 154
- Community 155
- Community 156
- Community 157
- Community 158
- Community 159
- Community 160
- Community 161
- Community 162
- Community 163
- Community 164
- Community 167

## God Nodes (most connected - your core abstractions)
1. `EngineConfig` - 116 edges
2. `EngineType` - 112 edges
3. `UniversalConfig` - 68 edges
4. `UniversalRequest` - 59 edges
5. `EngineMetadata` - 55 edges
6. `DeepSiteProfiler` - 54 edges
7. `StealthManager` - 52 edges
8. `BrowserEngine` - 52 edges
9. `EngineCapability` - 49 edges
10. `ScrapeRequest` - 48 edges

## Surprising Connections (you probably didn't know these)
- `DeepSiteProfiler` --uses--> `AntiBotLevel`  [INFERRED]
  scripts/profiler.py → scraper/config/schemas.py
- `DeepSiteProfiler` --uses--> `DeepSiteProfile`  [INFERRED]
  scripts/profiler.py → scraper/config/schemas.py
- `DeepSiteProfiler` --uses--> `EngineType`  [INFERRED]
  scripts/profiler.py → scraper/config/schemas.py
- `DeepSiteProfiler` --uses--> `FallbackContext`  [INFERRED]
  scripts/profiler.py → scraper/config/schemas.py
- `DeepSiteProfiler` --uses--> `ProfileDepth`  [INFERRED]
  scripts/profiler.py → scraper/config/schemas.py

## Import Cycles
- None detected.

## Communities (168 total, 18 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (25): BrowserFingerprint, FingerprintGenerator, FingerprintRotator, Any, Page, Generate script for manual CAPTCHA fallback handling., Wait for Cloudflare challenge to complete (manual solve)., Wait for manual CAPTCHA solve. Args: page: Playwright page timeout: Timeout in… (+17 more)

### Community 1 - "Community 1"
Cohesion: 0.11
Nodes (27): FilteringBoundLogger, BrowserEngineConfig, EngineCapability, AuthConfig, create_adaptive_pool(), Factory function to create adaptive browser pool., SearchResult, EngineMetadata (+19 more)

### Community 2 - "Community 2"
Cohesion: 0.06
Nodes (31): CheckpointConfig, QueueConfig, TaskPriority, WorkerConfig, Implementation of add_urls for abstract base class., create_coordinator(), create_queue_manager(), create_task_from_url() (+23 more)

### Community 3 - "Community 3"
Cohesion: 0.07
Nodes (28): DataValidation, DataNormalizer, Any, Apply explicit normalization rule., Normalize datetime to ISO 8601 UTC., Normalize to YYYY-MM-DD format., Normalize to HH:MM:SS format., Extract and normalize currency value. (+20 more)

### Community 4 - "Community 4"
Cohesion: 0.06
Nodes (23): BaseHybridEngineV2, BaseManagedEngineV2, CrawlStrategy, PageResult, CrawleeCrawlerState, create_managed_engine(), ManagedEngine, default_handler() (+15 more)

### Community 5 - "Community 5"
Cohesion: 0.06
Nodes (21): Execute interaction sequence on a new page., InfiniteScrollHandler, InteractionExecutor, InteractionResult, InteractionSequence, InteractionStep, _pagination_click(), PaginationHandler (+13 more)

### Community 6 - "Community 6"
Cohesion: 0.06
Nodes (8): AuthToken, Cookie, ProxySessionManager, Any, Session, SessionContext, SessionManager, set_cookies()

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (26): CloudEngineConfig, SiteProfile, Browser-based profiling using Playwright for JS-heavy sites., Return a default profile when all profiling fails., Selects optimal engine based on profile and historical performance., Select best engine with optimized config., Quick analysis using HEAD + single GET, with browser fallback on failure., Quick analysis using HTTP requests. (+18 more)

### Community 8 - "Community 8"
Cohesion: 0.08
Nodes (14): AsyncClient, RobotFileParser, BaseHTTPEngineV2, fetch_one(), HTTPEngine, _fetch(), fetch_one(), Any (+6 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (25): BaseModelMixin, model_validator, QualityScorer, Score based on content richness., Score based on media presence., Score based on metadata completeness., Score based on data accuracy/validity., Validate price fields. (+17 more)

### Community 10 - "Community 10"
Cohesion: 0.10
Nodes (15): DeepSiteProfiler, LLMAnalysis, Any, DeepSiteProfile, Deep analysis for script generation., Fetch with multiple engines in parallel., Select best fetch result., Analyze site characteristics. (+7 more)

### Community 11 - "Community 11"
Cohesion: 0.09
Nodes (12): BaseEngine, EngineMetadata, ScrapeRequest, ScrapeResponse, Legacy-compatible scrape method., FirecrawlEngine, Legacy-compatible scrape method accepting ScrapeRequest from base.py., record_engine_init() (+4 more)

### Community 12 - "Community 12"
Cohesion: 0.09
Nodes (31): GenerationRequirements, DeepSiteProfile, GenerationMetadata, GenerationRequirements, GenerationStrategy, cmd_cache(), cmd_generate(), cmd_generate_from_profile() (+23 more)

### Community 13 - "Community 13"
Cohesion: 0.07
Nodes (29): create_api_engine(), Factory function to create API engine., create_browser_engine(), Factory function to create browser engine., CloudEngine, CloudEngineConfig, create_cloud_engine(), Factory function to create cloud engine. (+21 more)

### Community 14 - "Community 14"
Cohesion: 0.07
Nodes (19): field, EngineType, BaseEngine, EngineFactory, ABC, EngineRegistryV2, Any, Get existing instance or create with default config. (+11 more)

### Community 15 - "Community 15"
Cohesion: 0.11
Nodes (23): datetime, ScraperService, Streaming version of the scraper service with real-time updates., Start a scraping task with real-time streaming updates., StreamingScraperService, OutputFormat, field_validator, model_validator (+15 more)

### Community 16 - "Community 16"
Cohesion: 0.07
Nodes (16): APIEngine, MockModeConfig, Update rate limiter from response headers., Enable mock mode with HAR file., Load HAR file for mock mode., AdaptiveRateLimiter, CacheConfig, ConnectionPoolConfig (+8 more)

### Community 17 - "Community 17"
Cohesion: 0.09
Nodes (30): PermissionError, _Links, Any, HTMLParser, Path, _same_origin_links(), scrape(), scrape_async() (+22 more)

### Community 18 - "Community 18"
Cohesion: 0.09
Nodes (42): get_low_memory_config(), Optimized configuration for 8GB RAM systems with 6GB Docker allocation. This…, APIEngineConfig, ConcurrencyConfig, ContentFilters, DeduplicationConfig, DomainRules, EngineAttempt (+34 more)

### Community 19 - "Community 19"
Cohesion: 0.08
Nodes (21): DeepSiteProfiler, Page, Launch Playwright browser with stealth configuration., Create browser context with stealth settings., Navigate to URL and perform initial analysis., Analyze additional pages for deep profiling., Analyze a single page., Detect JavaScript framework used by the site. (+13 more)

### Community 20 - "Community 20"
Cohesion: 0.08
Nodes (12): RuntimeError, BaseCloudEngineV2, Get a context from the adaptive pool., InteractionSequence, Navigate to URL and extract content., Scrape implementation - navigates to URL and extracts content., Implementation of scrape for abstract base class., BrowserRequest (+4 more)

### Community 21 - "Community 21"
Cohesion: 0.09
Nodes (24): CacheConfig, Configuration for script cache., GeneratedScript, GenerationMetadata, GenerationRequirements, Script generation module for the universal scraper., Generate a complete scraper script from a site profile., Select the best engine for the given profile and requirements. (+16 more)

### Community 22 - "Community 22"
Cohesion: 0.09
Nodes (16): Any, UniversalResult, FailureClassifier, Any, Exception, Classifies failures to determine fallback strategy., Suggest alternative engine based on failure category., Classify failure and determine fallback action. (+8 more)

### Community 23 - "Community 23"
Cohesion: 0.11
Nodes (6): BaseBrowserEngineV2, BrowserContextWrapper, Any, Manually trigger context recycle., InteractionResult, InteractionSequence

### Community 24 - "Community 24"
Cohesion: 0.09
Nodes (18): APIEndpointPattern, Return context to the adaptive pool., Get adaptive pool metrics., BrowserEngine, create_context(), Any, Page, PlaywrightBrowserContext (+10 more)

### Community 25 - "Community 25"
Cohesion: 0.09
Nodes (3): BaseAPIEngineV2, APIEndpoint, APIEngine

### Community 26 - "Community 26"
Cohesion: 0.10
Nodes (21): Element, HTTPCacheConfig, check_robots(), discover_sitemaps(), get_crawl_delay(), parse_sitemap(), Fetch sitemap content., Check if root is a sitemap index. (+13 more)

### Community 27 - "Community 27"
Cohesion: 0.10
Nodes (20): Pattern, CategoryConfig, CategoryMapper, map_category(), Any, Build regex patterns for each category., Load custom taxonomy from JSON file., Map text to a product category. (+12 more)

### Community 28 - "Community 28"
Cohesion: 0.10
Nodes (16): Synchronous scrape function - re-exported from scraper.api module., scrape(), scrape_async(), ConnectionManager, handle_message(), handle_websocket(), MessageType, Enum (+8 more)

### Community 29 - "Community 29"
Cohesion: 0.11
Nodes (6): BehavioralMimicry, Locator, High-level behavioral mimicry for browser automation., Execute a single interaction step with human-like behavior., Execute a step with human-like behavior., Simulate a thinking pause.

### Community 30 - "Community 30"
Cohesion: 0.10
Nodes (15): CacheEntry, Any, Path, A cache entry with metadata., Check if entry is expired., Update last accessed time and increment access count., Cache for storing generated scripts and profiles., Get cache file path for a key. (+7 more)

### Community 31 - "Community 31"
Cohesion: 0.15
Nodes (17): extract_with_schema(), ExtractionMethod, ExtractionResult, ExtractionSchema, HybridExtractor, infer_and_extract(), LLMExtractor, Any (+9 more)

### Community 32 - "Community 32"
Cohesion: 0.08
Nodes (7): PlaywrightEngine, Any, HTMLParser, Legacy sync interface for backward compatibility, record_from_html(), ScrapyEngine, _Text

### Community 33 - "Community 33"
Cohesion: 0.12
Nodes (6): AbstractIncomingMessage, Any, Register a task as being processed by this worker., Mark a task as completed., WorkerCoordinator, WorkerInfo

### Community 34 - "Community 34"
Cohesion: 0.11
Nodes (19): ExecutionConfig, ExecutionResult, GeneratedScriptExecutor, Any, Path, Validate a script before execution., Execute script with progress monitoring., Execute script with retry logic. (+11 more)

### Community 35 - "Community 35"
Cohesion: 0.08
Nodes (9): ObservabilityConfig, ObservabilityConfig, BaseEngineV2, EngineMetrics, ABC, RateLimitConfig, RetryPolicy, V2 version of ScrapyEngine - inherits from BaseEngineV2 with circuit breaker,… (+1 more)

### Community 36 - "Community 36"
Cohesion: 0.15
Nodes (10): CacheEntry, CacheConfig, CachedScript, CacheEntry, GeneratedScript, Any, Enum, GeneratedScript (+2 more)

### Community 37 - "Community 37"
Cohesion: 0.08
Nodes (15): Configuration for query expander., Configuration for relevance ranker., create_query_expander_engine(), QueryExpanderConfig, QueryExpanderEngine, Factory function to create query expander engine., Groq-powered query expansion engine (free tier available)., Initialize Groq client. (+7 more)

### Community 38 - "Community 38"
Cohesion: 0.21
Nodes (17): create_deduplicator(), DedupConfig, BaseArticle, BaseListing, BaseProduct, BaseReview, field_validator, QualityConfig (+9 more)

### Community 39 - "Community 39"
Cohesion: 0.11
Nodes (15): EnrichmentConfig, EnrichmentPipeline, Any, Apply all enabled enrichment steps., Extract entities (emails, phones, URLs) from text fields., Categorize item based on text content using hybrid approach (rules + ML)., Rule-based category matching with confidence scores., ML-based category classification with confidence scores. (+7 more)

### Community 40 - "Community 40"
Cohesion: 0.10
Nodes (5): Checkpoint, CrawlSession, CrawlStateManager, Any, URLFrontierEntry

### Community 41 - "Community 41"
Cohesion: 0.15
Nodes (15): Decimal, Currency, NormalizedPrice, extract_prices(), parse_price_string(), PriceConfig, PriceNormalizer, Normalize multiple price values. (+7 more)

### Community 42 - "Community 42"
Cohesion: 0.12
Nodes (16): DateConfig, DateNormalizer, extract_dates(), parse_date_string(), Normalize multiple date values., Extract all dates from text content., Parse relative date expressions., Parse time from text. (+8 more)

### Community 43 - "Community 43"
Cohesion: 0.12
Nodes (15): DataQualityPipeline, ProcessingResult, Any, Process multiple items., Extract and normalize prices from item., Attach normalized prices to item., Extract and normalize dates from item., Attach normalized dates to item. (+7 more)

### Community 44 - "Community 44"
Cohesion: 0.08
Nodes (5): Protocol, BrowserContext, CloudEngine, HybridEngine, ManagedEngine

### Community 45 - "Community 45"
Cohesion: 0.12
Nodes (13): ArticleDeduplicator, ContentDeduplicator, ProductDeduplicator, Add item to deduplication index., Normalize title for comparison., Generate fingerprint for content similarity., Calculate string similarity ratio., Clear all deduplication data. (+5 more)

### Community 46 - "Community 46"
Cohesion: 0.13
Nodes (15): main(), Main scraper orchestrating all engines with fallback, Initialize all components, Universal Scraper - Uses all engines with auto-fallback Supports: Scrapy,…, Read Groq key from .env.firecrawl, Determine best engines for the task, Scrape with automatic engine fallback, Scrape using local engines (scrapy, playwright, crawlee) (+7 more)

### Community 47 - "Community 47"
Cohesion: 0.12
Nodes (20): benchmark_engines(), _run(), BenchmarkResult, LoadTester, make_request(), make_request_limited(), main(), Any (+12 more)

### Community 48 - "Community 48"
Cohesion: 0.11
Nodes (13): AdaptiveBrowserPool, Any, Detect available system memory using psutil., Calculate safe memory budget for browser pool., Start the pool and background tasks., Stop the pool and cleanup all contexts., Get current process memory in MB., Update memory usage for a context. (+5 more)

### Community 49 - "Community 49"
Cohesion: 0.12
Nodes (13): GoalParser, Parses natural language goals into structured entities., Compile regex patterns for extraction., Parse a natural language goal into structured entities using Groq first, then…, Original regex-based parsing as fallback., Extract product category from goal., Extract brand from goal., Extract price range from goal. (+5 more)

### Community 50 - "Community 50"
Cohesion: 0.10
Nodes (13): CrawleeLLMCrawler, demo(), ExtractResult, GroqLLMEngine, Generate search queries from natural language, Crawlee crawler enhanced with Groq LLM for Extract/Agent features, Scrape URL and optionally extract structured data using Groq, Run autonomous agent task with Groq (+5 more)

### Community 51 - "Community 51"
Cohesion: 0.11
Nodes (9): RateLimitConfig, RetryPolicy, ContentHasher, create_dedup_manager(), DedupConfig, DeduplicationManager, Any, Path (+1 more)

### Community 52 - "Community 52"
Cohesion: 0.12
Nodes (8): Remove expired entries., DomainRateLimiter, LRUCache, Any, Thread-safe LRU cache with TTL support., Generate cache key from request., Evict least recently used entry., Invalidate cache entries.

### Community 53 - "Community 53"
Cohesion: 0.10
Nodes (13): Manages secrets with support for multiple backends and rotation., Set a secret (for testing or runtime configuration)., Generate a cryptographically secure random secret., Generate an API key with prefix., Hash a secret for storage., Verify a secret against its hash., Check if a secret needs rotation., Get list of keys that need rotation. (+5 more)

### Community 54 - "Community 54"
Cohesion: 0.11
Nodes (14): BrowserContextConfig, PlaywrightBrowser, Launch the Playwright browser with configured options., PlaywrightSearchConfig, PlaywrightSearchEngine, PlaywrightBrowser, Initialize the search engine with browser and pool., Shutdown the search engine and cleanup resources. (+6 more)

### Community 55 - "Community 55"
Cohesion: 0.16
Nodes (10): ExtractionField, OutputPipeline, Any, Extract HTML content from result data., Convert JSON Schema to ExtractionSchema., Apply enrichment steps., Write result to file in specified format., Process results through: Raw → Cleaned → Validated → Enriched → Format (+2 more)

### Community 56 - "Community 56"
Cohesion: 0.11
Nodes (13): AlertManager, configure_json_formatter(), configure_log_levels(), configure_log_sampling(), configure_observability(), HARCapturer, init_observability(), ObservabilityConfig (+5 more)

### Community 57 - "Community 57"
Cohesion: 0.12
Nodes (15): input, rest_infer_extract(), ExtractionFieldInput, ExtractionResultType, ExtractionSchemaInput, InteractionResultType, InteractionSequenceInput, InteractionStepInput (+7 more)

### Community 58 - "Community 58"
Cohesion: 0.13
Nodes (11): create_scrape_task(), create_task_updates_stream(), get_task_status(), list_tasks(), Any, Manages long-running tasks with real-time streaming updates., Create a new streaming task., Create a new scraping task with streaming updates. (+3 more)

### Community 59 - "Community 59"
Cohesion: 0.15
Nodes (8): load_config(), EngineRegistry, EngineSelector, test_engine_metadata(), test_selector_creation(), test_selector_explicit_engine(), test_selector_js_routes_to_crawlee(), test_selector_pdf_routes_to_firecrawl()

### Community 60 - "Community 60"
Cohesion: 0.13
Nodes (13): CacheEntry, get_cache(), LLMResponseCache, Any, LLM Response Cache for caching LLM responses to avoid redundant API calls., Load cache entries from disk on startup., Remove oldest entries if cache exceeds size limit., Clear all cache entries. (+5 more)

### Community 61 - "Community 61"
Cohesion: 0.10
Nodes (16): auto_reload_on_import(), decorator(), wrapper(), ModuleReloader, Path, Module reload utility for development and testing., Decorator to auto-reload modules on import (for development)., Utility for reloading modules during development and testing. (+8 more)

### Community 62 - "Community 62"
Cohesion: 0.12
Nodes (10): DockerFirecrawlManager, Ensure ghcr.io authentication, Diagnose and report Docker failures, Restart only failed services, Ensure Firecrawl is running, start if not, Manages Firecrawl Docker container with auto-repair, Check if all Firecrawl services are healthy, Start Firecrawl stack with auto-repair (+2 more)

### Community 63 - "Community 63"
Cohesion: 0.11
Nodes (10): load_config(), Path, ScraperConfig, ABC, Any, Legacy sync interface - use BaseEngine for new code, Sync wrapper for async scrape, ScrapingEngine (+2 more)

### Community 64 - "Community 64"
Cohesion: 0.12
Nodes (11): _call(), Any, Call an API endpoint with authentication., Apply authentication to headers., Match URL against endpoint patterns., Replay request from HAR file., Replay a previously captured request., Internal implementation of API call. (+3 more)

### Community 65 - "Community 65"
Cohesion: 0.11
Nodes (9): PluginInstance, PluginManager, PluginMetadata, Manages plugin lifecycle: loading, initialization, execution., Add a directory to search for plugins., Load and initialize a plugin., Execute all hooks of a given type., Initialize all loaded plugins. (+1 more)

### Community 66 - "Community 66"
Cohesion: 0.28
Nodes (7): create_selector_engine(), Any, Enum, SelectorConfig, SelectorEngine, SelectorResult, SelectorType

### Community 68 - "Community 68"
Cohesion: 0.17
Nodes (9): Any, request_context(), RequestContext, RequestLogger, trace_span(), traced(), decorator(), async_wrapper() (+1 more)

### Community 69 - "Community 69"
Cohesion: 0.13
Nodes (14): FastAPI, create_app(), create_graphql_app(), get_engines(), health(), rest_infer(), EngineMetadataType, EngineStatus (+6 more)

### Community 70 - "Community 70"
Cohesion: 0.15
Nodes (10): FallbackConfig, AllEnginesFailed, EngineAttempt, FallbackChain, Any, Exception, Executes engine chain with rich context capture., Execute engine chain with fallback. (+2 more)

### Community 71 - "Community 71"
Cohesion: 0.14
Nodes (12): Any, Enforce rate limiting., Build search parameters for SerpAPI., Parse SerpAPI response into SearchResult objects., Search SerpAPI and return results using official SDK., Search result from SerpAPI., Configuration for SerpAPI Search Engine (using official SDK)., SerpAPI Search Engine - Uses official SerpAPI Python SDK. (+4 more)

### Community 72 - "Community 72"
Cohesion: 0.13
Nodes (11): InputSanitizer, Sanitizes and validates input data., Pre-compile regex patterns., Sanitize HTML content., Sanitize command injection attempts., Sanitize filename for safe storage., Sanitize text for safe logging., Basic text sanitization. (+3 more)

### Community 73 - "Community 73"
Cohesion: 0.18
Nodes (11): BenchmarkRunner, make_request(), main(), Any, ProfileDepth, Benchmark browser pool memory usage with concurrent scrapes., Benchmark fallback latency overhead., Benchmark script generation time. (+3 more)

### Community 74 - "Community 74"
Cohesion: 0.30
Nodes (16): ArgumentParser, create_argument_parser(), get_default_config(), load_config_from_file(), merge_configs(), validate_config(), AntiBotLevel, BrowserType (+8 more)

### Community 75 - "Community 75"
Cohesion: 0.11
Nodes (10): Event, GracefulShutdown, Manages graceful shutdown of the application., Register a task to run during shutdown., Remove a shutdown task., Handle shutdown signals., Install signal handlers for graceful shutdown., Restore original signal handlers. (+2 more)

### Community 76 - "Community 76"
Cohesion: 0.14
Nodes (12): ContextCookies, ContextMetrics, CookieData, PlaywrightBrowserContext, Get a context from the pool (creates new if needed)., Cookie data for persistence., Create a new browser context., Check if context is still healthy. (+4 more)

### Community 77 - "Community 77"
Cohesion: 0.12
Nodes (4): Any, Record task start and return context for recording completion., Record task completion with metrics., WorkerMetrics

### Community 78 - "Community 78"
Cohesion: 0.12
Nodes (7): get_security_manager(), Validate a URL against security policies., Central security manager coordinating all security features., Validate an incoming request., Get or create the default security manager., SecurityManager, validate_url()

### Community 79 - "Community 79"
Cohesion: 0.24
Nodes (15): generate_script(), main(), profile_site(), Any, Path, ProfileDepth, Profile a site deeply, Universal Scraper V2 - Hybrid Architecture (Option A + Option B with Smart… (+7 more)

### Community 81 - "Community 81"
Cohesion: 0.15
Nodes (5): ErrorHandlingHook, Any, RateLimitMiddleware, Middleware for rate limiting requests., Hook for handling errors and retries.

### Community 82 - "Community 82"
Cohesion: 0.15
Nodes (8): HealthChecker, Run all registered health checks., Get overall system health status., Get latest health check results., Start periodic health checks., Stop periodic health checks., Manages health checks for the application., Run a single health check.

### Community 83 - "Community 83"
Cohesion: 0.12
Nodes (9): HumanBehaviorEngine, Engine for generating human-like browser interactions., Generate a bezier curve path for natural mouse movement., Generate typing actions with human-like timing and occasional typos., Calculate reading time based on text length., Generate a random mouse position within viewport., Generate micro-jitter around a position., Generate a thinking pause duration. (+1 more)

### Community 84 - "Community 84"
Cohesion: 0.17
Nodes (5): HTTPEngineConfig, CircuitBreakerRetryPolicy, RetryPolicy, stop_base, wait_base

### Community 85 - "Community 85"
Cohesion: 0.18
Nodes (9): BaseException, RetryCallState, execute_with_retry(), execute_with_retry_async(), Any, Exception, retry_with_context(), RetryCondition (+1 more)

### Community 86 - "Community 86"
Cohesion: 0.27
Nodes (4): Any, ValidationResult, DataValidator, ValidationResult

### Community 87 - "Community 87"
Cohesion: 0.19
Nodes (6): record_scrape(), set_circuit_state(), set_engine_health(), test_circuit_state(), test_engine_health(), test_record_scrape()

### Community 88 - "Community 88"
Cohesion: 0.15
Nodes (7): Return context to pool with health check., Check if context should be recycled., Recycle a specific context., Recycle one idle context., Scale down idle contexts when memory pressure or high idle ratio., Scale up when queue builds up., Dynamically adjust idle timeout based on scaling.

### Community 89 - "Community 89"
Cohesion: 0.18
Nodes (8): GroqEntityExtractor, Lazy initialization of clients., Call Groq API with given model., Call OpenRouter API with auto model selection., Parse Groq response into ParsedGoal., Extract entities from goal using Groq with fallback chain., Fallback to regex-based parsing., Universal entity extraction using Groq LLM for ANY category.

### Community 90 - "Community 90"
Cohesion: 0.21
Nodes (9): Any, Enforce rate limiting (30 requests/minute = 2 seconds between requests)., Build search parameters for TinyFish API., Parse TinyFish API response into SearchResult objects., Search result from TinyFish., Search TinyFish and return results using official SDK., TinyFish Search Engine - Uses official TinyFish Python SDK., TinyFishSearchEngine (+1 more)

### Community 91 - "Community 91"
Cohesion: 0.22
Nodes (10): ExecutionMode, Enum, GenerationRequirements, ValidationResult, _check_syntax(), _run_lint(), _run_tests(), _run_type_check() (+2 more)

### Community 92 - "Community 92"
Cohesion: 0.16
Nodes (14): clear_module_cache(), fresh_modules(), mock_firecrawl_env(), fixture, pytest_configure(), Pytest configuration with module reloading support., Mock Firecrawl environment for testing without Docker., Clear module cache before test session. (+6 more)

### Community 93 - "Community 93"
Cohesion: 0.13
Nodes (8): Tests for PlaywrightSearchEngine., Test PlaywrightSearchConfig defaults., Test engine can be created., Test engine metadata., Test engine initialization., Test engine shutdown., Test search returns empty when CAPTCHA not solved., TestPlaywrightSearchEngine

### Community 94 - "Community 94"
Cohesion: 0.15
Nodes (6): WebSocket, Subscribe to task updates via WebSocket., Subscription, sender(), WebSocketManager, subscribe_to_task()

### Community 95 - "Community 95"
Cohesion: 0.23
Nodes (7): CircuitBreaker, asyncio, test_circuit_breaker_half_open(), fail(), test_circuit_breaker_opens_after_failures(), fail(), test_router_initialization()

### Community 97 - "Community 97"
Cohesion: 0.14
Nodes (6): EnginePlugin, ExampleStealthPlugin, Check if engine is healthy., Example custom stealth plugin., Base class for engine plugins., Execute scraping with this engine.

### Community 98 - "Community 98"
Cohesion: 0.14
Nodes (7): Plugin, ABC, Discover all plugin classes in plugin directories., Base class for all plugins., Return plugin metadata., Initialize the plugin. Return True if successful., Shutdown the plugin. Return True if successful.

### Community 99 - "Community 99"
Cohesion: 0.20
Nodes (4): HTTPCache, Any, Disk-based HTTP cache with TTL and size limits., Generate cache key from URL and relevant headers.

### Community 100 - "Community 100"
Cohesion: 0.15
Nodes (7): CSPBuilder, Builds Content Security Policy headers., Parse a CSP policy string., Add values to a directive., Remove a value from a directive., Build CSP header value., Create a permissive CSP for development.

### Community 101 - "Community 101"
Cohesion: 0.24
Nodes (13): asyncio, integration, Test all search engines are registered., Test query expander with real Groq API., Test relevance ranker with real Groq API., Test playwright search with real browser (expects CAPTCHA)., Test full search pipeline with real APIs., test_engine_registry() (+5 more)

### Community 102 - "Community 102"
Cohesion: 0.19
Nodes (7): ndarray, EmbeddingDedup, Embedding-based semantic deduplication using SentenceTransformers., Get embedding for text with caching., Compute cosine similarity between two texts., Check if two texts are semantic duplicates., Batch check similarity against reference texts.

### Community 103 - "Community 103"
Cohesion: 0.35
Nodes (4): ConfigLoader, Any, Namespace, Path

### Community 105 - "Community 105"
Cohesion: 0.18
Nodes (8): Page, Search DuckDuckGo and return results., Search result from DuckDuckGo., Extract search results from the page., SearchResult, Search multiple queries., Test search returns results when CAPTCHA solved., Test SearchResult dataclass.

### Community 106 - "Community 106"
Cohesion: 0.15
Nodes (9): create_plugin_manager(), get_plugin_manager(), PluginRegistry, Registry for managing plugin discovery and loading., Load all builtin plugins., Load plugins from configuration., Register a custom plugin class directly., Create and initialize plugin manager with configuration. (+1 more)

### Community 107 - "Community 107"
Cohesion: 0.27
Nodes (12): check_cpu(), check_database(), check_disk_space(), check_memory(), check_rabbitmq(), check_redis(), HealthCheckResult, lifespan() (+4 more)

### Community 108 - "Community 108"
Cohesion: 0.15
Nodes (11): InputValidationError, Exception, Base exception for security-related errors., Raised when SSRF protection blocks a request., Raised when input validation fails., Raised when a secret is not found., Prevent path traversal., Scan request body for threats. (+3 more)

### Community 109 - "Community 109"
Cohesion: 0.19
Nodes (7): Calculate Hamming distance between two fingerprints., Check if two fingerprints are similar within threshold., SimHash implementation for near-duplicate detection., Tokenize text into shingles., Hash a token to integer., Compute SimHash for text., SimHash

### Community 110 - "Community 110"
Cohesion: 0.17
Nodes (6): handle_request(), Discover API endpoints by intercepting network traffic., Intercept network traffic to discover API endpoints., Determine if a request is an API request., Internal implementation of endpoint discovery., Internal implementation of network interception.

### Community 111 - "Community 111"
Cohesion: 0.21
Nodes (6): ActionType, create_interaction_executor(), InteractionConfig, Enum, Page, Factory function to create behavioral mimicry executor.

### Community 112 - "Community 112"
Cohesion: 0.23
Nodes (6): IPValidator, Validates IP addresses against allow/block lists and security policies., Compile allowed and blocked network ranges., Validate an IP address against allow/block lists., Validate hostname format., Check for suspicious URL patterns.

### Community 113 - "Community 113"
Cohesion: 0.20
Nodes (6): Get content hash key., Get SimHash for content with caching., Check if content is a duplicate using hybrid approach. Returns (is_duplicate,…, Check exact content match., Check for near-duplicate using SimHash., Check for semantic similarity using embeddings.

### Community 114 - "Community 114"
Cohesion: 0.24
Nodes (4): Infers extraction schemas from HTML content using ML/heuristics., Infer extraction schema from HTML content., Use LLM to refine inferred schema., SchemaInferenceEngine

### Community 115 - "Community 115"
Cohesion: 0.18
Nodes (5): ExporterPlugin, JSONExporter, Base class for exporter plugins., Export data to specified format., Export data to JSON format.

### Community 116 - "Community 116"
Cohesion: 0.22
Nodes (9): DeepSiteProfile, profile_site(), ProfileDepth, Enum, Deep site profiling module for the universal scraper., Depth of site profiling., Comprehensive site profile for script generation., Generate a hash of the profile for caching. (+1 more)

### Community 117 - "Community 117"
Cohesion: 0.27
Nodes (5): create_metrics_server(), create_metrics_server_sync(), MetricsServer, Synchronous version that returns metrics and server directly (for non-context-…, WorkerMetricsConfig

### Community 118 - "Community 118"
Cohesion: 0.20
Nodes (7): generate_api_key(), generate_secret(), Central security configuration., Generate and store a new secret., Generate a secure API key., Generate a secure random secret., SecurityConfig

### Community 119 - "Community 119"
Cohesion: 0.24
Nodes (6): Async robots.txt parser with caching., Check if URL can be fetched according to robots.txt., Get crawl delay for user agent., Get sitemap URLs from robots.txt., Get or create robots.txt parser for domain., RobotsParser

### Community 120 - "Community 120"
Cohesion: 0.22
Nodes (4): Counter, Gauge, Get or create a custom gauge., Get or create a custom counter.

### Community 121 - "Community 121"
Cohesion: 0.24
Nodes (5): crawl_one(), Any, Implementation of crawl for abstract base class., Implementation of LLM extraction for abstract base class., Extract structured data using Firecrawl's LLM extraction.

### Community 123 - "Community 123"
Cohesion: 0.24
Nodes (4): PlaywrightEngineV2, Any, PlaywrightBrowser, V2 version of PlaywrightEngine - inherits from BaseEngineV2 with circuit…

### Community 124 - "Community 124"
Cohesion: 0.20
Nodes (4): DataCleaningTransformer, Base class for data transformer plugins., Plugin for cleaning and normalizing scraped data., TransformerPlugin

### Community 125 - "Community 125"
Cohesion: 0.31
Nodes (9): asyncio, integration, Integration test for research mode., Test research mode auto-detection when goal provided without URL., Test regular URL request still works., Test research mode with extraction schema., test_regular_url_request(), test_research_mode_auto_detection() (+1 more)

### Community 126 - "Community 126"
Cohesion: 0.33
Nodes (3): Extract structured data from HTML (JSON-LD, Microdata, RDFa)., Extract all structured data from HTML., StructuredDataExtractor

### Community 127 - "Community 127"
Cohesion: 0.25
Nodes (4): Any, HTMLParser, record_from_html(), _Text

### Community 129 - "Community 129"
Cohesion: 0.28
Nodes (5): Auto-solve Cloudflare Turnstile challenges using 2Captcha or Capsolver API., Solve Turnstile challenge and return token., Solve using 2Captcha API., Solve using Capsolver API., TurnstileSolver

### Community 130 - "Community 130"
Cohesion: 0.25
Nodes (5): LLMResponseCache, Close Redis connection., Redis-backed cache for LLM responses with memory fallback., Initialize Redis connection., Delete a key from cache.

### Community 131 - "Community 131"
Cohesion: 0.28
Nodes (4): CORSHandler, Handles CORS headers and preflight requests., Generate CORS headers for a response., Handle OPTIONS preflight request.

### Community 132 - "Community 132"
Cohesion: 0.31
Nodes (6): create_dedup_manager(), DedupConfig, HybridDeduplicator, Hybrid deduplicator combining Hash + SimHash + Embeddings., Configuration for semantic deduplication., Create a deduplication manager with the specified strategy.

### Community 133 - "Community 133"
Cohesion: 0.31
Nodes (5): High-level semantic deduplication manager., Check if URL/content is a duplicate., Normalize URL for comparison., Store content for future duplicate checks., SemanticDeduplicationManager

### Community 134 - "Community 134"
Cohesion: 0.25
Nodes (3): Any, Type text with human-like errors and corrections., Scroll with momentum/easing.

### Community 135 - "Community 135"
Cohesion: 0.29
Nodes (3): FirecrawlEngineV2, Any, V2 version of FirecrawlEngine - inherits from BaseEngineV2 with circuit…

### Community 137 - "Community 137"
Cohesion: 0.29
Nodes (5): Any, Validate JSON structure for safety., Sanitize input based on context., Convenience function to sanitize input., sanitize_input()

### Community 138 - "Community 138"
Cohesion: 0.29
Nodes (4): callable, OrchestratorPool, Any, Parallel execution with shared cache

### Community 139 - "Community 139"
Cohesion: 0.33
Nodes (5): parse_goal(), ParsedGoal, Parsed goal with extracted entities and constraints., Generate optimized search queries for search engines., Parse a goal string into structured entities.

### Community 140 - "Community 140"
Cohesion: 0.48
Nodes (5): ActionType, create_interaction_executor(), InteractionConfig, Enum, # NOTE: [rel="next"] and link[rel="next"] removed — they match hidden <link>…

### Community 141 - "Community 141"
Cohesion: 0.29
Nodes (4): MiddlewarePlugin, Base class for middleware plugins., Process request before scraping., Process response after scraping.

### Community 142 - "Community 142"
Cohesion: 0.33
Nodes (4): CaptchaImageSolver, Solve simple image CAPTCHAs using OCR (Tesseract)., Solve CAPTCHA from image file using OCR., Preprocess image for better OCR results.

### Community 143 - "Community 143"
Cohesion: 0.29
Nodes (4): create_health_endpoint(), health_check(), Decorator to register a health check., Create FastAPI/Starlette health check endpoints.

### Community 145 - "Community 145"
Cohesion: 0.33
Nodes (4): run_scrape(), fixture, Create a PlaywrightSearchEngine instance., Create a test EngineConfig.

### Community 146 - "Community 146"
Cohesion: 0.33
Nodes (3): InteractionResult, Execute an interaction sequence with human-like behavior., Wait with small random variation.

### Community 147 - "Community 147"
Cohesion: 0.33
Nodes (3): Any, Find API endpoints by monitoring network requests., Generate crawl strategy based on profile.

### Community 148 - "Community 148"
Cohesion: 0.33
Nodes (3): Generate security headers for HTTP responses., Get all security headers., SecurityHeaders

### Community 149 - "Community 149"
Cohesion: 0.40
Nodes (3): HookPlugin, Base class for hook plugins (event-based)., Execute a specific hook.

### Community 150 - "Community 150"
Cohesion: 0.40
Nodes (3): Base class for validator plugins., Validate data against schema. Return validation result., ValidatorPlugin

### Community 151 - "Community 151"
Cohesion: 0.40
Nodes (3): Any, Complete search pipeline: Goal → Queries → Search Engines (fallback) → Rank →…, Scrape method compatible with UniversalRunner fallback chain. Uses the search…

### Community 152 - "Community 152"
Cohesion: 0.40
Nodes (3): Configuration for TinyFish Search Engine (using official SDK)., Initialize the TinyFish search engine with official SDK., TinyFishSearchConfig

### Community 153 - "Community 153"
Cohesion: 0.70
Nodes (4): get_limit_state(), _mark(), mark_limit_reached(), _state()

### Community 154 - "Community 154"
Cohesion: 0.40
Nodes (3): decorator(), HealthCheck, Register a health check.

### Community 162 - "Community 162"
Cohesion: 0.67
Nodes (3): HealthStatus, Enum, str

## Knowledge Gaps
- **8 isolated node(s):** `AuthConfig`, `SearchResult`, `BenchmarkResult`, `CrawlResult`, `ExtractResult` (+3 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 1147 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **18 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `EngineConfig` connect `Community 13` to `Community 1`, `Community 2`, `Community 4`, `Community 135`, `Community 8`, `Community 7`, `Community 10`, `Community 11`, `Community 140`, `Community 14`, `Community 15`, `Community 16`, `Community 145`, `Community 20`, `Community 23`, `Community 24`, `Community 25`, `Community 152`, `Community 31`, `Community 35`, `Community 37`, `Community 44`, `Community 51`, `Community 54`, `Community 59`, `Community 62`, `Community 71`, `Community 79`, `Community 90`, `Community 93`, `Community 96`, `Community 101`, `Community 123`?**
  _High betweenness centrality (0.082) - this node is a cross-community bridge._
- **Why does `EngineType` connect `Community 14` to `Community 1`, `Community 4`, `Community 135`, `Community 8`, `Community 7`, `Community 10`, `Community 11`, `Community 12`, `Community 13`, `Community 140`, `Community 15`, `Community 16`, `Community 18`, `Community 19`, `Community 21`, `Community 22`, `Community 24`, `Community 31`, `Community 35`, `Community 37`, `Community 44`, `Community 54`, `Community 59`, `Community 70`, `Community 71`, `Community 73`, `Community 74`, `Community 79`, `Community 90`, `Community 91`, `Community 116`, `Community 123`?**
  _High betweenness centrality (0.072) - this node is a cross-community bridge._
- **Why does `ManagedEngine` connect `Community 4` to `Community 1`, `Community 2`, `Community 40`, `Community 13`, `Community 14`, `Community 15`, `Community 16`, `Community 51`, `Community 20`, `Community 84`?**
  _High betweenness centrality (0.036) - this node is a cross-community bridge._
- **Are the 43 inferred relationships involving `EngineConfig` (e.g. with `APIEngine` and `create_api_engine()`) actually correct?**
  _`EngineConfig` has 43 INFERRED edges - model-reasoned connections that need verification._
- **Are the 39 inferred relationships involving `EngineType` (e.g. with `ScraperService` and `StreamingScraperService`) actually correct?**
  _`EngineType` has 39 INFERRED edges - model-reasoned connections that need verification._
- **Are the 20 inferred relationships involving `UniversalConfig` (e.g. with `_same_origin_links()` and `scrape()`) actually correct?**
  _`UniversalConfig` has 20 INFERRED edges - model-reasoned connections that need verification._
- **Are the 14 inferred relationships involving `UniversalRequest` (e.g. with `ScraperService` and `StreamingScraperService`) actually correct?**
  _`UniversalRequest` has 14 INFERRED edges - model-reasoned connections that need verification._