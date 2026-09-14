from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

from scraper.config.schemas import (
    DeepSiteProfile,
    SiteProfile,
    EngineType,
    AntiBotLevel,
    ProfileDepth,
    FallbackContext,
    GenerationStrategy,
    GenerationRequirements,
    APIEngineConfig,
)
from scraper.engines.registry_v2 import EngineRegistryV2
from scraper.engines.http_engine import HTTPEngine as HTTPEngineImpl
from scraper.engines.browser_engine import BrowserEngine as BrowserEngineImpl
from scraper.engines.api_engine import APIEngine as APIEngineImpl
from scraper.engines.selectors import SelectorEngine, create_selector_engine, SelectorConfig, SelectorType
from scraper.engines.interactions import InteractionExecutor, create_interaction_executor, InteractionConfig
from scraper.utils.observability import get_logger
from scraper.engines.stealth import StealthManager
from scraper.engines.browser_pool import AdaptiveBrowserPool
from scraper.engines.interfaces import HTTPRequest, BrowserRequest, APIEndpoint, EngineConfig


@dataclass
class LLMAnalysis:
    page_type_classification: str = "unknown"
    stable_selectors: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    inferred_schema: Dict[str, Any] = field(default_factory=dict)
    pagination_pattern: str = "url_param"
    anti_bot_indicators: List[str] = field(default_factory=list)
    recommended_approach: str = "browser"
    interaction_sequence: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0


class DeepSiteProfiler:
    """Comprehensive site analysis for script generation."""

    def __init__(self, llm_client: Optional[Any] = None, config: Optional[Any] = None):
        self.llm_client = llm_client
        self.config = config
        self.logger = get_logger("deep_profiler")
        self._engines: Dict[str, Any] = {}
        self._selector_engine = create_selector_engine()
        self._interaction_config = InteractionConfig()

    async def _get_engines(self) -> Dict[str, Any]:
        if not self._engines:
            http_engine = HTTPEngineImpl()
            await http_engine.initialize(EngineConfig(name="http", config={
                "http_engine": {},
                "rate_limit": {"requests_per_second": 2.0},
            }))
            self._engines["http"] = http_engine

            browser_engine = BrowserEngineImpl()
            await browser_engine.initialize(EngineConfig(name="browser", config={
                "browser_engine": {
                    "headless": True,
                    "browser_type": "chromium",
                    "stealth_mode": True,
                    "stealth_config": {},
                    "context_config": {
                        "viewport_width": 1920,
                        "viewport_height": 1080,
                    },
                    "navigation_timeout": 30000,
                    "ignore_https_errors": True,
                    "java_script_enabled": True,
                },
            }))
            self._engines["browser"] = browser_engine

            api_engine = APIEngineImpl()
            await api_engine.initialize(EngineConfig(name="api", config={
                "api_engine": {},
            }))
            self._engines["api"] = api_engine
        return self._engines

    async def profile(
        self,
        url: str,
        context: Optional[FallbackContext] = None,
        depth: ProfileDepth = ProfileDepth.DEEP,
    ) -> DeepSiteProfile:
        """Deep analysis for script generation."""
        self.logger.info("Starting deep site profile", url=url, depth=depth.value)

        engines = await self._get_engines()

        # Phase 1: Multi-engine fetch (parallel)
        fetch_results = await self._multi_engine_fetch(engines, url)

        # Phase 2: Deep analysis on best result
        best_result = self._select_best_fetch(fetch_results)
        profile = await self._analyze_site(fetch_results, url, depth)

        # Phase 3: Crawl sample pages
        if depth in (ProfileDepth.STANDARD, ProfileDepth.DEEP):
            sample_pages = await self._crawl_sample_pages(engines, best_result, depth)
            profile.sample_pages = len(sample_pages)
            profile = await self._deep_analyze(profile, sample_pages, fetch_results)

        # Phase 4: API endpoint discovery
        profile.api_endpoints = await self._discover_apis(engines, url, fetch_results)

        # Phase 5: LLM-assisted analysis
        if self.llm_client and depth == ProfileDepth.DEEP:
            llm_analysis = await self._llm_analyze(profile, fetch_results)
            profile.llm_analysis = llm_analysis.__dict__ if llm_analysis else None

        # Phase 6: Selector stability testing
        if depth == ProfileDepth.DEEP:
            profile.selector_stability = await self._test_selector_stability(engines, profile)

        # Phase 7: Performance benchmarking
        profile.performance_metrics = self._benchmark_engines(fetch_results)

        # Final recommendations
        profile.recommended_engine = self._recommend_engine(fetch_results)
        profile.confidence = self._calculate_confidence(profile)
        profile.analyzed_at = datetime.utcnow().isoformat()
        profile.profile_depth = depth
        profile.fallback_context = context.__dict__ if context else None

        return profile

    async def _multi_engine_fetch(
        self,
        engines: Dict[str, Any],
        url: str,
    ) -> Dict[str, Any]:
        """Fetch with multiple engines in parallel."""
        tasks = {
            "http": engines["http"].fetch(HTTPRequest(url=url)),
            "browser": engines["browser"].navigate(BrowserRequest(url=url)),
            "api": engines["api"].intercept_network(url, 5000),
        }

        results = {}
        for name, coro in tasks.items():
            try:
                results[name] = await asyncio.wait_for(coro, timeout=30.0)
            except asyncio.TimeoutError:
                results[name] = {"success": False, "error": "timeout"}
            except Exception as e:
                results[name] = {"success": False, "error": str(e)}

        return results

    def _select_best_fetch(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Select best fetch result."""
        priority = ["browser", "http", "api"]
        for engine in priority:
            if engine in results:
                result = results[engine]
                # Handle different result types
                if isinstance(result, dict) and result.get("success", False):
                    return result
                elif isinstance(result, list) and len(result) > 0:
                    # For API engine, a non-empty list of endpoints is success
                    return {"success": True, "data": result, "engine": engine}
        return results.get("http", {})

    async def _analyze_site(
        self,
        fetch_results: Dict[str, Any],
        url: str,
        depth: ProfileDepth,
    ) -> DeepSiteProfile:
        """Analyze site characteristics."""
        best = self._select_best_fetch(fetch_results)

        profile = DeepSiteProfile(
            url=url,
            category=self._classify_site(best),
            js_framework=self._detect_js_framework(best),
            requires_js=self._requires_js(best),
            anti_bot_level=self._detect_anti_bot(fetch_results),
            anti_bot_details=self._get_anti_bot_details(fetch_results),
            has_pagination=self._detect_pagination(best),
            pagination_type=self._get_pagination_type(best),
            page_types=self._classify_pages(best),
            selectors=self._extract_selectors(best),
            auth_required=self._detect_auth(best),
            auth_type=self._get_auth_type(best),
            performance_metrics=self._measure_performance(fetch_results),
            recommended_engine=self._recommend_engine(fetch_results),
            confidence=self._calculate_confidence(fetch_results),
            analyzed_at=datetime.utcnow().isoformat(),
            sample_pages=1,
        )

        return profile

    async def _crawl_sample_pages(
        self,
        engines: Dict[str, Any],
        best_result: Dict[str, Any],
        depth: ProfileDepth,
    ) -> List[Dict[str, Any]]:
        """Crawl sample pages for deeper analysis."""
        sample_pages = []
        base_result = best_result

        # Get links from base page
        links = self._extract_links(base_result)
        if not links:
            return []

        # Limit based on depth
        max_pages = 3 if depth == ProfileDepth.STANDARD else 10
        target_links = links[:max_pages]

        # Use best engine for crawling
        engine_name = "browser" if engines.get("browser") else "http"
        engine = engines[engine_name]

        for link in target_links:
            try:
                if engine_name == "browser":
                    result = await engine.navigate(BrowserRequest(url=link))
                else:
                    result = await engine.fetch(HTTPRequest(url=link))

                if result.success:
                    sample_pages.append({
                        "url": link,
                        "html": getattr(result, "html", ""),
                        "text": getattr(result, "text", ""),
                        "title": getattr(result, "title", ""),
                    })
            except Exception as e:
                self.logger.warning("Failed to crawl sample page", url=link, error=str(e))

        return sample_pages

    async def _deep_analyze(
        self,
        profile: DeepSiteProfile,
        sample_pages: List[Dict[str, Any]],
        fetch_results: Dict[str, Any],
    ) -> DeepSiteProfile:
        """Deep analysis on multiple pages."""

        # Extract stable selectors across pages
        profile.selectors = self._extract_stable_selectors(sample_pages)

        # Analyze pagination more deeply
        profile.pagination_type = self._deep_pagination_analysis(sample_pages)
        profile.pagination_selectors = self._extract_pagination_selectors(sample_pages)

        # Classify page types
        profile.page_types = self._classify_pages_multi(sample_pages)

        # Detect interaction sequences
        profile.interaction_sequences = await self._detect_interactions(profile.url, sample_pages)

        # Infer schemas from sample data
        profile.inferred_schemas = self._infer_schemas(sample_pages)

        # Stability testing
        profile.selector_stability = self._test_selectors_on_samples(sample_pages)

        profile.sample_pages = len(sample_pages) + 1  # +1 for base page
        return profile

    async def _discover_apis(self, engines: Dict[str, Any], url: str, fetch_results: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Discover API endpoints."""
        api_results = fetch_results.get("api", [])
        
        # Handle both dict (legacy) and list (API engine) formats
        if isinstance(api_results, dict):
            if not api_results.get("success"):
                return []
            endpoints = api_results.get("endpoints", [])
        elif isinstance(api_results, list):
            endpoints = api_results
        else:
            return []
        
        return [
            {
                "url": ep.url if hasattr(ep, 'url') else ep.get("url"),
                "method": ep.method if hasattr(ep, 'method') else ep.get("method"),
                "is_graphql": ep.is_graphql if hasattr(ep, 'is_graphql') else ep.get("is_graphql", False),
                "response_sample": ep.response_body if hasattr(ep, 'response_body') else ep.get("response_body"),
            }
            for ep in endpoints[:20]
        ]

    async def _llm_analyze(
        self,
        profile: DeepSiteProfile,
        fetch_results: Dict[str, Any],
    ) -> Optional[LLMAnalysis]:
        """Use LLM to analyze site and recommend extraction approach."""
        if not self.llm_client:
            return None

        try:
            # Prepare context for LLM
            best = self._select_best_fetch(fetch_results)
            content = best.get("html") or best.get("text") or ""

            prompt = f"""
            Analyze this website for web scraping:
            
            URL: {profile.url}
            Category: {profile.category}
            JS Framework: {profile.js_framework}
            Anti-bot Level: {profile.anti_bot_level}
            Has Pagination: {profile.has_pagination}
            
            Page content (first 5000 chars):
            {content[:5000]}
            
            Sample pages: {len(profile.page_types)} pages analyzed
            
            Return JSON with:
            1. page_type_classification: "list" | "detail" | "listing" | "unknown"
            2. stable_selectors: CSS/XPath selectors for key fields with confidence
            3. inferred_schema: JSON Schema for extracted data
            4. pagination_pattern: "next_button" | "url_param" | "cursor" | "graphql" | "load_more"
            5. anti_bot_indicators: detected anti-bot mechanisms
            6. recommended_approach: "http" | "browser" | "api" | "hybrid"
            7. interaction_sequence: steps needed (click, scroll, wait)
            """

            # Call LLM (implementation depends on client)
            response = await self._call_llm(prompt)
            return self._parse_llm_response(response)

        except Exception as e:
            self.logger.warning("LLM analysis failed", error=str(e))
            return None

    async def _call_llm(self, prompt: str) -> str:
        """Call LLM with prompt."""
        # Implementation depends on LLM client (Groq, OpenAI, etc.)
        # Placeholder
        return '{"page_type_classification": "list", "recommended_approach": "browser"}'

    def _parse_llm_response(self, response: str) -> LLMAnalysis:
        try:
            data = json.loads(response)
            return LLMAnalysis(**data)
        except Exception:
            return LLMAnalysis()

    async def _test_selector_stability(
        self,
        engines: Dict[str, Any],
        profile: DeepSiteProfile,
    ) -> Dict[str, float]:
        """Test selector stability across pages."""
        stability = {}

        # Test on sample pages
        sample_pages = profile.page_types  # placeholder
        for field, selectors in profile.selectors.items():
            if isinstance(selectors, list):
                for sel in selectors:
                    # Test on multiple pages
                    pass
            stability[f"{field}"] = 0.9  # placeholder

        return stability

    def _benchmark_engines(self, fetch_results: Dict[str, Any]) -> Dict[str, float]:
        metrics = {}
        for engine, result in fetch_results.items():
            if isinstance(result, dict):
                metrics[f"{engine}_latency_ms"] = result.get("elapsed_ms", 0)
                metrics[f"{engine}_success"] = 1.0 if result.get("success") else 0.0
        return metrics

    # Helper methods (copied from profiler.py for completeness)
    def _classify_site(self, result: Dict[str, Any]) -> str:
        content = result.get("content") or result.get("html") or ""
        content_lower = content.lower()
        if any(x in content_lower for x in ["shop", "cart", "product", "price", "buy"]):
            return "ecommerce"
        elif any(x in content_lower for x in ["article", "blog", "post", "news"]):
            return "content"
        elif any(x in content_lower for x in ["login", "sign in", "register", "account"]):
            return "auth"
        return "unknown"

    def _detect_js_framework(self, result: Dict[str, Any]) -> Optional[str]:
        content = result.get("content") or result.get("html") or ""
        content_lower = content.lower()
        frameworks = {
            "react": ["react", "__react", "reactroot", "data-reactroot"],
            "vue": ["vue", "__vue", "v-app", "v-cloak"],
            "nextjs": ["__next", "next.js", "_next/static"],
            "angular": ["ng-app", "ng-version", "angular"],
            "svelte": ["svelte", "__svelte"],
        }
        for fw, indicators in frameworks.items():
            if any(ind in content_lower for ind in indicators):
                return fw
        return None

    def _requires_js(self, result: Dict[str, Any]) -> bool:
        content = result.get("content") or result.get("html") or ""
        return bool(self._detect_js_framework(result))

    def _detect_anti_bot(self, results: Dict[str, Any]) -> AntiBotLevel:
        for engine, result in results.items():
            if isinstance(result, dict):
                if not result.get("success"):
                    error = result.get("error", "").lower()
                    if any(x in error for x in ["403", "429", "blocked", "captcha", "challenge"]):
                        return AntiBotLevel.HIGH
            elif isinstance(result, list):
                # For API engine, empty list doesn't necessarily mean blocking
                # Only flag if we actually got an error response
                pass
        content = " ".join(
            str(r.get("content") or r.get("html") or "").lower()
            for r in results.values() if isinstance(r, dict)
        )
        if any(x in content for x in ["cloudflare", "akamai", "incapsula", "perimeterx", "datadome"]):
            return AntiBotLevel.EXTREME
        if any(x in content for x in ["captcha", "challenge", "access denied", "blocked", "rate limit"]):
            return AntiBotLevel.HIGH
        return AntiBotLevel.NONE

    def _get_anti_bot_details(self, results: Dict[str, Any]) -> Dict[str, Any]:
        details = {}
        for engine, result in results.items():
            if isinstance(result, dict):
                if not result.get("success"):
                    details[engine] = {"error": result.get("error"), "status": result.get("status_code")}
            elif isinstance(result, list):
                if len(result) == 0:
                    details[engine] = {"error": "No API endpoints found", "status": "blocked"}
        return details

    def _detect_pagination(self, result: Dict[str, Any]) -> bool:
        content = result.get("content") or result.get("html") or ""
        content_lower = content.lower()
        return any(x in content_lower for x in ["pagination", "page=", "pagenum", "next page", "load more"])

    def _get_pagination_type(self, result: Dict[str, Any]) -> Optional[str]:
        content = result.get("content") or result.get("html") or ""
        content_lower = content.lower()
        if "load more" in content_lower:
            return "load_more"
        elif "infinite scroll" in content_lower:
            return "infinite"
        elif "page=" in content_lower:
            return "url_param"
        return None

    def _classify_pages(self, result: Dict[str, Any]) -> Dict[str, int]:
        return {"list": 1, "detail": 1}

    def _extract_selectors(self, result: Dict[str, Any]) -> Dict[str, List[str]]:
        return {}

    def _extract_links(self, result: Dict[str, Any]) -> List[str]:
        content = result.get("html") or result.get("content") or ""
        links = re.findall(r'href=["\']([^"\']+)["\']', content)
        return [urljoin(result.get("url", ""), l) for l in links if l.startswith(("http", "/"))]

    def _detect_auth(self, result: Dict[str, Any]) -> bool:
        content = result.get("content") or result.get("html") or ""
        return any(x in content.lower() for x in ["login", "sign in", "sign up", "register", "password"])

    def _get_auth_type(self, result: Dict[str, Any]) -> Optional[str]:
        content = result.get("content") or result.get("html") or ""
        content_lower = content.lower()
        if "oauth" in content_lower:
            return "oauth2"
        elif "bearer" in content_lower:
            return "jwt"
        elif "api key" in content_lower:
            return "api_key"
        return None

    def _measure_performance(self, results: Dict[str, Any]) -> Dict[str, float]:
        metrics = {}
        for engine, result in results.items():
            if isinstance(result, dict) and "elapsed_ms" in result:
                metrics[f"{engine}_latency_ms"] = result["elapsed_ms"]
        return metrics

    def _recommend_engine(self, results: Dict[str, Any]) -> EngineType:
        if results.get("browser", {}).get("success"):
            return EngineType.BROWSER
        elif results.get("http", {}).get("success"):
            return EngineType.HTTP
        return EngineType.HTTP

    def _calculate_confidence(self, *args) -> float:
        return 0.8

    def _deep_pagination_analysis(self, sample_pages: List[Dict[str, Any]]) -> str:
        return "url_param"

    def _extract_pagination_selectors(self, sample_pages: List[Dict[str, Any]]) -> List[str]:
        return [".pagination a", "a[rel=next]", ".next a"]

    def _classify_pages_multi(self, sample_pages: List[Dict[str, Any]]) -> Dict[str, int]:
        return {"list": 1, "detail": max(0, len(sample_pages))}

    async def _detect_interactions(self, url: str, sample_pages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        return []

    def _infer_schemas(self, sample_pages: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
        return {}

    def _test_selectors_on_samples(self, sample_pages: List[Dict[str, Any]]) -> Dict[str, float]:
        return {}

    def _test_selectors_on_samples(self, sample_pages: List[Dict[str, Any]]) -> Dict[str, float]:
        return {}