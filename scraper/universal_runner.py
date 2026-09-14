from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from pathlib import Path

from .config.schemas import (
    UniversalConfig,
    UniversalRequest,
    UniversalResult,
    SiteProfile,
    EngineType,
    OutputFormat,
    FallbackConfig,
    FallbackContext,
    AntiBotLevel,
)
from .engines.interfaces import EngineConfig
from .engines.registry_v2 import EngineRegistryV2
from .engines.interfaces import (
    HTTPEngine,
    BrowserEngine,
    ManagedEngine,
    CloudEngine,
    APIEngine,
    EngineConfig,
    EngineCapability,
)
from .engines.http_engine import HTTPEngine
from .engines.browser_engine import BrowserEngine
from .engines.managed_engine import ManagedEngine
from .engines.cloud_engine import CloudEngine
from .engines.api_engine import APIEngine
from .engines.browser_pool import AdaptiveBrowserPool
from .utils.observability import get_logger, MetricsCollector
from .utils.dedup import DeduplicationManager, DedupConfig
from .utils.sitemap import SitemapParser, SitemapConfig, RobotsParser
from .failure_classifier import FailureClassifier, FailureClassification
from .validator import ResultValidator
from .output_pipeline import OutputPipeline


class FallbackReason(Enum):
    NETWORK_ERROR = "network_error"
    HTTP_ERROR = "http_error"
    BLOCKING = "blocking"
    EMPTY_CONTENT = "empty_content"
    PARSING_ERROR = "parsing_error"
    ENGINE_ERROR = "engine_error"
    QUALITY_BELOW_THRESHOLD = "quality_below_threshold"
    TIMEOUT = "timeout"
    CIRCUIT_OPEN = "circuit_open"


@dataclass
class EngineAttempt:
    engine: str
    success: bool
    latency_ms: int
    error: Optional[str] = None
    error_category: Optional[str] = None
    result_quality: Optional[float] = None
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


class QuickProfiler:
    """Fast site profiling (<5s) for engine selection with browser fallback."""

    def __init__(self, config: UniversalConfig):
        self.config = config
        self.logger = get_logger("quick_profiler")

    async def analyze(self, url: str) -> SiteProfile:
        """Quick analysis using HEAD + single GET, with browser fallback on failure."""
        from httpx import AsyncClient
        import re

        self.logger.info("Quick profiling", url=url)

        # Try HTTP first (fast path)
        profile = await self._analyze_http(url)
        if profile and profile.confidence >= 0.5:
            return profile

        # Fallback: browser-based profiling for JS-heavy or blocked sites
        self.logger.info("HTTP profiling failed or low confidence, trying browser-based profiling", url=url)
        profile = await self._analyze_browser(url)
        return profile

    async def _analyze_http(self, url: str) -> SiteProfile:
        """Quick analysis using HTTP requests."""
        from httpx import AsyncClient
        import re

        async with AsyncClient(timeout=15.0, follow_redirects=True) as client:
            # HEAD request
            try:
                head_resp = await client.head(url)
                headers = dict(head_resp.headers)
            except Exception:
                headers = {}

            # GET request
            try:
                resp = await client.get(url)
                content = resp.text
                status_code = resp.status_code
            except Exception as e:
                self.logger.warning("GET failed during profiling", error=str(e))
                return None

        # Quick classification
        content_lower = content.lower()

        # Detect JS framework
        js_framework = None
        frameworks = {
            "react": ["react", "__react", "reactroot", "data-reactroot"],
            "vue": ["vue", "__vue", "v-app", "v-cloak"],
            "nextjs": ["__next", "next.js", "_next/static"],
            "angular": ["ng-app", "ng-version", "angular"],
            "svelte": ["svelte", "__svelte"],
        }
        for fw, indicators in frameworks.items():
            if any(ind in content_lower for ind in indicators):
                js_framework = fw
                break

        # Detect anti-bot
        anti_bot = "none"
        anti_bot_details = {}
        if status_code in (403, 429):
            anti_bot = "high"
        elif any(x in content_lower for x in ["cloudflare", "akamai", "incapsula", "perimeterx", "datadome", "shape"]):
            anti_bot = "high"
        elif any(x in content_lower for x in ["captcha", "challenge", "access denied", "blocked", "rate limit"]):
            anti_bot = "medium"

        # Detect pagination
        has_pagination = any(x in content_lower for x in ["pagination", "page=", "pagenum", "next page", "load more"])

        return SiteProfile(
            url=url,
            category="unknown",
            js_framework=js_framework,
            requires_js=bool(js_framework),
            anti_bot_level=anti_bot,
            anti_bot_details=anti_bot_details,
            has_pagination=has_pagination,
            pagination_type="url_param" if "page=" in content_lower else None,
            recommended_engine=self._recommend_engine(js_framework, anti_bot, status_code),
            confidence=0.7 if content else 0.1,
            analyzed_at=datetime.utcnow().isoformat(),
            sample_pages=1,
        )

    async def _analyze_browser(self, url: str) -> SiteProfile:
        """Browser-based profiling using Playwright for JS-heavy sites."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            self.logger.warning("Playwright not available for browser profiling")
            return self._default_profile(url)

        try:
            p = await async_playwright().start()
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-gpu",
                    "--disable-web-security",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                locale="en-US",
            )
            page = await context.new_page()

            try:
                # Navigate with fallback
                response = None
                try:
                    response = await page.goto(url, wait_until="networkidle", timeout=30000)
                except Exception:
                    try:
                        response = await page.goto(url, wait_until="load", timeout=30000)
                    except Exception:
                        response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)

                content = await page.content()
                status_code = response.status if response else 0
                content_lower = content.lower()

                # Detect JS framework
                js_framework = None
                frameworks = {
                    "react": ["react", "__react", "reactroot", "data-reactroot"],
                    "vue": ["vue", "__vue", "v-app", "v-cloak"],
                    "nextjs": ["__next", "next.js", "_next/static"],
                    "angular": ["ng-app", "ng-version", "angular"],
                    "svelte": ["svelte", "__svelte"],
                }
                for fw, indicators in frameworks.items():
                    if any(ind in content_lower for ind in indicators):
                        js_framework = fw
                        break

                # Detect anti-bot
                anti_bot = "none"
                anti_bot_details = {}
                if status_code in (403, 429):
                    anti_bot = "high"
                elif any(x in content_lower for x in ["cloudflare", "akamai", "incapsula", "perimeterx", "datadome", "shape"]):
                    anti_bot = "high"
                elif any(x in content_lower for x in ["captcha", "challenge", "access denied", "blocked", "rate limit"]):
                    anti_bot = "medium"

                # Detect pagination
                has_pagination = any(x in content_lower for x in ["pagination", "page=", "pagenum", "next page", "load more"])

                return SiteProfile(
                    url=url,
                    category="unknown",
                    js_framework=js_framework,
                    requires_js=bool(js_framework),
                    anti_bot_level=anti_bot,
                    anti_bot_details=anti_bot_details,
                    has_pagination=has_pagination,
                    pagination_type="url_param" if "page=" in content_lower else None,
                    recommended_engine=self._recommend_engine(js_framework, anti_bot, status_code),
                    confidence=0.8,
                    analyzed_at=datetime.utcnow().isoformat(),
                    sample_pages=1,
                )
            finally:
                await context.close()
                await browser.close()
                await p.stop()
        except Exception as e:
            self.logger.warning("Browser profiling failed", error=str(e))
            return self._default_profile(url)

    def _default_profile(self, url: str) -> SiteProfile:
        """Return a default profile when all profiling fails."""
        return SiteProfile(
            url=url,
            category="unknown",
            js_framework=None,
            requires_js=False,
            anti_bot_level="none",
            anti_bot_details={},
            has_pagination=False,
            pagination_type=None,
            recommended_engine=EngineType.HTTP.value,
            confidence=0.3,
            analyzed_at=datetime.utcnow().isoformat(),
            sample_pages=0,
        )

    def _recommend_engine(self, js_framework: Optional[str], anti_bot: str, status_code: int) -> str:
        if anti_bot == "high" or status_code in (403, 429):
            return EngineType.CLOUD.value
        elif js_framework:
            return EngineType.BROWSER.value
        else:
            return EngineType.HTTP.value

    def _recommend_engine(self, js_framework: Optional[str], anti_bot: str, status_code: int) -> str:
        if anti_bot == "high" or status_code in (403, 429):
            return EngineType.CLOUD.value
        elif js_framework:
            return EngineType.BROWSER.value
        else:
            return EngineType.HTTP.value


class SmartEngineSelector:
    """Selects optimal engine based on profile and historical performance."""

    def __init__(self, config: UniversalConfig):
        self.config = config
        self.logger = get_logger("engine_selector")
        self._metrics = MetricsCollector("selector", config.observability)

    def select(self, profile: SiteProfile, request: UniversalRequest) -> tuple[EngineType, Dict[str, Any]]:
        """Select best engine with optimized config."""

        # Explicit engine override
        if request.engine:
            return EngineType(request.engine), self._get_engine_config(request.engine, profile)

        # Check routing rules
        for rule in self.config.routing.rules:
            if self._matches_rule(request.url, rule):
                # Handle both dict and Pydantic RoutingRule
                if hasattr(rule, 'model_dump'):
                    rule_dict = rule.model_dump()
                elif hasattr(rule, 'dict'):
                    rule_dict = rule.dict()
                else:
                    rule_dict = rule
                engine = rule_dict.get("engine")
                if engine and EngineRegistryV2.is_registered(EngineType(engine)):
                    self.logger.debug("Rule matched", url=request.url, engine=engine, reason=rule_dict.get("reason"))
                    return EngineType(engine), self._get_engine_config(engine, profile)

        # Score-based selection
        self._current_request = request  # Set for scoring
        scored = self._score_engines(profile)
        self._current_request = None
        best_engine = scored[0][1]

        self.logger.info("Engine selected", engine=best_engine.value, scores={e.value: s for s, e in scored[:3]})
        return best_engine, self._get_engine_config(best_engine.value, profile)

    def _score_engines(self, profile: SiteProfile) -> List[tuple[float, EngineType]]:
        candidates = EngineRegistryV2.get_available()
        scored = []

        # Get current request for context (set by select() method)
        request = getattr(self, '_current_request', None)

        for engine_type in candidates:
            meta = EngineRegistryV2.get_metadata(engine_type)
            if not meta:
                continue

            # Capability match
            caps = set(meta.capabilities)
            required = self._infer_required_capabilities(profile)
            capability_score = len([c for c in required if c in caps]) / max(1, len(required))

            # Historical success
            history_score = self._metrics.get_success_rate(engine_type, profile.category) or 0.5

            # Cost efficiency
            cost_score = 1.0 / (meta.cost_per_1k_pages + 0.01)

            # Latency (lower better)
            latency_score = max(0, 1.0 - meta.avg_latency_ms / 30000)

            # Health
            health_score = 1.0 if EngineRegistryV2._health_status.get(engine_type, True) else 0.1

            # Firecrawl boost for specific scenarios
            firecrawl_boost = 0.0
            if engine_type.value == "cloud" and request:
                # Boost for anti-bot
                if profile.anti_bot_level in ("high", "extreme"):
                    firecrawl_boost += 0.5
                # Boost for PDF extraction
                if request.pdf:
                    firecrawl_boost += 0.4
                # Boost for screenshot
                if request.screenshot:
                    firecrawl_boost += 0.6
                # Boost for LLM extraction
                if request.extract_schema:
                    firecrawl_boost += 0.4
                # Boost for PDF extraction (duplicate check)
                if hasattr(request, 'pdf') and request.pdf:
                    firecrawl_boost += 0.4

            # Weighted score
            weights = {
                "capability": 0.35,
                "history": 0.25,
                "cost": 0.15,
                "latency": 0.15,
                "health": 0.10,
            }
            total = sum(w * s for w, s in zip(
                weights.values(),
                [capability_score, history_score, cost_score, latency_score, health_score]
            )) + firecrawl_boost
            scored.append((total, engine_type))

        scored.sort(reverse=True)
        return scored

    def _infer_required_capabilities(self, profile: SiteProfile) -> List[EngineCapability]:
        caps = []
        if profile.category == "research":
            caps.append(EngineCapability.SEARCH)
            caps.append(EngineCapability.REST_API)
            caps.append(EngineCapability.LLM_EXTRACTION)
        if profile.requires_js or profile.js_framework:
            caps.append(EngineCapability.JAVASCRIPT)
        if profile.anti_bot_level in ("high", "extreme"):
            caps.append(EngineCapability.ANTI_BOT)
        if self.config.proxy_config.enabled:
            caps.append(EngineCapability.PROXY_ROTATION)
        if self.config.session_config.enabled:
            caps.append(EngineCapability.SESSION_PERSISTENCE)
        # Check for PDF/screenshot needs from request
        request = getattr(self, '_current_request', None)
        if request:
            if request.extract_schema:
                caps.append(EngineCapability.LLM_EXTRACTION)
            # PDF extraction capability
            if hasattr(request, 'pdf') and request.pdf:
                caps.append(EngineCapability.PDF_PARSING)
        return caps

    def _matches_rule(self, url: str, rule: Any) -> bool:
        from urllib.parse import urlparse
        import fnmatch

        # Handle both dict and Pydantic RoutingRule
        if hasattr(rule, 'model_dump'):
            rule = rule.model_dump()
        elif hasattr(rule, 'dict'):
            rule = rule.dict()

        parsed = urlparse(url)
        if "domain" in rule and rule["domain"] and rule["domain"] not in parsed.netloc:
            return False
        if "pattern" in rule and rule["pattern"] and not fnmatch.fnmatch(url, rule["pattern"]):
            return False
        if "path_prefix" in rule and rule["path_prefix"] and not parsed.path.startswith(rule["path_prefix"]):
            return False
        return True

    def _get_engine_config(self, engine_name: str, profile: SiteProfile) -> EngineConfig:
        base_config = {}
        if engine_name == "browser":
            base_config = {
                "headless": True,
                "stealth_mode": True,
                "resource_blocking": {"images": True, "fonts": True, "media": True},
            }
        elif engine_name == "http":
            base_config = {
                "autothrottle_enabled": True,
                "parser": "selectolax",
            }
        elif engine_name == "managed":
            base_config = {
                "managed_engine": {
                    "headless": True,
                    "browser_type": "chromium",
                    "max_concurrency": 5,
                    "max_requests_per_crawl": 50,
                }
            }
        elif engine_name == "cloud":
            base_config = {
                "cloud_engine": {
                    "formats": ["markdown", "html"],
                    "only_main_content": True,
                    "proxy": "auto",
                    "timeout": 120000,
                },
                "retry_policy": {
                    "max_attempts": 3,
                    "base_delay": 1.0,
                    "max_delay": 60.0,
                    "exponential_base": 2.0,
                    "jitter": True,
                    "jitter_factor": 0.1,
                    "retryable_status_codes": [408, 429, 500, 502, 503, 504],
                    "retryable_exceptions": [
                        "TimeoutError", "ConnectionError", "ConnectTimeout", "ReadTimeout",
                        "ProxyError", "SSLError", "TooManyRedirects"
                    ],
                    "stop_on_status": [400, 401, 403, 404]
                }
            }
        return EngineConfig(name=engine_name, config=base_config)


class FallbackChain:
    """Executes engine chain with rich context capture."""

    def __init__(self, config: UniversalConfig):
        self.config = config
        self.fallback_config = config.fallback or FallbackConfig()
        self.logger = get_logger("fallback_chain")
        self._circuit_breakers: Dict[str, Any] = {}

    async def execute(
        self,
        primary_engine: EngineType,
        profile: SiteProfile,
        request: UniversalRequest,
        engine_config: Dict[str, Any],
    ) -> UniversalResult:
        """Execute engine chain with fallback."""
        chain = self._build_chain(primary_engine, profile)
        self.logger.info("Executing fallback chain", chain=[e.value for e in chain])

        attempts = []

        for engine_type in chain:
            if not EngineRegistryV2.is_registered(engine_type):
                continue

            # Check circuit breaker
            if self._is_circuit_open(engine_type.value):
                attempts.append(EngineAttempt(
                    engine=engine_type.value,
                    success=False,
                    latency_ms=0,
                    error="Circuit breaker open",
                    error_category="circuit_open",
                ))
                continue

            try:
                # Add timeout for each engine execution (configurable per engine type)
                engine_timeouts = {
                    "search": 120,      # Search pipeline: query expansion + multiple searches
                    "browser": 60,      # Browser engine: page load + JS execution
                    "managed": 60,      # Managed engine: crawler initialization + crawl
                    "http": 30,         # HTTP engine: simple fetch
                    "cloud": 60,        # Cloud engine: API call + processing
                    "api": 30,          # API engine: API call
                }
                timeout_seconds = engine_timeouts.get(engine_type.value, 30)
                self.logger.info(f"Executing engine {engine_type.value} with {timeout_seconds}s timeout")
                result = await asyncio.wait_for(
                    self._execute_engine(engine_type, request, profile, engine_config),
                    timeout=timeout_seconds
                )
                self.logger.info(f"Engine {engine_type.value} completed successfully")

                attempts.append(EngineAttempt(
                    engine=engine_type.value,
                    success=result.success,
                    latency_ms=result.latency_ms,
                    error=result.error,
                    result_quality=result.quality_score if result.success else 0,
                ))

                if result.success and self._is_meaningful_result(result, request):
                    if self.fallback_config.enabled:
                        self._record_circuit_success(engine_type.value)
                    return result

                # Result not meaningful
                if not self._is_meaningful_result(result, request):
                    attempts[-1].error = "empty_or_low_quality"
                    attempts[-1].error_category = "empty_content"

            except asyncio.TimeoutError:
                self.logger.warning(f"Engine {engine_type.value} timed out after {timeout_seconds}s")
                attempts.append(EngineAttempt(
                    engine=engine_type.value,
                    success=False,
                    latency_ms=0,
                    error=f"Timeout after {timeout_seconds}s",
                    error_category="timeout",
                ))
                self._record_circuit_failure(engine_type.value)
                continue
            except Exception as e:
                attempts.append(EngineAttempt(
                    engine=engine_type.value,
                    success=False,
                    latency_ms=0,
                    error=str(e),
                    error_category=self._categorize_error(e),
                ))
                self._record_circuit_failure(engine_type.value)
                continue

        # All engines failed
        raise AllEnginesFailed(FallbackContext(
            target_url=request.url,
            profile=profile,
            attempts=[a.__dict__ for a in attempts],
            request_config=request.model_dump(),
            error_category=attempts[-1].error_category if attempts else "unknown",
        ))

    def _build_chain(self, primary: EngineType, profile: SiteProfile) -> List[EngineType]:
        """Build fallback chain based on primary engine and profile."""
        # Concrete engine types (not abstract)
        concrete_engines = {
            EngineType.SEARCH, EngineType.BROWSER, EngineType.HTTP, EngineType.API, EngineType.CLOUD, EngineType.MANAGED
        }
        
        # For research mode, prioritize SEARCH engine
        if profile.category == "research":
            research_chain = [EngineType.SEARCH, EngineType.BROWSER, EngineType.HTTP, EngineType.CLOUD]
            return [e for e in research_chain if EngineRegistryV2.is_registered(e) and e in concrete_engines]
        
        # For anti-bot scenarios, prioritize CLOUD (Firecrawl) then BROWSER
        if profile.anti_bot_level in ("high", "extreme"):
            anti_bot_chain = [EngineType.CLOUD, EngineType.BROWSER, EngineType.HTTP]
            return [e for e in anti_bot_chain if EngineRegistryV2.is_registered(e) and e in concrete_engines]
        
        fallback_map = {
            EngineType.API: [EngineType.HTTP, EngineType.BROWSER, EngineType.CLOUD],
            EngineType.BROWSER: [EngineType.HTTP, EngineType.API, EngineType.CLOUD],
            EngineType.HTTP: [EngineType.BROWSER, EngineType.API, EngineType.CLOUD],
            EngineType.CLOUD: [EngineType.BROWSER, EngineType.HTTP, EngineType.API],
            EngineType.MANAGED: [EngineType.BROWSER, EngineType.HTTP, EngineType.CLOUD],
        }
        chain = [primary] + fallback_map.get(primary, [EngineType.BROWSER, EngineType.HTTP, EngineType.CLOUD])
        # Filter to available concrete engines
        return [e for e in chain if EngineRegistryV2.is_registered(e) and e in concrete_engines]

    def _is_circuit_open(self, engine_name: str) -> bool:
        cb = self._circuit_breakers.get(engine_name)
        if cb and cb.get("open", False):
            if time.time() - cb.get("opened_at", 0) > 60:  # 60s recovery
                cb["open"] = False
                return False
            return True
        return False

    def _record_circuit_success(self, engine_name: str):
        if engine_name in self._circuit_breakers:
            self._circuit_breakers[engine_name] = {"failures": 0, "open": False}

    def _record_circuit_failure(self, engine_name: str):
        if engine_name not in self._circuit_breakers:
            self._circuit_breakers[engine_name] = {"failures": 0, "open": False}
        cb = self._circuit_breakers[engine_name]
        cb["failures"] = cb.get("failures", 0) + 1
        if cb["failures"] >= 3:
            cb["open"] = True
            cb["opened_at"] = time.time()

    def _is_meaningful_result(self, result: UniversalResult, request: UniversalRequest) -> bool:
        if not result.success:
            return False

        # For SEARCH engine: empty results list is valid (no results found for query)
        # Don't treat as failure - only treat as failure if engine itself errored
        if result.engine_used == "search_pipeline" or result.engine_used == "search":
            # Search engine returns data={"results": [...]} or a list
            results_list = result.data.get("results") if isinstance(result.data, dict) else result.data
            if isinstance(results_list, list):
                # Empty list is valid for search - query returned no results
                # Only fail if there's an explicit error
                if result.error and "captcha" in result.error.lower():
                    return False
                return True

        # Check for error patterns in content
        content_str = str(result.data).lower()
        error_patterns = [
            "captcha", "access denied", "blocked", "rate limit",
            "please verify", "unusual traffic", "challenge",
            "cloudflare", "akamai", "incapsula", "perimeterx",
        ]
        if any(p in content_str for p in error_patterns):
            return False

        # Check minimum content for non-search engines
        if isinstance(result.data, list) and len(result.data) == 0:
            return False

        return True

    def _categorize_error(self, error: Exception) -> str:
        error_str = str(error).lower()
        if "timeout" in str(error):
            return "timeout"
        elif "connection" in str(error):
            return "network_error"
        elif "403" in str(error) or "429" in str(error):
            return "http_error"
        elif "captcha" in str(error) or "blocked" in str(error):
            return "blocking"
        return "engine_error"

    async def _execute_engine(self, engine_type: EngineType, request: UniversalRequest, profile: SiteProfile, engine_config: Dict[str, Any]) -> UniversalResult:
            """Execute a single engine with request adaptation."""
            from .engines import EngineRegistryV2
            from .engines.interfaces import BrowserRequest, HTTPRequest

            engine = await EngineRegistryV2.get(engine_type, engine_config)

            # Check health
            if not engine.health_check():
                raise RuntimeError(f"{engine_type.value} health check failed")

            # Adapt request based on engine type
            if engine_type == EngineType.SEARCH:
                # SearchPipelineEngine expects UniversalRequest
                return await engine.scrape(request)
            elif engine_type == EngineType.BROWSER:
                # Browser engines expect BrowserRequest
                browser_req = BrowserRequest(
                    url=request.url,
                    wait_until="networkidle",
                    wait_for_selector=request.engine_options.get("wait_for_selector"),
                    timeout=request.engine_options.get("timeout", 30) * 1000,
                    user_agent=request.engine_options.get("user_agent"),
                )
                response = await engine.scrape(browser_req)
                return UniversalResult(
                    success=response.success,
                    url=response.url,
                    data={"html": response.html, "markdown": response.markdown} if response.success else {},
                    engine_used=engine_type.value,
                    error=response.error,
                    latency_ms=response.elapsed_ms,
                )
            elif engine_type == EngineType.HTTP:
                # HTTP engines use fetch with HTTPRequest
                http_req = HTTPRequest(
                    url=request.url,
                    method="GET",
                    headers=request.headers,
                    timeout=request.engine_options.get("timeout", 30.0),
                )
                response = await engine.fetch(http_req)
                # HTTPResponse has status_code/error but no success boolean
                success = response.status_code < 400 and response.error is None
                return UniversalResult(
                    success=success,
                    url=response.url,
                    data=response.text,
                    engine_used=engine_type.value,
                    error=response.error,
                    latency_ms=getattr(response, "elapsed_ms", 0),
                )
            elif engine_type == EngineType.CLOUD:
                # Cloud engines (Firecrawl) use BrowserRequest
                browser_req = BrowserRequest(
                    url=request.url,
                    wait_until="networkidle",
                )
                response = await engine.scrape(browser_req)
                return UniversalResult(
                    success=response.success,
                    url=response.url,
                    data={"html": response.html, "markdown": response.markdown} if response.success else {},
                    engine_used=engine_type.value,
                    error=response.error,
                    latency_ms=response.elapsed_ms,
                )
            elif engine_type == EngineType.MANAGED:
                # Managed engines (Crawlee) use BrowserRequest
                browser_req = BrowserRequest(
                    url=request.url,
                    wait_until="networkidle",
                )
                response = await engine.scrape(browser_req)
                # BrowserResponse has elapsed_ms; fallback to 0 if missing
                latency_ms = getattr(response, "elapsed_ms", getattr(response, "latency_ms", 0))
                return UniversalResult(
                    success=response.success,
                    url=response.url,
                    data={"html": response.html, "markdown": response.markdown} if response.success else {},
                    engine_used=engine_type.value,
                    error=response.error,
                    latency_ms=latency_ms,
                )
            elif engine_type == EngineType.API:
                # API engine doesn't support traditional scraping
                raise RuntimeError(f"Engine {engine_type.value} does not support traditional scraping")

            raise RuntimeError(f"Engine {engine_type.value} does not support scraping")


class AllEnginesFailed(Exception):
    def __init__(self, context: FallbackContext):
        self.context = context
        errors = []
        for a in context.attempts:
            if isinstance(a, dict):
                errors.append(a.get('error', 'unknown'))
            else:
                errors.append(getattr(a, 'error', 'unknown'))
        super().__init__(f"All engines failed for {context.target_url}: {errors}")


class UniversalRunner:
    """Option A: Real-time multi-engine scraping with auto-fallback."""

    def __init__(self, config: UniversalConfig):
        self.config = config
        self.logger = get_logger("universal_runner")
        self.profiler = QuickProfiler(config)
        self.selector = SmartEngineSelector(config)
        self.fallback_chain = FallbackChain(config)
        self.validator = ResultValidator(config)
        self.output_pipeline = OutputPipeline(config)
        self._dedup = DeduplicationManager(DedupConfig())
        self._firecrawl_started = False
        self._metrics = MetricsCollector("universal_runner", config.observability)

    async def _ensure_firecrawl_ready(self) -> bool:
        """Ensure Firecrawl Docker is running if cloud engine is enabled."""
        if not self.config.cloud_engine.enabled:
            return False
        
        if not self.config.cloud_engine.auto_start:
            return False
        
        if self._firecrawl_started:
            return True
        
        # Import here to avoid circular import
        try:
            from custom_scripts.universal_scraper import DockerFirecrawlManager
        except ImportError:
            # Fallback: when running as a script, custom_scripts/ is on sys.path[0]
            # (not its parent), so the absolute import above fails. Try the direct
            # module import instead, adding the script's parent to sys.path if needed.
            try:
                import sys as _sys
                from pathlib import Path as _Path
                _project_root = _Path(__file__).resolve().parent.parent
                if str(_project_root) not in _sys.path:
                    _sys.path.insert(0, str(_project_root))
                from custom_scripts.universal_scraper import DockerFirecrawlManager
            except Exception as _e:
                self.logger.warning(
                    f"Firecrawl Docker manager not available (import failed: {_e})"
                )
                return False
        
        try:
            docker_manager = DockerFirecrawlManager()
            if not docker_manager.is_running():
                self.logger.info("Auto-starting Firecrawl Docker...")
                success = await asyncio.wait_for(docker_manager.start(), timeout=30.0)
                if not success:
                    self.logger.warning("Failed to auto-start Firecrawl Docker, continuing without cloud engine")
                    return False
            self._firecrawl_started = True
            return True
        except Exception as e:
            self.logger.warning(f"Firecrawl Docker unavailable, continuing without cloud engine: {e}")
            return False

    async def scrape(self, request: UniversalRequest) -> UniversalResult:
        """Main entry point for scraping."""
        self.logger.info("Starting scrape", url=request.url, goal=request.goal[:50] if request.goal else "none")

        # Auto-detect research mode: goal provided without URL
        is_research = request.goal and not request.url

        if is_research:
            self.logger.info("Research mode detected", goal=request.goal[:100])
            # Create research profile
            profile = SiteProfile(
                url="research:goal",
                category="research",
                requires_js=False,
                anti_bot_level=AntiBotLevel.NONE,
                recommended_engine=EngineType.SEARCH.value,
                confidence=1.0,
                analyzed_at=datetime.utcnow().isoformat(),
                sample_pages=0,
            )
            engine_type = EngineType.SEARCH
            search_config = self.config.extraction.model_dump() if hasattr(self.config, 'extraction') else {}
            self.logger.info(f"UniversalRunner search_config keys before browser_engine: {list(search_config.keys())}")
            # Pass browser_engine config to search_pipeline for browser pool configuration
            search_config["browser_engine"] = self.config.browser_engine.model_dump() if hasattr(self.config, 'browser_engine') else {}
            self.logger.info(f"UniversalRunner search_config keys after browser_engine: {list(search_config.keys())}")
            self.logger.info(f"UniversalRunner search_config browser_engine: {search_config.get('browser_engine', 'NOT FOUND')}")
            # Pass tinyfish and serpapi configs
            if hasattr(self.config, 'tinyfish_search'):
                search_config["tinyfish_search"] = self.config.tinyfish_search.model_dump()
            if hasattr(self.config, 'serpapi_search'):
                search_config["serpapi_search"] = self.config.serpapi_search.model_dump()
            if hasattr(self.config, 'query_expander'):
                search_config["query_expander"] = self.config.query_expander.model_dump()
            if hasattr(self.config, 'relevance_ranker'):
                search_config["relevance_ranker"] = self.config.relevance_ranker.model_dump()
            self.logger.info(f"UniversalRunner search_config keys after browser_engine: {list(search_config.keys())}")
            self.logger.info(f"UniversalRunner search_config browser_engine: {search_config.get('browser_engine', 'NOT FOUND')}")
            self.logger.info(f"UniversalRunner search_config tinyfish_search: {search_config.get('tinyfish_search', 'NOT FOUND')}")
            self.logger.info(f"UniversalRunner search_config serpapi_search: {search_config.get('serpapi_search', 'NOT FOUND')}")
            engine_config = EngineConfig(name="search_pipeline", config={"search_pipeline": search_config})
        else:
            # Deduplication check (only for URL-based requests)
            if request.url and not request.force_rescrape and self._dedup.is_duplicate(request.url):
                self.logger.info("URL already scraped, skipping", url=request.url)
                return UniversalResult(
                    success=False,
                    url=request.url,
                    error="URL already scraped (deduplication)",
                    engine_used="dedup",
                )

            # Quick profile
            profile = await self.profiler.analyze(request.url)

            # Select engine
            engine_type, engine_config = self.selector.select(profile, request)

        # Auto-start Firecrawl if cloud engine is selected or could be fallback
        await self._ensure_firecrawl_ready()

        # Execute with fallback
        result = None
        try:
            result = await self.fallback_chain.execute(
                engine_type, profile, request, engine_config
            )
            result.engine_used = result.engine_used or engine_type.value
            result.quality_score = self.validator.validate(result, request.extract_schema)
        except AllEnginesFailed as e:
            self.logger.warning("All engines failed, will trigger Option B", url=request.url or "research")
            raise

        # Mark as seen only on successful scrape
        if request.url and result and result.success:
            self._dedup.mark_seen(request.url)

        # Output pipeline
        return await self.output_pipeline.process(result, request)