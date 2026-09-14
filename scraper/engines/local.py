from __future__ import annotations
from typing import Any, AsyncIterator, Optional
from html.parser import HTMLParser
import requests
import asyncio
import time
import logging

from playwright.sync_api import sync_playwright

from .base import (
    BaseEngine,
    ScrapeRequest,
    ScrapeResponse,
    EngineMetadata,
    EngineType,
    EngineCapability,
)

LOG = logging.getLogger(__name__)

class _Text(HTMLParser):
    def __init__(self): 
        super().__init__(); 
        self.title = ""; 
        self._in_title = False; 
        self.bits: list[str] = []
    
    def handle_starttag(self, tag, attrs):
        self._in_title = tag == "title"
    
    def handle_endtag(self, tag):
        if tag == "title": 
            self._in_title = False
    
    def handle_data(self, data):
        data = " ".join(data.split())
        if data:
            self.bits.append(data)
            if self._in_title: 
                self.title += data

def record_from_html(url: str, html: str, engine: str) -> dict[str, Any]:
    parser = _Text(); 
    parser.feed(html)
    return {"url": url, "title": parser.title, "text": " ".join(parser.bits), "engine": engine}

class ScrapyEngine(BaseEngine):
    metadata = EngineMetadata(
        name="scrapy",
        type=EngineType.HTTP,
        capabilities=[],  # No JS support
        max_concurrent=16,
        avg_latency_ms=2000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )
    
    def __init__(self):
        self._initialized = False
    
    async def initialize(self, config: dict):
        self._initialized = True
        LOG.info("Scrapy engine initialized")
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        if not self._initialized:
            raise RuntimeError("Scrapy engine not initialized")
        
        start_time = time.time()
        
        try:
            timeout = request.engine_options.get("timeout", 20)
            agent = request.engine_options.get("user_agent", "CompliantFreeFirstScraper/0.1")
            
            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.get(
                    request.url,
                    timeout=timeout,
                    headers={"User-Agent": agent},
                    allow_redirects=True
                )
            )
            response.raise_for_status()
            
            record = record_from_html(response.url, response.text, self.metadata.name)
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            res = ScrapeResponse(
                url=response.url,
                success=True,
                data=record,
                markdown=None,
                html=response.text,
                metadata={"title": record["title"], "status_code": response.status_code},
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )
            self._record_metrics(self.metadata.name, True, latency_ms)
            return res
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"Scrapy scrape failed for {request.url}: {e}")
            
            res = ScrapeResponse(
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
            return res
    
    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        for url in urls:
            yield await self.scrape(ScrapeRequest(url=url, engine_options=config))
    
    async def shutdown(self):
        self._initialized = False
    
    def health_check(self) -> bool:
        return True
    
    def is_available(self) -> bool:
        return True
    
    def is_limit_reached(self) -> bool:
        return False
    
    def scrape_legacy(self, url: str, goal: str, schema: dict[str, Any], **kwargs: Any):
        """Legacy sync interface for backward compatibility"""
        import asyncio
        request = ScrapeRequest(url=url, goal=goal, schema=schema, engine_options=kwargs)
        response = asyncio.run(self.scrape(request))
        return response.to_legacy_format()

class PlaywrightEngine(BaseEngine):
    metadata = EngineMetadata(
        name="playwright",
        type=EngineType.BROWSER,
        capabilities=[
            EngineCapability.JAVASCRIPT,
            EngineCapability.AUTH_FLOWS,
        ],
        max_concurrent=5,
        avg_latency_ms=8000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )
    
    def __init__(self):
        self._initialized = False
    
    async def initialize(self, config: dict):
        self._initialized = True
        LOG.info("Playwright engine initialized")
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        if not self._initialized:
            raise RuntimeError("Playwright engine not initialized")
        
        start_time = time.time()
        
        try:
            timeout = request.engine_options.get("timeout", 20) * 1000
            agent = request.engine_options.get("user_agent", "CompliantFreeFirstScraper/0.1")
            wait_for = request.engine_options.get("wait_for_selector")
            wait_until = request.engine_options.get("wait_until", "networkidle")
            
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._scrape_sync,
                request.url,
                timeout,
                agent,
                wait_for,
                wait_until,
            )
            
            latency_ms = int((time.time() - start_time) * 1000)
            
            res = ScrapeResponse(
                url=result["url"],
                success=True,
                data=result,
                markdown=None,
                html=result.get("html", ""),
                metadata={"title": result.get("title", ""), "status_code": 200},
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )
            self._record_metrics(self.metadata.name, True, latency_ms)
            return res
            
        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"Playwright scrape failed for {request.url}: {e}")
            
            res = ScrapeResponse(
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
            return res
    
    def _scrape_sync(self, url: str, timeout: int, agent: str, wait_for: Optional[str], wait_until: Optional[str] = None, engine_options: Optional[dict] = None) -> dict:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=agent)
                
                # Determine wait strategy based on URL/engine options
                if engine_options:
                    wait_until = engine_options.get("wait_until", "domcontentloaded")
                    wait_for = engine_options.get("wait_for_selector", wait_for)
                else:
                    wait_until = wait_until or "domcontentloaded"
                
                page.goto(url, wait_until=wait_until, timeout=timeout)
                
                if wait_for:
                    page.wait_for_selector(wait_for, timeout=timeout)
                
                # Additional wait for dynamic content
                if engine_options and engine_options.get("extra_wait_ms"):
                    page.wait_for_timeout(engine_options["extra_wait_ms"])
                
                html = page.content()
                record = record_from_html(page.url, html, self.metadata.name)
                record["html"] = html
                return record
            finally:
                browser.close()
    
    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        for url in urls:
            yield await self.scrape(ScrapeRequest(url=url, engine_options=config))
    
    async def shutdown(self):
        self._initialized = False
    
    def health_check(self) -> bool:
        try:
            import playwright.sync_api
            return True
        except ImportError:
            return False
    
    def is_available(self) -> bool:
        try:
            import playwright.sync_api
            return True
        except ImportError:
            return False
    
    def is_limit_reached(self) -> bool:
        return False
    
    def scrape_legacy(self, url: str, goal: str, schema: dict[str, Any], **kwargs: Any):
        """Legacy sync interface for backward compatibility"""
        import asyncio
        request = ScrapeRequest(url=url, goal=goal, schema=schema, engine_options=kwargs)
        response = asyncio.run(self.scrape(request))
        return response.to_legacy_format()