import pytest
import asyncio
from scraper.config import ScraperConfig
from scraper.engines.base_v2 import CircuitBreaker
from scraper.strategy import FallbackStrategyRouter
from scraper.engines import EngineRegistry


@pytest.mark.asyncio
async def test_circuit_breaker_opens_after_failures():
    cb = CircuitBreaker(failure_threshold=3, recovery_timeout=60)
    
    assert cb.get_state() == "closed"
    
    async def fail():
        raise RuntimeError("fail")
    
    for _ in range(3):
        with pytest.raises(RuntimeError):
            await cb.call(fail)
    
    assert cb.get_state() == "open"
    
    with pytest.raises(RuntimeError, match="Circuit breaker OPEN"):
        await cb.call(lambda: "success")


@pytest.mark.asyncio
async def test_circuit_breaker_half_open():
    cb = CircuitBreaker(failure_threshold=2, recovery_timeout=0.01)
    
    async def fail():
        raise RuntimeError("fail")
    
    with pytest.raises(RuntimeError):
        await cb.call(fail)
    with pytest.raises(RuntimeError):
        await cb.call(fail)
    assert cb.get_state() == "open"
    
    # Wait for recovery
    await asyncio.sleep(0.02)
    
    # Should allow one call in half-open (this succeeds)
    async def success():
        return "success"
    result = await cb.call(success)
    assert result == "success"
    # After successful call in half-open, state goes to CLOSED
    assert cb.get_state() == "closed"


@pytest.mark.asyncio
async def test_router_initialization():
    config = ScraperConfig()
    router = FallbackStrategyRouter(config)
    await router.initialize()
    
    assert router._initialized
    assert "scrapy" in EngineRegistry._engines
    assert "playwright" in EngineRegistry._engines