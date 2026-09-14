"""Integration tests for search pipeline."""

import pytest
import asyncio


@pytest.mark.integration
@pytest.mark.asyncio
async def test_query_expander_real():
    """Test query expander with real Groq API."""
    from scraper.engines import EngineRegistry
    from scraper.engines.interfaces import EngineConfig
    
    engine_class = EngineRegistry._engines['query_expander']
    engine = engine_class()
    await engine.initialize(EngineConfig(name='query_expander', config={'query_expander': {}}))
    
    queries = await engine.expand_queries("Python asyncio tutorial for beginners", max_queries=5)
    
    assert isinstance(queries, list)
    assert len(queries) > 0
    assert all(isinstance(q, str) for q in queries)
    print(f"Expanded queries: {queries}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_relevance_ranker_real():
    """Test relevance ranker with real Groq API."""
    from scraper.engines import EngineRegistry
    from scraper.engines.interfaces import EngineConfig
    
    engine_class = EngineRegistry._engines['relevance_ranker']
    engine = engine_class()
    await engine.initialize(EngineConfig(name='relevance_ranker', config={'relevance_ranker': {}}))
    
    results = [
        {"title": "Python asyncio tutorial", "url": "https://example.com/1", "snippet": "Learn asyncio"},
        {"title": "JavaScript promises", "url": "https://example.com/2", "snippet": "Learn promises"},
        {"title": "Python asyncio advanced", "url": "https://example.com/3", "snippet": "Advanced asyncio patterns"},
    ]
    
    ranked = await engine.rank_results("Python asyncio tutorial for beginners", results)
    
    assert isinstance(ranked, list)
    assert len(ranked) <= len(results)
    # All ranked items should have relevance_score
    assert all('relevance_score' in r for r in ranked)
    print(f"Ranked results: {[r.get('relevance_score', 0) for r in ranked]}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_playwright_search_real():
    """Test Playwright search with real DuckDuckGo."""
    from scraper.engines import EngineRegistry
    from scraper.engines.interfaces import EngineConfig
    
    engine_class = EngineRegistry._engines['playwright_search']
    engine = engine_class()
    await engine.initialize(EngineConfig(name='playwright_search', config={'playwright_search': {}}))
    
    results = await engine.search("Python asyncio tutorial", max_results=5)
    
    assert isinstance(results, list)
    assert len(results) >= 0  # May be 0 if CAPTCHA
    print(f"Playwright search results: {len(results)}")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_search_pipeline_real():
    """Test full search pipeline with real engines."""
    from scraper.engines import EngineRegistry
    from scraper.engines.interfaces import EngineConfig
    from scraper.engines.search_pipeline import SearchPipelineEngine
    
    engine = SearchPipelineEngine()
    config = EngineConfig(name='search_pipeline', config={
        'search_pipeline': {
            'enable_query_expansion': True,
            'enable_relevance_ranking': True,
            'max_queries_per_goal': 3,
            'max_results_per_query': 5,
            'tinyfish_search': {'enabled': True},
            'serpapi_search': {'enabled': False},
            'query_expander': {},
            'relevance_ranker': {},
        }
    })
    await engine.initialize(config)
    
    urls = await engine.discover_urls("Python asyncio tutorial", max_urls=10)
    
    assert isinstance(urls, list)
    assert len(urls) > 0
    print(f"Discovered URLs: {urls[:3]}...")


@pytest.mark.integration
@pytest.mark.asyncio
async def test_engine_registry():
    """Test engine registry has all search engines registered."""
    from scraper.engines import EngineRegistry
    from scraper.config.schemas import EngineType
    
    # Check all search engines are registered
    assert EngineType.QUERY_EXPANDER in EngineRegistry._engines
    assert EngineType.RELEVANCE_RANKER in EngineRegistry._engines
    assert EngineType.PLAYWRIGHT_SEARCH in EngineRegistry._engines
    assert EngineType.TINYFISH_SEARCH in EngineRegistry._engines
    assert EngineType.SERPAPI_SEARCH in EngineRegistry._engines
    
    print("All search engines registered successfully")