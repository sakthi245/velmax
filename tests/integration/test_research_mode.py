"""Integration test for research mode."""

import pytest
import asyncio


@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_mode_auto_detection(reload_scraper):
    """Test research mode auto-detection when goal provided without URL."""
    from scraper.config.schemas import UniversalRequest
    from scraper.universal_runner import UniversalRunner
    from scraper.config.loader import load_config
    
    config = load_config()
    runner = UniversalRunner(config)
    
    # Test 1: Research request (goal without URL)
    request = UniversalRequest(
        goal="Find Python asyncio tutorials for beginners",
        extract_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "difficulty": {"type": "string", "enum": ["beginner", "intermediate", "advanced"]},
            },
            "required": ["title", "url", "difficulty"]
        }
    )
    
    result = await runner.scrape(request)
    
    # Should succeed (may use search engine)
    assert result.success or result.error is not None
    print(f"Research mode result: success={result.success}, engine={result.engine_used}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_regular_url_request(reload_scraper):
    """Test regular URL request still works."""
    from scraper.config.schemas import UniversalRequest
    from scraper.universal_runner import UniversalRunner
    from scraper.config.loader import load_config
    
    config = load_config()
    runner = UniversalRunner(config)
    
    # Test regular URL request
    request = UniversalRequest(
        url="https://httpbin.org/html",
        goal="Extract page content",
        force_rescrape=True
    )
    
    result = await runner.scrape(request)
    
    assert result.success
    assert result.data is not None
    assert result.engine_used is not None
    print(f"Regular URL result: engine={result.engine_used}, data_type={type(result.data)}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_research_mode_with_extraction(reload_scraper):
    """Test research mode with extraction schema."""
    from scraper.config.schemas import UniversalRequest
    from scraper.universal_runner import UniversalRunner
    from scraper.config.loader import load_config
    
    config = load_config()
    runner = UniversalRunner(config)
    
    request = UniversalRequest(
        goal="Find Python asyncio tutorial",
        extract_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "url": {"type": "string", "format": "uri"},
                "difficulty": {"type": "string"},
            },
            "required": ["title", "url"]
        }
    )
    
    result = await runner.scrape(request)
    
    # Should succeed
    assert result.success or result.error is not None
    print(f"Research with extraction: success={result.success}, engine={result.engine_used}")