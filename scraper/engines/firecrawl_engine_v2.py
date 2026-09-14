from __future__ import annotations

from typing import Any, AsyncIterator, Optional
import asyncio
import time
import logging

from .base_v2 import BaseEngineV2
from .interfaces import EngineConfig, EngineMetadata
from ..config.schemas import EngineType, EngineCapability
from ..engines.base import ScrapeRequest, ScrapeResponse
from ..utils.observability import get_logger

LOG = logging.getLogger(__name__)


class FirecrawlEngineV2(BaseEngineV2):
    """V2 version of FirecrawlEngine - inherits from BaseEngineV2 with circuit breaker, rate limiter, retry."""
    
    metadata = EngineMetadata(
        name="firecrawl",
        engine_type=EngineType.CLOUD,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.LLM_EXTRACTION,
            EngineCapability.LARGE_CRAWL,
            EngineCapability.PDF_PARSING,
            EngineCapability.ANTI_BOT,
            EngineCapability.PROXY_ROTATION,
        },
        max_concurrent=10,
        avg_latency_ms=15000,
        requires_external_service=True,
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
        self.client = None
        self.config = {}

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Handle both EngineConfig object and plain dict
        if isinstance(config, EngineConfig):
            self.config = config.config.get("firecrawl", {})
        else:
            self.config = config.get("firecrawl", {})

        try:
            from firecrawl import FirecrawlApp
        except ImportError:
            raise RuntimeError("firecrawl-py not installed. Install with: pip install firecrawl-py")

        api_url = self.config.get("api_url", "http://localhost:3002")
        api_key = self.config.get("api_key", "local-dev")

        self.client = FirecrawlApp(api_key=api_key, api_url=api_url)

        # Verify connection
        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(None, lambda: self.client.scrape("https://example.com"))
        except Exception as e:
            LOG.warning(f"Firecrawl health check failed, but continuing: {e}")

        self._initialized = True
        LOG.info(f"FirecrawlEngineV2 initialized: {api_url}")

    async def _shutdown_impl(self) -> None:
        self.client = None
        self._initialized = False

    def _health_check_impl(self) -> bool:
        if not self._initialized or not self.client:
            return False
        try:
            self.client.scrape("https://example.com")
            return True
        except Exception as e:
            LOG.warning(f"Firecrawl health check failed: {e}")
            return False

    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        """Legacy-compatible scrape method."""
        if not self._initialized:
            raise RuntimeError("FirecrawlEngineV2 not initialized")

        start_time = time.time()
        opts = request.engine_options or {}

        try:
            scrape_opts = {
                "formats": opts.get("formats", ["markdown", "html"]),
                "only_main_content": opts.get("only_main_content", True),
                "proxy": opts.get("proxy", "auto"),
                "timeout": opts.get("timeout", 120000),
            }

            if opts.get("actions"):
                scrape_opts["actions"] = opts["actions"]
            if opts.get("prompt"):
                scrape_opts["prompt"] = opts["prompt"]

            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                lambda: self.client.scrape(request.url, **scrape_opts)
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if hasattr(result, "model_dump"):
                data = result.model_dump()
                metadata = result.metadata.model_dump() if hasattr(result.metadata, "model_dump") else dict(result.metadata)
                markdown = getattr(result, "markdown", None)
                html = getattr(result, "html", None)
            else:
                data = dict(result) if result else {}
                metadata = data.get("metadata", {})
                markdown = data.get("markdown")
                html = data.get("html")

            response = ScrapeResponse(
                url=metadata.get("sourceURL", request.url),
                success=True,
                data=data,
                markdown=markdown,
                html=html,
                metadata=metadata,
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )

            self.metrics.record_request(True, latency_ms)
            return response

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"FirecrawlEngineV2 scrape failed for {request.url}: {e}")

            response = ScrapeResponse(
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
            return response

    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        if not self._initialized:
            raise RuntimeError("FirecrawlEngineV2 not initialized")

        opts = config.get("crawl_options", {})
        loop = asyncio.get_event_loop()

        try:
            crawl_result = await loop.run_in_executor(
                None,
                lambda: self.client.crawl(
                    urls[0] if urls else "",
                    limit=opts.get("limit", 1000),
                    max_depth=opts.get("max_depth", 3),
                    scrape_options=opts.get("scrape_options", {}),
                )
            )

            if hasattr(crawl_result, "status") and crawl_result.status == "scraping":
                job_id = crawl_result.id
                while True:
                    await asyncio.sleep(5)
                    status = await loop.run_in_executor(
                        None,
                        lambda: self.client.crawl_status(job_id)
                    )
                    if status.status == "completed":
                        crawl_result = status
                        break
                    elif status.status == "failed":
                        raise RuntimeError(f"Crawl failed: {status.error}")

            pages = getattr(crawl_result, "data", []) or getattr(crawl_result, "pages", [])
            for page in pages:
                yield ScrapeResponse(
                    url=page.get("metadata", {}).get("sourceURL", ""),
                    success=True,
                    data=page,
                    markdown=page.get("markdown"),
                    html=page.get("html"),
                    metadata=page.get("metadata", {}),
                    engine=self.metadata.name,
                )

        except Exception as e:
            LOG.warning(f"FirecrawlEngineV2 crawl failed: {e}")
            yield ScrapeResponse(
                url=urls[0] if urls else "",
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine=self.metadata.name,
                error=str(e),
            )

    async def _crawl_impl(self, strategy) -> AsyncIterator[Any]:
        pass  # Not used in legacy interface