from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import serpapi

from ..config.schemas import EngineType, EngineCapability
from .interfaces import EngineConfig, EngineMetadata
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class SerpAPISearchResult:
    """Search result from SerpAPI."""
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0
    source: str = "serpapi"
    site_name: str = ""
    query: str = ""


@dataclass
class SerpAPISearchConfig:
    """Configuration for SerpAPI Search Engine (using official SDK)."""
    enabled: bool = False
    api_key: str = ""
    base_url: str = "https://serpapi.com/search"
    timeout: float = 30.0
    max_results_per_query: int = 10
    rate_limit_delay: float = 1.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    verify_ssl: bool = True
    engine: str = "google"
    location: str = "United States"
    language: str = "en"
    gl: str = "us"
    hl: str = "en"
    google_domain: str = "google.com"
    safe_search: bool = True
    num_results: int = 10
    device: str = "desktop"


class SerpAPISearchEngine:
    """SerpAPI Search Engine - Uses official SerpAPI Python SDK."""
    
    metadata = EngineMetadata(
        name="serpapi",
        engine_type=EngineType.SEARCH,
        capabilities={
            EngineCapability.SEARCH,
            EngineCapability.REST_API,
        },
        max_concurrent=3,
        avg_latency_ms=3000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,
    )

    def __init__(self) -> None:
        self.config = SerpAPISearchConfig()
        self._client = None
        self._last_request_time = 0.0
        self._request_lock: Optional[asyncio.Lock] = None
        self._initialized = False

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize the SerpAPI search engine with official SDK."""
        search_config = config.config.get("serpapi_search", {})
        self.config = SerpAPISearchConfig(**search_config)
        
        # Fallback: config -> env var
        api_key = self.config.api_key or os.environ.get("SERPAPI_API_KEY")
        if not api_key:
            raise ValueError("SerpAPI API key is required. Set in config or SERPAPI_API_KEY env var.")
        
        # Initialize official SerpAPI SDK
        self._client = serpapi.Client(api_key=api_key)
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._initialized = True
        LOG.info("SerpAPI Search Engine initialized with official SDK")

    async def shutdown(self) -> None:
        """Shutdown the search engine."""
        # SerpAPI client doesn't need explicit cleanup
        self._initialized = False

    def health_check(self) -> bool:
        return self._initialized

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()

    def _build_search_params(self, query: str, **kwargs) -> Dict[str, str]:
        """Build search parameters for SerpAPI."""
        params = {
            "engine": self.config.engine,
            "q": query,
            "location": kwargs.get("location", self.config.location),
            "hl": kwargs.get("language", self.config.language),
            "gl": self.config.gl,
            "google_domain": self.config.google_domain,
            "safe_search": "true" if self.config.safe_search else "false",
            "num": str(self.config.num_results),
            "device": self.config.device,
        }
        
        # Add optional parameters
        if self.config.location:
            params["location"] = self.config.location
        if self.config.language:
            params["hl"] = self.config.language
        if self.config.gl:
            params["gl"] = self.config.gl
        if self.config.hl:
            params["hl"] = self.config.hl
        if self.config.google_domain:
            params["google_domain"] = self.config.google_domain
        if self.config.safe_search:
            params["safe_search"] = "true" if self.config.safe_search else "false"
        if self.config.num_results:
            params["num"] = str(self.config.num_results)
        if self.config.device:
            params["device"] = self.config.device
            
        return params

    def _parse_results(self, data: Dict[str, Any], query: str) -> List[SerpAPISearchResult]:
        """Parse SerpAPI response into SearchResult objects."""
        results = []
        organic_results = data.get("organic_results", [])
        
        for item in organic_results:
            try:
                result = SerpAPISearchResult(
                    url=item.get("link", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    position=item.get("position", 0),
                    source="serpapi",
                    site_name=item.get("source", ""),
                    query=query,
                )
                if result.url:
                    results.append(result)
            except Exception as e:
                LOG.warning(f"Failed to parse SerpAPI result: {e}")
                continue
        
        return results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        **kwargs,
    ) -> List[SerpAPISearchResult]:
        """Search SerpAPI and return results using official SDK."""
        if not self._initialized:
            raise RuntimeError("SerpAPI Search Engine not initialized")

        await self._rate_limit()

        params = self._build_search_params(query, **kwargs)

        for attempt in range(self.config.max_retries + 1):
            try:
                await self._rate_limit()
                
                # Use official SerpAPI SDK
                results = self._client.search(params)
                
                data = results
                results_list = self._parse_results(data, query)
                return results_list[:max_results]

            except Exception as e:
                LOG.warning(f"SerpAPI search error (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.backoff_factor ** attempt)
                    continue
                raise

        return []

    async def search_multiple(
        self,
        queries: List[str],
        max_results_per_query: int = 10,
        delay_between_queries: float = 1.0,
        **kwargs,
    ) -> Dict[str, List[SerpAPISearchResult]]:
        """Search multiple queries."""
        results = {}
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(delay_between_queries)
            try:
                results[query] = await self.search(query, max_results=max_results_per_query)
            except Exception as e:
                LOG.error(f"Failed to search for '{query}': {e}")
                results[query] = []
        return results

    async def _rate_limit(self) -> None:
        """Enforce rate limiting."""
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()