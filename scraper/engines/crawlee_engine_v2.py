from __future__ import annotations

from typing import Any, AsyncIterator, Optional
import asyncio
import time
import logging
from datetime import timedelta

from .base_v2 import BaseEngineV2
from .interfaces import EngineConfig, EngineMetadata
from ..config.schemas import EngineType, EngineCapability
from ..engines.base import ScrapeRequest, ScrapeResponse
from ..utils.observability import get_logger

LOG = logging.getLogger(__name__)


class CrawleeEngineV2(BaseEngineV2):
    """V2 version of CrawleeEngine - inherits from BaseEngineV2 with circuit breaker, rate limiter, retry."""
    
    metadata = EngineMetadata(
        name="crawlee",
        engine_type=EngineType.MANAGED,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.PROXY_ROTATION,
            EngineCapability.SESSION_PERSISTENCE,
            EngineCapability.ANTI_BOT,
            EngineCapability.LARGE_CRAWL,
        },
        max_concurrent=20,
        avg_latency_ms=5000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        circuit_breaker_config: Optional[dict] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self.crawler = None
        self.session_pool = None
        self.proxy_config = None
        self.config = {}
        self._results: list[dict] = []

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Handle both EngineConfig object and plain dict
        if isinstance(config, EngineConfig):
            self.config = config.config.get("crawlee", {})
        else:
            self.config = config.get("crawlee", {})

        try:
            from crawlee.crawlers import PlaywrightCrawler, BeautifulSoupCrawler
            from crawlee.proxy_configuration import ProxyConfiguration
            from crawlee.sessions import SessionPool
            from crawlee import ConcurrencySettings
        except ImportError:
            raise RuntimeError("crawlee not installed. Install with: pip install 'crawlee[playwright]'")

        proxy_tiers = self.config.get("proxy_tiers")
        proxy_urls = self.config.get("proxy_urls")

        if proxy_tiers:
            self.proxy_config = ProxyConfiguration(tiered_proxy_urls=proxy_tiers)
        elif proxy_urls:
            self.proxy_config = ProxyConfiguration(proxy_urls=proxy_urls)

        session_settings = self.config.get("session_settings", {})
        self.session_pool = SessionPool(
            max_pool_size=self.config.get("max_pool_size", 50),
            create_session_settings={
                "max_usage_count": session_settings.get("max_usage_count", 15),
                "max_age": timedelta(hours=session_settings.get("max_age_hours", 2)),
                "blocked_status_codes": session_settings.get("blocked_status_codes", [403, 429, 503]),
            }
        )

        use_browser = self.config.get("use_browser", True)
        crawler_class = PlaywrightCrawler if use_browser else BeautifulSoupCrawler

        self.crawler = crawler_class(
            proxy_configuration=self.proxy_config,
            use_session_pool=True,
            session_pool=self.session_pool,
            max_requests_per_crawl=self.config.get("max_requests", 1000),
            concurrency_settings=ConcurrencySettings(
                min_concurrency=1,
                max_concurrency=self.config.get("concurrency", 10),
                max_tasks_per_minute=self.config.get("rpm", 120),
                desired_concurrency=self.config.get("concurrency", 10),
            ),
            headless=self.config.get("headless", True),
            browser_type=self.config.get("browser_type", "chromium"),
        )

        self._setup_handlers(self.config)
        self._initialized = True
        LOG.info(f"CrawleeEngineV2 initialized (browser={use_browser})")

    def _setup_handlers(self, config: dict):
        follow_links = config.get("follow_links", False)

        @self.crawler.router.default_handler
        async def default_handler(context):
            if hasattr(context, "page"):
                html = await context.page.content()
                title = await context.page.title()
            else:
                html = str(context.soup)
                title = context.soup.title.string if context.soup.title else None

            result = {
                "url": context.request.url,
                "html": html,
                "title": title,
                "status_code": getattr(context.response, 'status_code', getattr(context.response, 'status_text', 200)) if context.response else 200,
            }
            self._results.append(result)

            if follow_links:
                await context.enqueue_links()

    async def _shutdown_impl(self) -> None:
        self._initialized = False

    def _health_check_impl(self) -> bool:
        return self._initialized and self.crawler is not None

    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        """Legacy-compatible scrape method."""
        if not self._initialized:
            raise RuntimeError("CrawleeEngineV2 not initialized")

        start_time = time.time()
        self._results = []

        try:
            await self.crawler.run([request.url])

            latency_ms = int((time.time() - start_time) * 1000)

            if self._results:
                r = self._results[0]
                response = ScrapeResponse(
                    url=r["url"],
                    success=True,
                    data={"title": r["title"], "html": r["html"]},
                    markdown=None,
                    html=r["html"],
                    metadata={"title": r["title"], "status_code": r["status_code"]},
                    engine=self.metadata.name,
                    latency_ms=latency_ms,
                )
                self.metrics.record_request(True, latency_ms)
                return response

            latency_ms = int((time.time() - start_time) * 1000)
            response = ScrapeResponse(
                url=request.url,
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine=self.metadata.name,
                error="No result returned",
                latency_ms=latency_ms,
            )
            self.metrics.record_request(False, latency_ms)
            return response

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"CrawleeEngineV2 scrape failed for {request.url}: {e}")

            response = ScrapeResponse(
                url=request.url,
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine=self.metadata.name,
                error=str(e),
                latency_ms=latency_ms,
            )
            self.metrics.record_request(False, latency_ms, str(e))
            return response

    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        if not self._initialized:
            raise RuntimeError("CrawleeEngineV2 not initialized")

        self._results = []
        follow_links = config.get("follow_links", True)

        @self.crawler.router.default_handler
        async def crawl_handler(context):
            if hasattr(context, "page"):
                html = await context.page.content()
                title = await context.page.title()
            else:
                html = str(context.soup)
                title = context.soup.title.string if context.soup.title else None

            result = {
                "url": context.request.url,
                "html": html,
                "title": title,
                "status_code": context.response.status_code if context.response else 200,
            }
            self._results.append(result)

            if follow_links:
                await context.enqueue_links()

        try:
            await self.crawler.run(urls)

            for r in self._results:
                yield ScrapeResponse(
                    url=r["url"],
                    success=True,
                    data={"title": r["title"], "html": r["html"]},
                    markdown=None,
                    html=r["html"],
                    metadata={"title": r["title"], "status_code": r["status_code"]},
                    engine=self.metadata.name,
                )
        except Exception as e:
            LOG.warning(f"CrawleeEngineV2 crawl failed: {e}")
            yield ScrapeResponse(
                url=urls[0] if urls else "",
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine=self.metadata.name,
                error=str(e),
            )

    async def _crawl_impl(self, strategy) -> AsyncIterator[Any]:
        pass  # Not used in legacy interface


async def create_crawlee_engine_v2(config: EngineConfig) -> CrawleeEngineV2:
    """Factory function to create CrawleeEngineV2 instance."""
    engine = CrawleeEngineV2()
    await engine.initialize(config)
    return engine