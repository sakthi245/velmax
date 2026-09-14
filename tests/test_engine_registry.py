from scraper.engines import EngineRegistry
from scraper.engines.base import EngineCapability

def test_engine_registration():
    assert "scrapy" in EngineRegistry._engines
    assert "playwright" in EngineRegistry._engines
    # These may not be registered if dependencies not installed
    # assert "firecrawl" in EngineRegistry._engines
    # assert "crawlee" in EngineRegistry._engines

def test_engine_metadata():
    scrapy_meta = EngineRegistry.get_metadata("scrapy")
    assert scrapy_meta is not None
    assert scrapy_meta.name == "scrapy"
    assert EngineCapability.JAVASCRIPT not in scrapy_meta.capabilities
    
    playwright_meta = EngineRegistry.get_metadata("playwright")
    assert playwright_meta is not None
    assert EngineCapability.JAVASCRIPT in playwright_meta.capabilities
    assert EngineCapability.AUTH_FLOWS in playwright_meta.capabilities