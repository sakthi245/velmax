import pytest
from scraper.config import ScraperConfig
from scraper.strategy import FallbackStrategyRouter
from scraper.engines.base import BaseEngine, ScrapeRequest, ScrapeResponse, EngineMetadata, EngineType, EngineCapability

class FailingEngine(BaseEngine):
    metadata = EngineMetadata(
        name="crawlee",
        type=EngineType.BROWSER,
        capabilities=[EngineCapability.JAVASCRIPT],
        max_concurrent=10,
    )
    
    def __init__(self):
        self._initialized = True
    
    async def initialize(self, config: dict): pass
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        return ScrapeResponse(
            url=request.url, success=False, data={}, markdown=None, html=None,
            metadata={}, engine=self.metadata.name, error="429 quota exceeded", latency_ms=0
        )
    
    async def crawl(self, urls, config): return []
    async def shutdown(self): pass
    def health_check(self): return True

class WorkingEngine(BaseEngine):
    metadata = EngineMetadata(
        name="playwright",
        type=EngineType.BROWSER,
        capabilities=[EngineCapability.JAVASCRIPT, EngineCapability.AUTH_FLOWS],
        max_concurrent=5,
    )
    
    def __init__(self):
        self._initialized = True
    
    async def initialize(self, config: dict): pass
    
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        return ScrapeResponse(
            url=request.url, success=True, data={"url": request.url},
            markdown="test", html="test", metadata={"title": "Test"},
            engine=self.metadata.name, latency_ms=100
        )
    
    async def crawl(self, urls, config): return []
    async def shutdown(self): pass
    def health_check(self): return True

@pytest.mark.asyncio
async def test_limit_falls_back_to_local(monkeypatch):
    monkeypatch.setattr("scraper.strategy.allowed", lambda *_: True)
    
    config = ScraperConfig()
    router = FallbackStrategyRouter(config)
    await router.initialize()
    
    # Manually register test engines
    from scraper.engines import EngineRegistry
    EngineRegistry._instances["crawlee"] = FailingEngine()
    EngineRegistry._instances["playwright"] = WorkingEngine()
    EngineRegistry._metadata["crawlee"] = FailingEngine.metadata
    EngineRegistry._metadata["playwright"] = WorkingEngine.metadata
    
    # Force use of crawlee as primary engine
    result = await router.scrape("https://app.example.com", "extract", engine="crawlee")
    assert result.engine == "playwright"
    assert any("crawlee" in str(a) for a in result.attempts)