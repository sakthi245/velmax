from __future__ import annotations
from typing import Optional, AsyncIterator, Any
import asyncio
import time
import logging

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
    from firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    FirecrawlApp = None
    FIRECRAWL_AVAILABLE = False

class FirecrawlEngine(BaseEngine):
    metadata = EngineMetadata(
        name="firecrawl",
        type=EngineType.MANAGED,
        capabilities=[
            EngineCapability.JAVASCRIPT,
            EngineCapability.LLM_EXTRACTION,
            EngineCapability.LARGE_CRAWL,
            EngineCapability.PDF_PARSING,
            EngineCapability.ANTI_BOT,
            EngineCapability.PROXY_ROTATION,
        ],
        max_concurrent=10,
        avg_latency_ms=15000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,
    )
    
    def __init__(self):
        self.client: Optional[FirecrawlApp] = None
        self.config: dict = {}
        self._initialized = False
    
    async def initialize(self, config: dict):
        if not FIRECRAWL_AVAILABLE:
            raise RuntimeError("firecrawl-py not installed. Install with: pip install firecrawl-py")
        
        start_time = time.time()
        self.config = config
        
        api_url = config.get("api_url", "http://localhost:3002")
        api_key = config.get("api_key", "local-dev")
        
        self.client = FirecrawlApp(api_key=api_key, api_url=api_url)
        
        # Verify connection with health check - use example.com as test URL
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, lambda: self.client.scrape("https://example.com"))
            self._initialized = True
            LOG.info(f"Firecrawl engine initialized: {api_url}")
        except Exception as e:
            LOG.warning(f"Firecrawl health check failed, but continuing: {e}")
            self._initialized = True
        
        from scraper.metrics import record_engine_init
        record_engine_init(self.metadata.name, time.time() - start_time)
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        if not self._initialized:
            raise RuntimeError("Firecrawl engine not initialized")
        
        start_time = time.time()
        opts = request.engine_options or {}
        loop = asyncio.get_event_loop()
        
        try:
            # Build scrape options - only use supported parameters
            scrape_opts = {
                "formats": opts.get("formats", ["markdown", "html"]),
                "only_main_content": opts.get("only_main_content", True),
                "proxy": opts.get("proxy", "auto"),
                "timeout": opts.get("timeout", 120000),
            }
            
            # Add optional parameters if provided
            if opts.get("actions"):
                scrape_opts["actions"] = opts["actions"]
            if opts.get("prompt"):
                scrape_opts["prompt"] = opts["prompt"]
            
            result = await loop.run_in_executor(
                None,
                lambda: self.client.scrape(request.url, **scrape_opts)
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            # Handle different response formats
            if hasattr(result, "model_dump"):
                data = result.model_dump()
                metadata = result.metadata.model_dump() if hasattr(result.metadata, "model_dump") else dict(result.metadata)
                markdown = getattr(result, "markdown", None)
                html = getattr(result, "html", None)
            else:
                data = dict(result) if result else {}
                metadata = data.get("metadata", {})
                markdown = data.get("markdown")
                html = data.get("html")
            
            response = ScrapeResponse(
                url=metadata.get("sourceURL", request.url),
                success=True,
                data=data,
                markdown=markdown,
                html=html,
                metadata=metadata,
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )
            
            self._record_metrics(self.metadata.name, True, latency_ms)
            return response
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"Firecrawl scrape failed for {request.url}: {e}")
            
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
            raise RuntimeError("Firecrawl engine not initialized")
        
        opts = config.get("crawl_options", {})
        loop = asyncio.get_event_loop()
        
        try:
            # Start crawl job
            crawl_result = await loop.run_in_executor(
                None,
                lambda: self.client.crawl(
                    urls[0] if urls else "",
                    limit=opts.get("limit", 1000),
                    max_depth=opts.get("max_depth", 3),
                    scrape_options=opts.get("scrape_options", {}),
                )
            )
            
            # Poll for results if async
            if hasattr(crawl_result, "status") and crawl_result.status == "scraping":
                job_id = crawl_result.id
                while True:
                    await asyncio.sleep(5)
                    status = await loop.run_in_executor(
                        None,
                        lambda: self.client.crawl_status(job_id)
                    )
                    if status.status == "completed":
                        crawl_result = status
                        break
                    elif status.status == "failed":
                        raise RuntimeError(f"Crawl failed: {status.error}")
            
            # Yield results
            pages = getattr(crawl_result, "data", []) or getattr(crawl_result, "pages", [])
            for page in pages:
                yield ScrapeResponse(
                    url=page.get("metadata", {}).get("sourceURL", ""),
                    success=True,
                    data=page,
                    markdown=page.get("markdown"),
                    html=page.get("html"),
                    metadata=page.get("metadata", {}),
                    engine=self.metadata.name,
                )
                
        except Exception as e:
            LOG.warning(f"Firecrawl crawl failed: {e}")
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
        if not self._initialized or not self.client:
            return False
        try:
            # Use a simple known URL for health check
            self.client.scrape("https://example.com")
            return True
        except Exception as e:
            LOG.warning(f"Firecrawl health check failed: {e}")
            return False