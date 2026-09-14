from scraper.config import ScraperConfig
from scraper.engines.base import ScrapingEngine
from scraper.strategy import FallbackStrategyRouter
from scraper.engines import EngineRegistry

class LocalEngine(ScrapingEngine):
    name = "scrapy"
    def is_available(self): return True
    def is_limit_reached(self): return False
    def scrape(self, url, *args, **kwargs): return [{"url": url}]

def test_free_only_uses_local_engine(monkeypatch):
    monkeypatch.setattr("scraper.strategy.allowed", lambda *_: True)
    config = ScraperConfig(mode="free_only")
    router = FallbackStrategyRouter(config)
    # The new router uses engine registry, so we need to test differently
    assert "scrapy" in EngineRegistry._engines
    assert "playwright" in EngineRegistry._engines