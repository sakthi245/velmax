from __future__ import annotations

import asyncio
import logging
import time
import urllib.parse
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from playwright.async_api import (
    Browser as PlaywrightBrowser,
    BrowserContext as PlaywrightBrowserContext,
    Page,
    async_playwright,
)

from .interfaces import EngineConfig, EngineMetadata, BaseEngine
from ..config.schemas import EngineType, EngineCapability
from .browser_pool import AdaptiveBrowserPool, create_adaptive_pool
from .stealth import StealthManager, StealthConfig
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class SearchResult:
    """Search result from DuckDuckGo."""
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0
    source: str = "duckduckgo"
    query: str = ""


@dataclass
class PlaywrightSearchConfig:
    """Configuration for Playwright search engine."""
    search_engine: str = "duckduckgo"
    headless: bool = True
    stealth_mode: bool = True
    max_pages_per_query: int = 2
    results_per_page: int = 10
    captcha_timeout: int = 10000
    request_timeout: float = 30.0
    delay_between_pages: float = 1.5
    resource_blocking: Dict[str, bool] = field(default_factory=lambda: {
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


class PlaywrightSearchEngine(BaseEngine):
    """Playwright-based search engine for DuckDuckGo with CAPTCHA handling."""
    
    metadata = EngineMetadata(
        name="playwright_search",
        engine_type=EngineType.BROWSER,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.STEALTH,
            EngineCapability.REST_API,
        },
        max_concurrent=3,
        avg_latency_ms=10000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(self) -> None:
        super().__init__()
        self._playwright: Optional[Any] = None
        self._browser: Optional[PlaywrightBrowser] = None
        self._pool: Optional[AdaptiveBrowserPool] = None
        self._stealth_manager: Optional[StealthManager] = None
        self._engine_config: PlaywrightSearchConfig = PlaywrightSearchConfig()
        self._default_context_config: Dict[str, Any] = {}

    def _create_context_fn(self):
        """Return a function that creates new browser contexts."""
        async def create_context(config: Dict[str, Any]) -> PlaywrightBrowserContext:
            if not self._browser:
                raise RuntimeError("Browser not launched")

            merged_config = {**self._default_context_config, **config}
            context = await self._browser.new_context(**merged_config)

            if self._engine_config.stealth_mode and self._stealth_manager:
                await self._stealth_manager.apply_to_context(context)

            if self._engine_config.resource_blocking:
                await self._setup_resource_blocking(context)

            return context

        return create_context

    async def _setup_resource_blocking(self, context: PlaywrightBrowserContext) -> None:
        """Set up resource blocking based on configuration."""
        block_types = []
        blocking = self._engine_config.resource_blocking

        if blocking.get("images"):
            block_types.append("image")
        if blocking.get("fonts"):
            block_types.append("font")
        if blocking.get("css"):
            block_types.append("stylesheet")
        if blocking.get("media"):
            block_types.extend(["media", "video", "audio"])
        if blocking.get("websocket"):
            block_types.append("websocket")

        if block_types:
            await context.route("**/*", lambda route: route.abort()
                if route.request.resource_type in block_types else route.continue_())

    async def _launch_browser(self) -> PlaywrightBrowser:
        """Launch the Playwright browser with configured options."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        if self._engine_config.headless:
            launch_args.append("--headless=new")

        if self._engine_config.ignore_https_errors:
            launch_args.append("--ignore-certificate-errors")

        self._browser = await self._playwright.chromium.launch(
            headless=self._engine_config.headless,
            args=launch_args,
            timeout=60000,
        )
        return self._browser

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize the search engine with browser and pool."""
        search_config = config.config.get("playwright_search", {})
        self._engine_config = PlaywrightSearchConfig(**search_config)

        if self._engine_config.stealth_mode:
            stealth_config = StealthConfig(**search_config.get("stealth_config", {}))
            self._stealth_manager = StealthManager(stealth_config)

        self._default_context_config = {
            "viewport": {
                "width": self._engine_config.viewport_width,
                "height": self._engine_config.viewport_height,
            },
            "device_scale_factor": 1.0,
            "is_mobile": False,
            "has_touch": False,
            "locale": self._engine_config.locale,
            "timezone_id": self._engine_config.timezone_id,
            "ignore_https_errors": self._engine_config.ignore_https_errors,
            "java_script_enabled": self._engine_config.java_script_enabled,
        }

        await self._launch_browser()

        from ..config.schemas import BrowserEngineConfig, BrowserContextConfig
        
        LOG.info(f"PlaywrightSearchEngine initialize - config.config keys: {list(config.config.keys())}")
        search_config = config.config.get("search_pipeline", {})
        LOG.info(f"PlaywrightSearchEngine search_config keys: {list(search_config.keys())}")
        
        # Use browser_engine config from passed config if available, otherwise use defaults
        browser_engine_config = search_config.get("browser_engine", {})
        LOG.info(f"PlaywrightSearchEngine browser_engine config: {browser_engine_config}")
        pool_config = BrowserEngineConfig(
            pool_min=browser_engine_config.get("pool_min", 1),
            pool_max=browser_engine_config.get("pool_max", self.metadata.max_concurrent),
            pool_max_memory_mb=browser_engine_config.get("pool_max_memory_mb", 512),
            min_idle_timeout_ms=browser_engine_config.get("min_idle_timeout_ms", 30000),
            max_idle_timeout_ms=browser_engine_config.get("max_idle_timeout_ms", 300000),
            scale_up_on_queue=browser_engine_config.get("scale_up_on_queue", 2),
            scale_down_idle_ratio=browser_engine_config.get("scale_down_idle_ratio", 0.5),
            recycle_after_memory_mb=browser_engine_config.get("recycle_after_memory_mb", 200),
            recycle_after_pages=browser_engine_config.get("recycle_after_pages", 50),
            recycle_on_error_rate=browser_engine_config.get("recycle_on_error_rate", 0.1),
            adaptive_pool=browser_engine_config.get("adaptive_pool", True),
            context_config=BrowserContextConfig(
                viewport_width=self._engine_config.viewport_width,
                viewport_height=self._engine_config.viewport_height,
                locale=self._engine_config.locale,
                timezone_id=self._engine_config.timezone_id,
            ),
            stealth_mode=self._engine_config.stealth_mode,
            resource_blocking=self._engine_config.resource_blocking,
        )

        self._pool = create_adaptive_pool(
            config=pool_config,
            create_context_fn=self._create_context_fn(),
            engine_name=self.metadata.name,
        )
        await self._pool.start()

        self._initialized = True
        LOG.info("PlaywrightSearchEngine initialized with adaptive pool")

    async def shutdown(self) -> None:
        """Shutdown the search engine and cleanup resources."""
        if self._pool:
            await self._pool.stop()
            self._pool = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def health_check(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def search(self, query: str, max_results: int = 10) -> List[SearchResult]:
        """Search DuckDuckGo and return results."""
        if not self._initialized:
            raise RuntimeError("PlaywrightSearchEngine not initialized")

        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://duckduckgo.com/html/?q={encoded_query}"

        all_results = []
        seen_urls = set()

        for page_num in range(self._engine_config.max_pages_per_query):
            if len(all_results) >= max_results:
                break

            page_url = url if page_num == 0 else f"{url}&s={page_num * 50}"
            
            LOG.info(f"Searching page {page_num + 1} for query: {query}")
            context = await self._pool.get_context()
            LOG.info(f"Got context from pool")
            try:
                page = await context.new_page()
                LOG.info(f"Created new page")
                try:
                    LOG.info(f"Navigating to {page_url}")
                    # Use domcontentloaded for faster loading, networkidle waits for CAPTCHA resources
                    await page.goto(page_url, wait_until="domcontentloaded", timeout=int(self._engine_config.request_timeout * 1000))
                    LOG.info(f"Page loaded")
                    
                    LOG.info(f"Waiting for CAPTCHA solve (timeout={self._engine_config.captcha_timeout}ms)")
                    captcha_solved = await self._stealth_manager.wait_for_captcha_solve(page, timeout=self._engine_config.captcha_timeout)
                    LOG.info(f"CAPTCHA solved: {captcha_solved}")
                    
                    if not captcha_solved:
                        LOG.warning(f"CAPTCHA not solved for query '{query}' (page {page_num + 1}), skipping")
                        continue
                    
                    LOG.info(f"Extracting results")
                    results = await self._extract_results(page, query)
                    LOG.info(f"Extracted {len(results)} results")
                    for result in results:
                        if result.url not in seen_urls:
                            seen_urls.add(result.url)
                            all_results.append(result)
                            if len(all_results) >= max_results:
                                break
                    
                    if page_num < self._engine_config.max_pages_per_query - 1:
                        await asyncio.sleep(self._engine_config.delay_between_pages)
                        
                finally:
                    await page.close()
                    LOG.info(f"Page closed")
            finally:
                await self._pool.return_context(context)
                LOG.info(f"Context returned to pool")

            if len(results) == 0:
                LOG.info(f"No results on page {page_num + 1}, breaking")
                break

        LOG.info(f"Search completed, returning {len(all_results)} results")
        return all_results[:max_results]

    async def _extract_results(self, page: Page, query: str) -> List[SearchResult]:
        """Extract search results from the page."""
        results = []
        position = 0

        selectors_to_try = [
            '[data-testid="result"]',
            '.result',
            '.web-result',
            'table tr',
        ]

        result_elements = []
        for selector in selectors_to_try:
            result_elements = await page.query_selector_all(selector)
            if result_elements:
                LOG.debug(f"Found {len(result_elements)} results with selector: {selector}")
                break

        if not result_elements:
            LOG.warning("No result elements found on page")
            return results

        title_selectors = ['h2 a', '.result__title', '[data-testid="result-title"]', 'h3 a', 'a.result__url']
        snippet_selectors = ['.result__snippet', '.snippet', '[data-testid="result-snippet"]', '.result__snippet']
        url_selectors = ['a.result__url', '.result__url', '[data-testid="result-url"]', 'h2 a']

        for elem in result_elements:
            if len(results) >= self._engine_config.results_per_page:
                break

            try:
                title = ""
                for sel in title_selectors:
                    title_elem = await elem.query_selector(sel)
                    if title_elem:
                        title = await title_elem.inner_text()
                        if title:
                            break

                snippet = ""
                for sel in snippet_selectors:
                    snippet_elem = await elem.query_selector(sel)
                    if snippet_elem:
                        snippet = await snippet_elem.inner_text()
                        if snippet:
                            break

                url = ""
                for sel in url_selectors:
                    url_elem = await elem.query_selector(sel)
                    if url_elem:
                        url = await url_elem.get_attribute("href")
                        if url:
                            break

                if not url:
                    link = await elem.query_selector("a")
                    if link:
                        url = await link.get_attribute("href")

                if url and url.startswith("//"):
                    url = "https:" + url
                elif url and url.startswith("/"):
                    url = "https://duckduckgo.com" + url

                parsed = urllib.parse.urlparse(url)
                if parsed.netloc in ("duckduckgo.com", "duckduckgo.com"):
                    continue

                if url and (title or snippet):
                    position += 1
                    results.append(SearchResult(
                        url=url,
                        title=title[:200] if title else "",
                        snippet=snippet[:500] if snippet else "",
                        position=position,
                        source="duckduckgo",
                        query=query,
                    ))

            except Exception as e:
                LOG.debug(f"Error extracting result: {e}")
                continue

        return results

    async def search_multiple(self, queries: List[str], max_results_per_query: int = 10, delay_between_queries: float = 1.0) -> Dict[str, List[SearchResult]]:
        """Search multiple queries."""
        results = {}
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(delay_between_queries)
            try:
                results[query] = await self.search(query, max_results=max_results_per_query)
            except Exception as e:
                LOG.error(f"Search failed for '{query}': {e}")
                results[query] = []
        return results