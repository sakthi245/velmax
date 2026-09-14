from scraper.engines import EngineRegistry, EngineSelector
from scraper.engines.base import ScrapeRequest, EngineCapability
from scraper.config import load_config
from scraper.config.schemas import EngineType

def test_selector_creation():
    config = load_config().to_dict()
    selector = EngineSelector(EngineRegistry, config)
    assert selector.default_engine == "managed"


def test_selector_pdf_routes_to_firecrawl():
    config = load_config().to_dict()
    selector = EngineSelector(EngineRegistry, config)
    
    request = ScrapeRequest(url="https://example.com/doc.pdf", goal="extract")
    engine = selector.select(request)
    assert engine == "cloud"


def test_selector_js_routes_to_crawlee():
    config = load_config().to_dict()
    selector = EngineSelector(EngineRegistry, config)
    
    request = ScrapeRequest(url="https://app.example.com", goal="extract", engine_options={"render_js": True})
    engine = selector.select(request)
    assert engine == "managed"


def test_selector_explicit_engine():
    config = load_config().to_dict()
    selector = EngineSelector(EngineRegistry, config)
    
    request = ScrapeRequest(url="https://example.com", goal="extract", engine_options={"engine": "browser"})
    engine = selector.select(request)
    assert engine == "browser"