"""Integration tests for automatic Firecrawl integration."""

import pytest
import asyncio
from unittest.mock import AsyncMock, Mock, patch, MagicMock
from pathlib import Path

from scraper.universal_runner import UniversalRunner, QuickProfiler, SmartEngineSelector, FallbackChain
from scraper.orchestrator import HybridOrchestrator
from scraper.config.schemas import UniversalConfig, UniversalRequest, UniversalResult, SiteProfile, EngineType, OutputFormat
from scraper.config.loader import get_low_memory_config
from custom_scripts.universal_scraper import UniversalScraper, DockerFirecrawlManager, ScrapeTask


class TestAutoFirecrawlIntegration:
    """Tests for automatic Firecrawl integration."""

    @pytest.fixture
    def low_memory_config(self):
        """Low memory config for testing."""
        return get_low_memory_config()

    @pytest.fixture
    def universal_runner(self, low_memory_config):
        """Create UniversalRunner with low memory config."""
        return UniversalRunner(low_memory_config)

    @pytest.fixture
    def universal_scraper(self):
        """Create UniversalScraper for testing."""
        return UniversalScraper(use_docker_firecrawl=True, auto_firecrawl=True)

    @pytest.mark.asyncio
    async def test_engine_selector_boosts_firecrawl_for_anti_bot(self, universal_runner):
        """Test that Firecrawl gets boosted for high anti-bot sites."""
        selector = SmartEngineSelector(universal_runner.config)
        
        # Create a profile with high anti-bot
        profile = SiteProfile(
            url="https://example.com",
            category="ecommerce",
            anti_bot_level="high",
            requires_js=False,
            js_framework=None,
        )
        
        request = UniversalRequest(
            url="https://example.com",
            goal="Extract product data",
        )
        
        # Set request on selector for scoring
        selector._current_request = request
        
        scored = selector._score_engines(profile)
        
        # Firecrawl should be ranked highest for high anti-bot
        assert scored[0][1].value == "cloud", f"Expected cloud first, got {scored[0][1].value}"
        assert scored[0][0] > scored[1][0], "Firecrawl should have highest score"

    @pytest.mark.asyncio
    async def test_engine_selector_boosts_firecrawl_for_pdf(self, universal_runner):
        """Test that Firecrawl gets boosted for PDF extraction."""
        selector = SmartEngineSelector(universal_runner.config)
        
        profile = SiteProfile(
            url="https://example.com/document.pdf",
            category="document",
            anti_bot_level="none",
        )
        
        request = UniversalRequest(
            url="https://example.com/document.pdf",
            goal="Extract PDF content",
            pdf=True,
        )
        
        selector._current_request = request
        scored = selector._score_engines(profile)
        
        # Firecrawl should be ranked highest for PDF
        assert scored[0][1].value == "cloud"

    @pytest.mark.asyncio
    async def test_engine_selector_boosts_firecrawl_for_screenshot(self, universal_runner):
        """Test that Firecrawl gets boosted for screenshot capture."""
        selector = SmartEngineSelector(universal_runner.config)
        
        profile = SiteProfile(
            url="https://example.com",
            category="web",
            anti_bot_level="none",
        )
        
        request = UniversalRequest(
            url="https://example.com",
            goal="Capture screenshot",
            screenshot=True,
        )
        
        selector._current_request = request
        scored = selector._score_engines(profile)
        
        assert scored[0][1].value == "cloud"

    @pytest.mark.asyncio
    async def test_engine_selector_boosts_firecrawl_for_llm_extraction(self, universal_runner):
        """Test that Firecrawl gets boosted for LLM extraction."""
        selector = SmartEngineSelector(universal_runner.config)
        
        profile = SiteProfile(
            url="https://example.com",
            category="web",
            anti_bot_level="none",
        )
        
        request = UniversalRequest(
            url="https://example.com",
            goal="Extract structured data",
            extract_schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        
        selector._current_request = request
        scored = selector._score_engines(profile)
        
        assert scored[0][1].value == "cloud"

    @pytest.mark.asyncio
    async def test_fallback_chain_prioritizes_firecrawl_for_anti_bot(self, universal_runner):
        """Test that fallback chain prioritizes Firecrawl for high anti-bot sites."""
        fallback_chain = FallbackChain(universal_runner.config)
        
        profile = SiteProfile(
            url="https://example.com",
            category="ecommerce",
            anti_bot_level="high",
        )
        
        # Primary engine is HTTP, but anti-bot should put Firecrawl first
        chain = fallback_chain._build_chain(EngineType.HTTP, profile)
        
        assert chain[0] == EngineType.CLOUD, "Firecrawl should be first for high anti-bot"
        
        # For low anti-bot, normal chain
        profile_low = SiteProfile(
            url="https://example.com",
            category="blog",
            anti_bot_level="none",
        )
        chain_low = fallback_chain._build_chain(EngineType.HTTP, profile_low)
        
        # HTTP should be first for normal sites
        assert chain_low[0] == EngineType.HTTP

    @pytest.mark.asyncio
    async def test_docker_firecrawl_manager_ensure_running(self):
        """Test DockerFirecrawlManager ensure_running method."""
        with patch('subprocess.run') as mock_run:
            # Mock is_running to return True on second call
            mock_run.side_effect = [
                Mock(returncode=0, stdout='[]'),  # is_running first call - not running
                Mock(returncode=0),  # docker compose up
                Mock(returncode=0, stdout='[{"Service": "firecrawl-api", "Health": "healthy"}]'),  # is_running second call - running
            ]
            
            manager = DockerFirecrawlManager()
            manager.compose_file = Path("/fake/path")
            manager.env_file = Path("/fake/env")
            
            with patch.object(manager, 'is_running', side_effect=[False, True]):
                with patch.object(manager, 'start', return_value=True) as mock_start:
                    result = manager.ensure_running()
                    assert result is True
                    mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_universal_runner_auto_starts_firecrawl(self, universal_runner):
        """Test that UniversalRunner auto-starts Firecrawl when cloud engine selected."""
        # Clear dedup cache to ensure test runs
        universal_runner._dedup.clear()
        
        with patch.object(universal_runner, '_ensure_firecrawl_ready', return_value=True) as mock_ensure:
            with patch.object(universal_runner.selector, 'select', return_value=(EngineType.CLOUD, {})):
                with patch.object(universal_runner.fallback_chain, 'execute') as mock_execute:
                    mock_execute.return_value = UniversalResult(
                        success=True,
                        url="https://example.com/test-firecrawl-auto",
                        data={"test": "data"},
                        engine_used="cloud",
                    )
                    
                    request = UniversalRequest(
                        url="https://example.com/test-firecrawl-auto",
                        goal="Test",
                    )
                    
                    result = await universal_runner.scrape(request)
                    
                    mock_ensure.assert_called_once()
                    assert result.engine_used == "cloud"

    @pytest.mark.asyncio
    async def test_universal_scraper_auto_ensures_firecrawl(self, universal_scraper):
        """Test that UniversalScraper auto-ensures Firecrawl when firecrawl engine selected."""
        with patch.object(universal_scraper.docker_manager, 'ensure_running', return_value=True) as mock_ensure:
            with patch.object(universal_scraper, '_scrape_firecrawl', return_value=({"success": True, "data": {}}, [])):
                task = ScrapeTask(
                    query="Test",
                    urls=["https://example.com"],
                    goal="Test",
                    engines=["firecrawl"],
                )
                
                result = await universal_scraper.scrape_with_fallback(task)
                
                mock_ensure.assert_called_once()
                assert result.engine_used == "firecrawl"

    @pytest.mark.asyncio
    async def test_universal_scraper_determines_engines_auto(self, universal_scraper):
        """Test that UniversalScraper automatically determines engines including Firecrawl."""
        # Test anti-bot detection
        task_antibot = ScrapeTask(
            query="Scrape e-commerce",
            urls=["https://amazon.com/product"],
            goal="Extract product data from Cloudflare protected site",
        )
        
        engines = universal_scraper.determine_engines_for_task(task_antibot)
        assert "firecrawl" in engines
        assert engines[0] == "firecrawl", "Firecrawl should be first for anti-bot"
        
        # Test PDF detection
        task_pdf = ScrapeTask(
            query="Extract PDF",
            urls=["https://example.com/doc.pdf"],
            goal="Extract PDF content",
        )
        
        engines_pdf = universal_scraper.determine_engines_for_task(task_pdf)
        assert "firecrawl" in engines_pdf
        
        # Test screenshot detection
        task_screenshot = ScrapeTask(
            query="Screenshot",
            urls=["https://example.com"],
            goal="Capture screenshot",
        )
        task_screenshot.screenshot = True
        
        engines_screenshot = universal_scraper.determine_engines_for_task(task_screenshot)
        assert "firecrawl" in engines_screenshot
        
        # Test LLM extraction
        task_llm = ScrapeTask(
            query="LLM extract",
            urls=["https://example.com"],
            goal="Extract structured data",
            schema={"type": "object", "properties": {"name": {"type": "string"}}},
        )
        
        engines_llm = universal_scraper.determine_engines_for_task(task_llm)
        assert "firecrawl" in engines_llm

    @pytest.mark.asyncio
    async def test_docker_manager_auto_stop_after_idle(self):
        """Test that Docker manager can be configured to stop after idle."""
        manager = DockerFirecrawlManager()
        
        # Test that auto_stop_idle_min config exists
        from scraper.config.schemas import CloudEngineConfig
        config = CloudEngineConfig()
        assert hasattr(config, 'auto_stop_idle_min')
        assert config.auto_stop_idle_min == 30


if __name__ == "__main__":
    pytest.main([__file__, "-v"])