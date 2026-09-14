from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
import httpx

from .base_v2 import BaseCloudEngineV2
from .interfaces import (
    EngineConfig,
    EngineMetadata,
    BrowserRequest,
    BrowserResponse,
)
from ..utils.observability import get_logger, MetricsCollector
from ..utils.retry import RetryPolicy, create_retry_policy
from ..config.schemas import CloudEngineConfig as CloudEngineConfigSchema, EngineType, EngineCapability


@dataclass
class CloudEngineConfig:
    enabled: bool = True
    api_url: str = "http://localhost:3002"
    api_key: str = "local-dev"
    formats: List[str] = field(default_factory=lambda: ["markdown", "html"])
    only_main_content: bool = True
    proxy: str = "auto"
    timeout: int = 120000
    wait_for_selector: Optional[str] = None
    wait_for_timeout: int = 5000
    screenshot: bool = False
    pdf: bool = False
    extract_with_llm: bool = False
    llm_schema: Optional[Dict[str, Any]] = None
    llm_prompt: Optional[str] = None
    failure_threshold: int = 3
    recovery_timeout: int = 60
    health_check_interval: int = 30


class CloudEngine(BaseCloudEngineV2):
    metadata = EngineMetadata(
        name="cloud",
        engine_type=EngineType.CLOUD,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.PDF_PARSING,
            EngineCapability.SCREENSHOT,
            EngineCapability.ANTI_BOT,
            EngineCapability.LLM_EXTRACTION,
        },
        max_concurrent=5,
        avg_latency_ms=15000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._engine_config = CloudEngineConfig()
        self._client: Optional[httpx.AsyncClient] = None
        self._connection_ok: Optional[bool] = None

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Store the full config before extracting cloud_engine config
        full_config = config.config
        self._engine_config = CloudEngineConfig(**config.config.get("cloud_engine", {}))

        # Initialize HTTP client for Firecrawl API
        timeout = httpx.Timeout(
            connect=10.0,
            read=self._engine_config.timeout / 1000,
            write=30.0,
            pool=5.0,
        )
        self._client = httpx.AsyncClient(
            base_url=self._engine_config.api_url,
            timeout=timeout,
            headers={
                "Authorization": f"Bearer {self._engine_config.api_key}",
                "Content-Type": "application/json",
            },
        )

        # Test connection
        await self._test_connection()

        self.logger.info("Cloud engine (Firecrawl) initialized", api_url=self._engine_config.api_url)

    async def _test_connection(self):
        """Test Firecrawl API connection."""
        try:
            response = await self._client.get("/health")
            if response.status_code == 200:
                self.logger.info("Firecrawl API connection successful")
                self._connection_ok = True
            else:
                self.logger.warning("Firecrawl API health check failed", status=response.status_code)
                self._connection_ok = False
        except Exception as e:
            self.logger.warning("Firecrawl API connection failed", error=str(e))
            self._connection_ok = False

    async def _shutdown_impl(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None
        self._connection_ok = None

    def _health_check_impl(self) -> bool:
        # Return connection state if tested, otherwise client state
        if self._connection_ok is not None:
            return self._connection_ok
        return self._client is not None and not self._client.is_closed

    async def _scrape_impl(self, request: BrowserRequest) -> BrowserResponse:
        """Implementation of scrape for abstract base class."""
        return await self.scrape(request)

    async def _crawl_impl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]:
        """Implementation of crawl for abstract base class."""
        return await self.crawl(urls, config)

    async def _extract_llm_impl(
        self, content: str, schema: Dict[str, Any], prompt: str
    ) -> Dict[str, Any]:
        """Implementation of LLM extraction for abstract base class."""
        return await self.extract_with_llm(content, schema, prompt)

    async def scrape(self, request: BrowserRequest) -> BrowserResponse:
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        start_time = time.time()

        try:
            # Build scrape request
            payload = {
                "url": request.url,
                "formats": self._engine_config.formats,
                "onlyMainContent": self._engine_config.only_main_content,
                "proxy": self._engine_config.proxy,
                "timeout": self._engine_config.timeout,
            }

            if self._engine_config.wait_for_selector:
                payload["waitForSelector"] = self._engine_config.wait_for_selector

            if self._engine_config.wait_for_timeout:
                payload["waitFor"] = self._engine_config.wait_for_timeout

            if self._engine_config.screenshot:
                payload["screenshot"] = True

            if self._engine_config.pdf:
                payload["pdf"] = True

            if self._engine_config.extract_with_llm and self._engine_config.llm_schema:
                payload["extract"] = {
                    "schema": self._engine_config.llm_schema,
                    "prompt": self._engine_config.llm_prompt or "Extract structured data from the page",
                }

            # Execute with retry - use tenacity directly
            from tenacity import (
                AsyncRetrying,
                stop_after_attempt,
                wait_exponential_jitter,
                retry_if_exception_type,
                retry_if_result,
                before_sleep_log,
            )
            
            async def _do_scrape():
                response = await self._client.post("/v1/scrape", json=payload)
                response.raise_for_status()
                return response.json()

            # Create retryer with tenacity directly
            retryer = AsyncRetrying(
                stop=stop_after_attempt(self.retry_policy.max_attempts),
                wait=wait_exponential_jitter(
                    initial=self.retry_policy.base_delay,
                    max=self.retry_policy.max_delay,
                    jitter=self.retry_policy.jitter_factor,
                ),
                retry=(
                    retry_if_exception_type(tuple(self.retry_policy.get_retryable_exceptions()))
                    | retry_if_result(lambda r: self._is_retryable_response(r))
                ),
                before_sleep=before_sleep_log(self.logger, "WARNING"),
                reraise=True,
            )
            
            try:
                result = await retryer(_do_scrape)
            except Exception as e:
                self.logger.error(f"Scrape failed: {e}")
                raise
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Parse result
            data = result.get("data", {})
            markdown = data.get("markdown")
            html = data.get("html")
            metadata = data.get("metadata", {})

            # Handle LLM extraction
            extracted = None
            if self._engine_config.extract_with_llm:
                extracted = data.get("extract")

            return BrowserResponse(
                url=request.url,
                status_code=200,
                title=metadata.get("title", ""),
                html=html,
                text=markdown or "",
                markdown=markdown,
                screenshot=None,  # Firecrawl returns base64 in data
                pdf=None,
                metadata={
                    **metadata,
                    "extracted": extracted,
                    "source": "firecrawl",
                },
                elapsed_ms=elapsed_ms,
            )

        except httpx.HTTPStatusError as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            error_msg = f"HTTP {e.response.status_code}: {e.response.text}"
            return BrowserResponse(
                url=request.url,
                error=error_msg,
                elapsed_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return BrowserResponse(
                url=request.url,
                error=str(e),
                elapsed_ms=elapsed_ms,
            )

    def _create_retryer(self):
        return create_retry_policy(
            max_attempts=self.retry_policy.max_attempts,
            base_delay=self.retry_policy.base_delay,
            max_delay=self.retry_policy.max_delay,
            retryable_status_codes=self.retry_policy.retryable_status_codes,
            retryable_exceptions=self.retry_policy.retryable_exceptions,
        )

    async def crawl(self, urls: List[str], config: Dict[str, Any]) -> List[BrowserResponse]:
        """Crawl multiple URLs."""
        results = []
        semaphore = asyncio.Semaphore(self.metadata.max_concurrent)

        async def crawl_one(url: str) -> BrowserResponse:
            async with semaphore:
                return await self.scrape(BrowserRequest(url=url))

        tasks = [crawl_one(url) for url in urls]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed.append(BrowserResponse(
                    url=urls[i],
                    error=str(result),
                ))
            else:
                processed.append(result)

        return processed

    async def extract_with_llm(
        self,
        content: str,
        schema: Dict[str, Any],
        prompt: str
    ) -> Dict[str, Any]:
        """Extract structured data using Firecrawl's LLM extraction."""
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        payload = {
            "content": content,
            "schema": schema,
            "prompt": prompt,
        }

        retryer = self._create_retryer()

        async def _extract():
            response = await self._client.post("/v1/extract", json=payload)
            response.raise_for_status()
            return response.json()

        result = await self.execute_with_retry(_extract)
        return result.get("data", {})


async def create_cloud_engine(config: EngineConfig) -> CloudEngine:
    """Factory function to create cloud engine."""
    engine = CloudEngine()
    await engine.initialize(config)
    return engine