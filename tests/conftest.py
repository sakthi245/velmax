"""Pytest configuration with module reloading support."""

import pytest
import sys
from pathlib import Path


def pytest_configure(config):
    """Configure pytest with custom settings."""
    config.addinivalue_line(
        "markers", "integration: marks tests as integration tests"
    )
    config.addinivalue_line(
        "markers", "slow: marks tests as slow"
    )


@pytest.fixture(scope="session", autouse=True)
def clear_module_cache():
    """Clear module cache before test session."""
    import shutil
    root = Path(__file__).parent.parent
    
    # Clear __pycache__ directories
    for cache_dir in root.rglob('__pycache__'):
        try:
            import shutil
            shutil.rmtree(cache_dir)
        except Exception:
            pass
    
    # Remove .pyc files
    for pyc_file in root.rglob('*.pyc'):
        try:
            pyc_file.unlink()
        except Exception:
            pass
    
    yield
    
    # Cleanup after session
    for cache_dir in root.rglob('__pycache__'):
        try:
            import shutil
            shutil.rmtree(cache_dir)
        except Exception:
            pass


@pytest.fixture
def reload_scraper():
    """Fixture to reload scraper modules before test."""
    import sys
    import importlib
    
    # Modules to reload
    prefixes = ['scraper', 'scripts']
    
    def reload():
        # Find modules to reload
        to_reload = [
            name for name in sys.modules
            if any(name.startswith(p) for p in ['scraper', 'scripts'])
        ]
        
        # Sort by depth (parents first)
        to_reload.sort(key=lambda x: x.count('.'))
        
        for name in to_reload:
            try:
                importlib.reload(sys.modules[name])
            except Exception:
                pass
        
        # Clear and re-register engine registry after reload
        try:
            from scraper.engines.registry_v2 import EngineRegistryV2, register_default_engines
            # Aggressive cleanup
            EngineRegistryV2._registrations.clear()
            EngineRegistryV2._instances.clear()
            EngineRegistryV2._health_status.clear()
            EngineRegistryV2._last_health_check.clear()
            EngineRegistryV2._initialization_times.clear()
            EngineRegistryV2._error_counts.clear()
            register_default_engines()
        except Exception as e:
            print(f"Fixture cleanup error: {e}")
            pass
    
    reload()
    yield
    reload()


@pytest.fixture
def fresh_modules():
    """Fixture providing fresh module imports for each test."""
    import sys
    import importlib
    
    # Save original state
    original = {
        name: mod for name, mod in sys.modules.items()
        if any(name.startswith(p) for p in ['scraper', 'scripts'])
    }
    
    yield
    
    # Restore
    to_remove = [
        name for name in sys.modules
        if any(name.startswith(p) for p in ['scraper', 'scripts'])
        and name not in original
    ]
    for name in to_remove:
        del sys.modules[name]
    
    for name, mod in original.items():
        sys.modules[name] = mod


@pytest.fixture
def mock_firecrawl_env(monkeypatch):
    """Mock Firecrawl environment for testing without Docker."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("FIRECRAWL_API_KEY", "test-key")


# Test utilities
class TestData:
    """Common test data."""
    
    SAMPLE_URLS = [
        "https://httpbin.org/html",
        "https://httpbin.org/json",
        "https://example.com",
    ]
    
    SAMPLE_GOALS = [
        "Extract page title and content",
        "Find all links on the page",
        "Extract product prices",
    ]
    
    SAMPLE_EXTRACTION_SCHEMA = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "content": {"type": "string"},
            "links": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["title", "content"]
    }