"""Unit tests for PlaywrightSearchEngine."""

import pytest
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from scraper.engines.playwright_search import PlaywrightSearchEngine, PlaywrightSearchConfig, SearchResult
from scraper.engines.interfaces import EngineConfig


class TestPlaywrightSearchEngine:
    """Tests for PlaywrightSearchEngine."""

    @pytest.fixture
    def engine(self):
        """Create a PlaywrightSearchEngine instance."""
        return PlaywrightSearchEngine()

    @pytest.fixture
    def engine_config(self):
        """Create a test EngineConfig."""
        return EngineConfig(
            name="playwright_search",
            config={
                "playwright_search": {
                    "headless": True,
                    "stealth_mode": True,
                    "captcha_timeout": 1000,
                    "request_timeout": 5.0,
                    "max_pages_per_query": 1,
                }
            }
        )

    def test_engine_creation(self, engine):
        """Test engine can be created."""
        assert engine is not None
        assert engine.metadata.name == "playwright_search"
        assert engine.metadata.engine_type.value == "browser"
        assert engine.metadata.max_concurrent == 3

    def test_engine_metadata(self, engine):
        """Test engine metadata."""
        assert "javascript" in [c.value for c in engine.metadata.capabilities]
        assert "stealth" in [c.value for c in engine.metadata.capabilities]
        assert "rest_api" in [c.value for c in engine.metadata.capabilities]
        assert engine.metadata.cost_per_1k_pages == 0.0
        assert engine.metadata.requires_external_service is False

    @pytest.mark.asyncio
    async def test_initialize(self, engine, engine_config):
        """Test engine initialization."""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock) as mock_launch:
            with patch.object(engine, '_pool') as mock_pool:
                mock_pool.start = AsyncMock()
                mock_pool.stop = AsyncMock()
                
                await engine.initialize(engine_config)
                
                assert engine._initialized is True
                mock_launch.assert_called_once()
                mock_pool.start.assert_called_once()

    @pytest.mark.asyncio
    async def test_shutdown(self, engine, engine_config):
        """Test engine shutdown."""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock):
            with patch('scraper.engines.playwright_search.create_adaptive_pool') as mock_create_pool:
                mock_pool = AsyncMock()
                mock_pool.start = AsyncMock()
                mock_pool.stop = AsyncMock()
                mock_create_pool.return_value = mock_pool
                
                await engine.initialize(engine_config)
                await engine.shutdown()
                
                assert engine._initialized is False
                mock_pool.stop.assert_called_once()

    def test_health_check(self, engine):
        """Test health check."""
        assert engine.health_check() is False
        
        engine._browser = MagicMock()
        engine._browser.is_connected = MagicMock(return_value=True)
        assert engine.health_check() is True
        
        engine._browser.is_connected = MagicMock(return_value=False)
        assert engine.health_check() is False

    @pytest.mark.asyncio
    async def test_search_returns_empty_on_captcha(self, engine, engine_config):
        """Test search returns empty when CAPTCHA not solved."""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock):
            with patch('scraper.engines.playwright_search.create_adaptive_pool') as mock_create_pool:
                mock_pool = AsyncMock()
                mock_pool.start = AsyncMock()
                mock_pool.get_context = AsyncMock()
                mock_pool.return_context = AsyncMock()
                mock_pool.stop = AsyncMock()
                mock_create_pool.return_value = mock_pool
                
                mock_context = AsyncMock()
                mock_page = AsyncMock()
                mock_context.new_page = AsyncMock(return_value=mock_page)
                mock_pool.get_context.return_value = mock_context
                
                # Mock page.goto
                mock_page.goto = AsyncMock()
                
                # Mock stealth manager wait_for_captcha_solve to return False (CAPTCHA not solved)
                engine._stealth_manager = AsyncMock()
                engine._stealth_manager.wait_for_captcha_solve = AsyncMock(return_value=False)
                
                await engine.initialize(engine_config)
                
                results = await engine.search("test query", max_results=5)
                
                assert results == []
                mock_page.close.assert_called()
                mock_pool.return_context.assert_called()

    @pytest.mark.asyncio
    async def test_search_returns_results_on_success(self, engine, engine_config):
        """Test search returns results when CAPTCHA solved."""
        with patch.object(engine, '_launch_browser', new_callable=AsyncMock):
            with patch('scraper.engines.playwright_search.create_adaptive_pool') as mock_create_pool:
                mock_pool = AsyncMock()
                mock_pool.start = AsyncMock()
                mock_pool.get_context = AsyncMock()
                mock_pool.return_context = AsyncMock()
                mock_pool.stop = AsyncMock()
                mock_create_pool.return_value = mock_pool
                
                mock_context = AsyncMock()
                mock_page = AsyncMock()
                mock_context.new_page = AsyncMock(return_value=mock_page)
                mock_pool.get_context.return_value = mock_context
                
                mock_page.goto = AsyncMock()
                
                # Mock stealth manager wait_for_captcha_solve to return True (CAPTCHA solved)
                engine._stealth_manager = AsyncMock()
                engine._stealth_manager.wait_for_captcha_solve = AsyncMock(return_value=True)
                
                # Mock _extract_results to return test results
                test_results = [
                    SearchResult(url="https://example.com/1", title="Result 1", snippet="Snippet 1", position=1, source="duckduckgo", query="test"),
                    SearchResult(url="https://example.com/2", title="Result 2", snippet="Snippet 2", position=2, source="duckduckgo", query="test"),
                ]
                engine._extract_results = AsyncMock(return_value=test_results)
                
                await engine.initialize(engine_config)
                
                results = await engine.search("test query", max_results=5)
                
                assert len(results) == 2
                assert results[0].url == "https://example.com/1"
                assert results[1].url == "https://example.com/2"

    def test_search_result_dataclass(self):
        """Test SearchResult dataclass."""
        result = SearchResult(
            url="https://example.com",
            title="Test Title",
            snippet="Test snippet",
            position=1,
            source="duckduckgo",
            query="test query"
        )
        
        assert result.url == "https://example.com"
        assert result.title == "Test Title"
        assert result.snippet == "Test snippet"
        assert result.position == 1
        assert result.source == "duckduckgo"
        assert result.query == "test query"

    def test_config_defaults(self):
        """Test PlaywrightSearchConfig defaults."""
        config = PlaywrightSearchConfig()
        
        assert config.search_engine == "duckduckgo"
        assert config.headless is True
        assert config.stealth_mode is True
        assert config.max_pages_per_query == 2
        assert config.results_per_page == 10
        assert config.captcha_timeout == 10000
        assert config.request_timeout == 30.0


class TestSearchPipelineIntegration:
    """Integration tests for search pipeline."""

    @pytest.mark.asyncio
    async def test_pipeline_initialization(self):
        """Test search pipeline can be initialized."""
        from scraper.engines import EngineRegistry
        from scraper.engines.interfaces import EngineConfig
        
        engine_class = EngineRegistry._engines.get('search_pipeline')
        assert engine_class is not None
        
        engine = engine_class()
        config = EngineConfig(name='search_pipeline', config={'search_pipeline': {}})
        
        # Mock sub-engines initialization
        with patch.object(engine, '_query_expander', new_callable=AsyncMock) as mock_expander:
            with patch.object(engine, '_relevance_ranker', new_callable=AsyncMock) as mock_ranker:
                with patch('scraper.engines.playwright_search.PlaywrightSearchEngine') as mock_search:
                    mock_search_instance = AsyncMock()
                    mock_search_instance.initialize = AsyncMock()
                    mock_search.return_value = mock_search_instance
                    
                    mock_expander.initialize = AsyncMock()
                    mock_ranker.initialize = AsyncMock()
                    
                    await engine.initialize(config)
                    
                    mock_expander.initialize.assert_called_once()
                    mock_ranker.initialize.assert_called_once()
                    mock_search_instance.initialize.assert_called_once()