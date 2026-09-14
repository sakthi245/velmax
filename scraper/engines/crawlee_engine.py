from __future__ import annotations
from typing import Optional, AsyncIterator, Any
import asyncio
import time
import logging
from datetime import timedelta

from .base import (
    BaseEngine,
    ScrapeRequest,
    ScrapeResponse,
    EngineMetadata,
    EngineType,
    EngineCapability,
)

LOG = logging.getLogger(__name__)

try:
    from crawlee.crawlers import PlaywrightCrawler, BeautifulSoupCrawler
    from crawlee.proxy_configuration import ProxyConfiguration
    from crawlee.sessions import SessionPool
    from crawlee import ConcurrencySettings
    CRAWLEE_AVAILABLE = True
except ImportError:
    PlaywrightCrawler = None
    BeautifulSoupCrawler = None
    ProxyConfiguration = None
    SessionPool = None
    ConcurrencySettings = None
    CRAWLEE_AVAILABLE = False

class CrawleeEngine(BaseEngine):
    metadata = EngineMetadata(
        name="crawlee",
        type=EngineType.BROWSER,
        capabilities=[
            EngineCapability.JAVASCRIPT,
            EngineCapability.PROXY_ROTATION,
            EngineCapability.SESSION_PERSISTENCE,
            EngineCapability.ANTI_BOT,
            EngineCapability.LARGE_CRAWL,
        ],
        max_concurrent=20,
        avg_latency_ms=5000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )
    
    def __init__(self):
        self.crawler = None
        self.session_pool = None
        self.proxy_config = None
        self.config = {}
        self._initialized = False
        self._results: list[dict] = []
    
    async def initialize(self, config: dict):
        if not CRAWLEE_AVAILABLE:
            raise RuntimeError("crawlee not installed. Install with: pip install 'crawlee[playwright]'")
        
        start_time = time.time()
        self.config = config
        
        # Proxy configuration (direct only for now)
        proxy_tiers = config.get("proxy_tiers")
        proxy_urls = config.get("proxy_urls")
        
        if proxy_tiers:
            self.proxy_config = ProxyConfiguration(tiered_proxy_urls=proxy_tiers)
        elif proxy_urls:
            self.proxy_config = ProxyConfiguration(proxy_urls=proxy_urls)
        
        # Session pool with anti-blocking
        session_settings = config.get("session_settings", {})
        self.session_pool = SessionPool(
            max_pool_size=config.get("max_pool_size", 50),
            create_session_settings={
                "max_usage_count": session_settings.get("max_usage_count", 15),
                "max_age": timedelta(hours=session_settings.get("max_age_hours", 2)),
                "blocked_status_codes": session_settings.get("blocked_status_codes", [403, 429, 503]),
            }
        )
        
        # Choose crawler type
        use_browser = config.get("use_browser", True)
        crawler_class = PlaywrightCrawler if use_browser else BeautifulSoupCrawler
        
        self.crawler = crawler_class(
            proxy_configuration=self.proxy_config,
            use_session_pool=True,
            session_pool=self.session_pool,
            max_requests_per_crawl=config.get("max_requests", 1000),
            concurrency_settings=ConcurrencySettings(
                min_concurrency=1,
                max_concurrency=config.get("concurrency", 10),
                max_tasks_per_minute=config.get("rpm", 120),
                desired_concurrency=config.get("concurrency", 10),
            ),
            headless=config.get("headless", True),
            browser_type=config.get("browser_type", "chromium"),
        )
        
        self._setup_handlers(config)
        self._initialized = True
        
        from scraper.metrics import record_engine_init
        record_engine_init(self.metadata.name, time.time() - start_time)
        LOG.info(f"Crawlee engine initialized (browser={use_browser})")
    
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
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        if not self._initialized:
            raise RuntimeError("Crawlee engine not initialized")
        
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
                self._record_metrics(self.metadata.name, True, latency_ms)
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
            self._record_metrics(self.metadata.name, False, latency_ms)
            return response
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"Crawlee scrape failed for {request.url}: {e}")
            
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
            self._record_metrics(self.metadata.name, False, latency_ms)
            return response
    
    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        if not self._initialized:
            raise RuntimeError("Crawlee engine not initialized")
        
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
            LOG.warning(f"Crawlee crawl failed: {e}")
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
    
    async def shutdown(self):
        self._initialized = False
    
    def health_check(self) -> bool:
        return self._initialized and self.crawler is not None