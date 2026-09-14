from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

import httpx

from ..config.schemas import EngineType, EngineCapability
from .interfaces import EngineConfig, EngineMetadata
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class TinyFishSearchResult:
    """Search result from TinyFish."""
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0
    source: str = "tinyfish"
    site_name: str = ""
    query: str = ""


@dataclass
class TinyFishSearchConfig:
    """Configuration for TinyFish Search Engine (using official SDK)."""
    enabled: bool = True
    api_key: str = ""
    base_url: str = "https://api.search.tinyfish.ai"
    timeout: float = 30.0
    max_results_per_query: int = 10
    rate_limit_delay: float = 2.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    verify_ssl: bool = True
    default_location: str = "US"
    default_language: str = "en"
    default_purpose: str = ""
    default_domain_type: str = "web"
    include_domains: str = ""
    exclude_domains: str = ""
    recency_minutes: int = 0
    page: int = 0
    include_thumbnail: bool = False
    fetch: bool = False


class TinyFishSearchEngine:
    """TinyFish Search Engine - Uses official TinyFish Python SDK."""
    
    metadata = EngineMetadata(
        name="tinyfish",
        engine_type=EngineType.SEARCH,
        capabilities={
            EngineCapability.SEARCH,
            EngineCapability.REST_API,
        },
        max_concurrent=3,
        avg_latency_ms=2000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,
    )

    def __init__(self) -> None:
        self.config = TinyFishSearchConfig()
        self._client = None
        self._last_request_time = 0.0
        self._request_lock: Optional[asyncio.Lock] = None
        self._initialized = False

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize the TinyFish search engine with official SDK."""
        search_config = config.config.get("tinyfish_search", {})
        self.config = TinyFishSearchConfig(**search_config)
        
        if not self.config.api_key:
            raise ValueError("TinyFish API key is required. Set TINYFISH_API_KEY in config or environment.")
        
        # Import and initialize official TinyFish SDK
        try:
            from tinyfish import TinyFish
        except ImportError:
            raise ImportError("tinyfish package not installed. Install with: pip install tinyfish")
        
        self._client = TinyFish(api_key=self.config.api_key)
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._initialized = True
        LOG.info("TinyFish Search Engine initialized with official SDK")

    async def shutdown(self) -> None:
        """Shutdown the search engine."""
        # TinyFish client doesn't need explicit cleanup
        self._initialized = False

    def health_check(self) -> bool:
        return self._initialized

    async def _rate_limit(self) -> None:
        """Enforce rate limiting (30 requests/minute = 2 seconds between requests)."""
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()

    def _build_search_params(
        self,
        query: str,
        location: Optional[str] = None,
        language: Optional[str] = None,
        purpose: Optional[str] = None,
        include_domains: Optional[str] = None,
        exclude_domains: Optional[str] = None,
        domain_type: Optional[str] = None,
        recency_minutes: Optional[int] = None,
        page: Optional[int] = None,
        include_thumbnail: Optional[bool] = None,
        fetch: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Build search parameters for TinyFish API."""
        params = {"query": query}
        
        if location:
            params["location"] = location
        if language:
            params["language"] = language
        if purpose:
            params["purpose"] = purpose
        if include_domains:
            params["include_domains"] = include_domains
        if exclude_domains:
            params["exclude_domains"] = exclude_domains
        if domain_type:
            params["domain_type"] = domain_type
        if recency_minutes is not None:
            params["recency_minutes"] = str(recency_minutes)
        if page is not None:
            params["page"] = str(page)
        if include_thumbnail is not None:
            params["include_thumbnail"] = str(include_thumbnail).lower()
        if fetch is not None:
            params["fetch"] = str(fetch).lower()
        
        # Use config defaults if not provided
        if "location" not in params and self.config.default_location:
            params["location"] = self.config.default_location
        if "language" not in params and self.config.default_language:
            params["language"] = self.config.default_language
        if "purpose" not in params and self.config.default_purpose:
            params["purpose"] = self.config.default_purpose
        if "domain_type" not in params and self.config.default_domain_type:
            params["domain_type"] = self.config.default_domain_type
        if "include_domains" not in params and self.config.include_domains:
            params["include_domains"] = self.config.include_domains
        if "exclude_domains" not in params and self.config.exclude_domains:
            params["exclude_domains"] = self.config.exclude_domains
        if "recency_minutes" not in params and self.config.recency_minutes:
            params["recency_minutes"] = str(self.config.recency_minutes)
        if "page" not in params and self.config.page:
            params["page"] = str(self.config.page)
        if "include_thumbnail" not in params and self.config.include_thumbnail:
            params["include_thumbnail"] = str(self.config.include_thumbnail).lower()
        if "fetch" not in params and self.config.fetch:
            params["fetch"] = str(self.config.fetch).lower()
        
        return params

    def _parse_results(self, data: Any, query: str) -> List[Any]:
        """Parse TinyFish API response into SearchResult objects."""
        from .tinyfish import TinyFishSearchResult
        results = []
        
        # Handle both dict and Pydantic model responses
        if hasattr(data, 'model_dump'):
            data = data.model_dump()
        elif hasattr(data, 'dict'):
            data = data.dict()
        
        results_data = data.get("results", [])
        
        for item in results_data:
            try:
                result = TinyFishSearchResult(
                    url=item.get("url", ""),
                    title=item.get("title", ""),
                    snippet=item.get("snippet", ""),
                    position=item.get("position", 0),
                    source="tinyfish",
                    site_name=item.get("site_name", ""),
                    query=query,
                )
                if result.url:
                    results.append(result)
            except Exception as e:
                LOG.warning(f"Failed to parse TinyFish result: {e}")
                continue
        
        return results

    async def search(
        self,
        query: str,
        max_results: int = 10,
        location: Optional[str] = None,
        language: Optional[str] = None,
        purpose: Optional[str] = None,
        include_domains: Optional[str] = None,
        exclude_domains: Optional[str] = None,
        domain_type: Optional[str] = None,
        recency_minutes: Optional[int] = None,
        page: Optional[int] = None,
        include_thumbnail: Optional[bool] = None,
        fetch: Optional[bool] = None,
    ) -> List[Any]:
        """Search TinyFish and return results using official SDK."""
        if not self._initialized:
            raise RuntimeError("TinyFish Search Engine not initialized")

        await self._rate_limit()

        params = self._build_search_params(
            query=query,
            location=location,
            language=language,
            purpose=purpose,
            include_domains=include_domains,
            exclude_domains=exclude_domains,
            domain_type=domain_type,
            recency_minutes=recency_minutes,
            page=page,
            include_thumbnail=include_thumbnail,
            fetch=fetch,
        )

        for attempt in range(self.config.max_retries + 1):
            try:
                await self._rate_limit()
                
                # Use official TinyFish SDK
                response = self._client.search.query(
                    query=query,
                    location=params.get("location"),
                    language=params.get("language"),
                    purpose=params.get("purpose"),
                    include_domains=params.get("include_domains"),
                    exclude_domains=params.get("exclude_domains"),
                    domain_type=params.get("domain_type"),
                    recency_minutes=params.get("recency_minutes"),
                    page=params.get("page"),
                )
                results = self._parse_results(response, query)
                return results[:max_results]

            except Exception as e:
                LOG.warning(f"TinyFish search error (attempt {attempt + 1}): {e}")
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
    ) -> Dict[str, List[Any]]:
        """Search multiple queries."""
        results = {}
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(delay_between_queries)
            try:
                results[query] = await self.search(query, max_results_per_query)
            except Exception as e:
                LOG.error(f"Failed to search for '{query}': {e}")
                results[query] = []
        return results

    async def _rate_limit(self) -> None:
        """Enforce rate limiting (30 requests/minute = 2 seconds between requests)."""
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()