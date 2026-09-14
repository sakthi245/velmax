from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional, AsyncIterator

from ..config.schemas import EngineType, EngineCapability

__all__ = ["EngineType", "EngineCapability", "EngineMetadata", "ScrapeRequest", "ScrapeResponse", "BaseEngine", "ScrapingEngine"]

@dataclass
class EngineMetadata:
    name: str
    type: EngineType
    capabilities: list[EngineCapability] = field(default_factory=list)
    max_concurrent: int = 5
    avg_latency_ms: int = 5000
    requires_external_service: bool = False
    cost_per_1k_pages: float = 0.0

@dataclass
class ScrapeRequest:
    url: str
    goal: str = ""
    schema: Optional[dict] = None
    engine_options: dict = field(default_factory=dict)
    priority: int = 0

@dataclass
class ScrapeResponse:
    url: str
    success: bool
    data: dict = field(default_factory=dict)
    markdown: Optional[str] = None
    html: Optional[str] = None
    metadata: dict = field(default_factory=dict)
    engine: str = ""
    error: Optional[str] = None
    latency_ms: int = 0

    def to_legacy_format(self) -> list[dict[str, Any]]:
        if self.success:
            return [{
                "url": self.url,
                "text": self.markdown or self.html or "",
                "title": self.metadata.get("title", ""),
                "engine": self.engine,
            }]
        return []

class BaseEngine(ABC):
    metadata: EngineMetadata
    
    @abstractmethod
    async def initialize(self, config: dict) -> None: ...
    
    @abstractmethod
    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse: ...
    
    @abstractmethod
    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]: ...
    
    @abstractmethod
    async def shutdown(self) -> None: ...
    
    @abstractmethod
    def health_check(self) -> bool: ...
    
    def supports(self, capability: EngineCapability) -> bool:
        return capability in self.metadata.capabilities
    
    def _record_metrics(self, engine_name: str, success: bool, latency_ms: int):
        try:
            from scraper.metrics import record_scrape
            record_scrape(engine_name, success, latency_ms)
        except ImportError:
            pass


# Legacy interface for backward compatibility
class ScrapingEngine(ABC):
    """Legacy sync interface - use BaseEngine for new code"""
    name = "base"
    
    @abstractmethod
    def is_available(self) -> bool: ...
    
    @abstractmethod
    def scrape(self, url: str, goal: str, schema: dict[str, Any], **kwargs: Any): ...
    
    def is_limit_reached(self) -> bool: return False
    
    def scrape_legacy(self, url: str, goal: str, schema: dict[str, Any], **kwargs: Any):
        """Sync wrapper for async scrape"""
        import asyncio
        from .base import ScrapeRequest
        request = ScrapeRequest(url=url, goal=goal, schema=schema, engine_options=kwargs)
        response = asyncio.run(self.scrape(request))
        return response.to_legacy_format()