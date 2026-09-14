from __future__ import annotations

from typing import Any, AsyncIterator, Optional
from html.parser import HTMLParser
import asyncio
import time
import logging

import httpx

from .base_v2 import BaseEngineV2
from .interfaces import EngineConfig, EngineMetadata
from ..config.schemas import EngineType, EngineCapability
from ..engines.base import ScrapeRequest, ScrapeResponse
from ..utils.observability import get_logger

LOG = logging.getLogger(__name__)


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.title = ""
        self._in_title = False
        self.bits: list[str] = []

    def handle_starttag(self, tag, attrs):
        self._in_title = tag == "title"

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        data = " ".join(data.split())
        if data:
            self.bits.append(data)
            if self._in_title:
                self.title += data


def record_from_html(url: str, html: str, engine: str) -> dict[str, Any]:
    parser = _Text()
    parser.feed(html)
    return {"url": url, "title": parser.title, "text": " ".join(parser.bits), "engine": engine}


class ScrapyEngineV2(BaseEngineV2):
    """V2 version of ScrapyEngine - inherits from BaseEngineV2 with circuit breaker, rate limiter, retry."""
    
    metadata = EngineMetadata(
        name="scrapy",
        engine_type=EngineType.HTTP,
        capabilities={
            EngineCapability.LARGE_CRAWL,
            EngineCapability.PROXY_ROTATION,
            EngineCapability.SESSION_PERSISTENCE,
        },
        max_concurrent=16,
        avg_latency_ms=2000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        circuit_breaker_config: Optional[dict] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._client: Optional[httpx.AsyncClient] = None

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Handle both EngineConfig object and plain dict
        if isinstance(config, EngineConfig):
            engine_config = config.config.get("scrapy", {})
        else:
            engine_config = config.get("scrapy", {})
        
        limits = httpx.Limits(max_keepalive_connections=20, max_connections=100, keepalive_expiry=30.0)
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=30.0, pool=5.0)
        self._client = httpx.AsyncClient(limits=limits, timeout=timeout, follow_redirects=True, http2=True)
        LOG.info("ScrapyEngineV2 initialized")

    async def _shutdown_impl(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _health_check_impl(self) -> bool:
        return self._client is not None and not self._client.is_closed

    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        """Legacy-compatible scrape method accepting ScrapeRequest from base.py."""
        print(f"DEBUG scrapy scrape: _initialized={self._initialized}")
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        start_time = time.time()

        try:
            timeout = request.engine_options.get("timeout", 20)
            agent = request.engine_options.get("user_agent", "CompliantFreeFirstScraper/0.1")

            # Use rate limiter and circuit breaker from base class
            async with self.request_context(request.url):
                response = await self._client.get(
                    request.url,
                    timeout=timeout,
                    headers={"User-Agent": agent},
                )
                response.raise_for_status()

            record = record_from_html(str(response.url), response.text, self.metadata.name)

            latency_ms = int((time.time() - start_time) * 1000)

            res = ScrapeResponse(
                url=str(response.url),
                success=True,
                data=record,
                markdown=None,
                html=response.text,
                metadata={"title": record["title"], "status_code": response.status_code},
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )
            self.metrics.record_request(True, latency_ms)
            return res

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"ScrapyEngineV2 scrape failed for {request.url}: {e}")

            res = ScrapeResponse(
                url=request.url,
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine=self.metadata.name,
                error=str(e),
                latency_ms=latency_ms,
            )
            self.metrics.record_request(False, latency_ms, str(e))
            return res

    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        for url in urls:
            yield await self.scrape(ScrapeRequest(url=url, engine_options=config))