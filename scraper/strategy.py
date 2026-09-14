from __future__ import annotations
import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, List
from .config import load_config
from .config.schemas import UniversalConfig
from .engines import EngineRegistry, EngineSelector
from .engines.base import ScrapeRequest
from .engines.base_v2 import CircuitBreaker
from .models import ScrapeResult
from .utils.errors import AllEnginesFailedError, RobotsDeniedError
from .utils.robots import allowed
from .metrics import set_circuit_state, set_engine_health

LOG = logging.getLogger(__name__)

class CircuitState(Enum):
    CLOSED = 0
    HALF_OPEN = 1
    OPEN = 2

# Map legacy engine names to UniversalConfig engine fields
# Only include legacy engines that have concrete V2 implementations
ENGINE_CONFIG_MAP = {
    "scrapy": "http_engine",
    "playwright": "browser_engine",
    "crawlee": "managed_engine",
    "firecrawl": "cloud_engine",
}

def get_engine_config(config: UniversalConfig, engine_name: str) -> dict:
    """Get engine config from UniversalConfig, mapping legacy names to config fields."""
    field_name = ENGINE_CONFIG_MAP.get(engine_name)
    if field_name is None:
        return {}
    engine_config_obj = getattr(config, field_name, None)
    if engine_config_obj is None:
        return {}
    # Convert Pydantic model to dict
    return engine_config_obj.model_dump() if hasattr(engine_config_obj, 'model_dump') else {}

class FallbackStrategyRouter:
    def __init__(self, config: UniversalConfig):
        self.config = config
        self.registry = EngineRegistry()
        self.selector = EngineSelector(self.registry, config.to_dict())
        self.circuit_breakers: dict[str, CircuitBreaker] = {}
        self._initialized = False
    
    async def initialize(self) -> None:
        if self._initialized:
            return
        
        # Initialize all available engines from UniversalConfig
        for legacy_name, config_field in ENGINE_CONFIG_MAP.items():
            engine_config = get_engine_config(self.config, legacy_name)
            if engine_config.get("enabled", True):
                try:
                    await self.registry.get(legacy_name, engine_config)
                    self.circuit_breakers[legacy_name] = CircuitBreaker(
                        failure_threshold=engine_config.get("failure_threshold", 5),
                        recovery_timeout=engine_config.get("recovery_timeout", 60),
                    )
                    set_engine_health(legacy_name, True)
                    LOG.info("Initialized engine: %s", legacy_name)
                except Exception as e:
                    LOG.warning("Failed to initialize %s: %s", legacy_name, e)
                    set_engine_health(legacy_name, False)
        
        self._initialized = True
    
    async def scrape(self, url: str, goal: str, schema: dict | None = None, *, engine: str | None = None, resume_session_id: str | None = None) -> ScrapeResult:
        if not self._initialized:
            await self.initialize()
        
        robots_config = self.config.robots
        if robots_config.respect and not allowed(url, robots_config.user_agent):
            raise RobotsDeniedError(f"robots.txt disallows {url}")
        
        request = ScrapeRequest(
            url=url,
            goal=goal,
            schema=schema,
            engine_options={"engine": engine, "resume_session_id": resume_session_id} if engine or resume_session_id else {}
        )
        
        primary = self.selector.select(request) if not engine else engine
        fallback_chain = self._build_fallback_chain(primary)
        all_engines = [primary] + fallback_chain
        
        attempts: list[dict[str, Any]] = []
        limits_hit: list[str] = []
        
        for eng_name in all_engines:
            breaker = self.circuit_breakers.get(eng_name)
            
            try:
                engine_config = get_engine_config(self.config, eng_name)
                eng = await self.registry.get(eng_name, engine_config)
                
                if not eng.health_check():
                    raise RuntimeError(f"{eng_name} health check failed")
                
                if breaker:
                    set_circuit_state(eng_name, {"closed": 0, "half_open": 1, "open": 2}.get(breaker.get_state(), 0))
                    response = await breaker.call(eng.scrape, request)
                else:
                    set_circuit_state(eng_name, 0)
                    response = await eng.scrape(request)
                
                attempts.append({
                    "engine": eng_name,
                    "outcome": "success" if response.success else f"failed: {response.error}",
                    "latency_ms": response.latency_ms,
                })
                
                if response.success:
                    items = response.to_legacy_format()
                    return ScrapeResult(
                        items=items,
                        engine=eng_name,
                        attempts=attempts,
                        limits_hit=limits_hit,
                    )
                
                if response.metadata.get("status_code") in (429, 402):
                    limits_hit.append(eng_name)
                
            except Exception as e:
                attempts.append({"engine": eng_name, "outcome": f"error: {e}", "latency_ms": 0})
                LOG.warning("%s failed for %s: %s", eng_name, url, e)
                continue
        
        detail = "; ".join(f"{a['engine']}={a['outcome']}" for a in attempts)
        raise AllEnginesFailedError(f"No eligible engine could scrape {url}. {detail}")
    
    def _build_fallback_chain(self, primary: str) -> List[str]:
        fallback_map = {
            "firecrawl": ["crawlee", "playwright"],
            "crawlee": ["firecrawl", "playwright"],
            "playwright": ["crawlee", "firecrawl"],
            "scrapy": ["crawlee", "firecrawl"],
        }
        return [e for e in fallback_map.get(primary, ["crawlee", "firecrawl"]) if e in self.registry._engines]
    
    async def shutdown(self) -> None:
        await self.registry.shutdown_all()
        self._initialized = False