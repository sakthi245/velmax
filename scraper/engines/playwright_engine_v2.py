from __future__ import annotations

from typing import Any, AsyncIterator, Optional
import asyncio
import time
import logging

from playwright.async_api import Browser as PlaywrightBrowser, BrowserContext as PlaywrightBrowserContext, Page, async_playwright, TimeoutError as PlaywrightTimeoutError

from .base_v2 import BaseEngineV2
from .interfaces import EngineConfig, EngineMetadata
from ..config.schemas import EngineType, EngineCapability
from ..engines.base import ScrapeRequest, ScrapeResponse
from .stealth import StealthManager, StealthConfig
from ..utils.observability import get_logger

LOG = logging.getLogger(__name__)


class PlaywrightEngineV2(BaseEngineV2):
    """V2 version of PlaywrightEngine - inherits from BaseEngineV2 with circuit breaker, rate limiter, retry."""
    
    metadata = EngineMetadata(
        name="playwright",
        engine_type=EngineType.BROWSER,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.AUTH_FLOWS,
            EngineCapability.STEALTH,
            EngineCapability.SCREENSHOT,
            EngineCapability.HAR_RECORDING,
            EngineCapability.INFINITE_SCROLL,
            EngineCapability.IFRAME_HANDLING,
            EngineCapability.CDP_ACCESS,
        },
        max_concurrent=5,
        avg_latency_ms=8000,
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
        self._playwright = None
        self._browser: Optional[PlaywrightBrowser] = None
        self._stealth_manager: Optional[StealthManager] = None
        self._engine_config: dict = {}

    async def _launch_browser(self) -> PlaywrightBrowser:
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        if self._engine_config.get("headless", True):
            launch_args.append("--headless=new")

        if self._engine_config.get("ignore_https_errors", True):
            launch_args.append("--ignore-certificate-errors")

        self._browser = await self._playwright.chromium.launch(
            headless=self._engine_config.get("headless", True),
            args=launch_args,
            timeout=60000,
        )
        return self._browser

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Handle both EngineConfig object and plain dict
        if isinstance(config, EngineConfig):
            self._engine_config = config.config.get("playwright", {})
        else:
            self._engine_config = config.get("playwright", {})

        # Initialize stealth manager
        if self._engine_config.get("stealth_mode", True):
            stealth_config = StealthConfig(**self._engine_config.get("stealth_config", {}))
            self._stealth_manager = StealthManager(stealth_config)

        await self._launch_browser()
        LOG.info("PlaywrightEngineV2 initialized")

    async def _shutdown_impl(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def _health_check_impl(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def scrape(self, request: ScrapeRequest) -> ScrapeResponse:
        """Legacy-compatible scrape method."""
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        start_time = time.time()

        try:
            timeout = request.engine_options.get("timeout", 20) * 1000
            agent = request.engine_options.get("user_agent")
            wait_for = request.engine_options.get("wait_for_selector")
            wait_until = request.engine_options.get("wait_until", "networkidle")

            # Use sync playwright in executor for simplicity
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None,
                self._scrape_sync,
                request.url,
                timeout,
                agent,
                wait_for,
                wait_until,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            if "error" in result:
                self.metrics.record_request(False, latency_ms, result["error"])
                return ScrapeResponse(
                    url=request.url,
                    success=False,
                    data={},
                    markdown=None,
                    html=None,
                    metadata={},
                    engine=self.metadata.name,
                    error=result["error"],
                    latency_ms=latency_ms,
                )

            res = ScrapeResponse(
                url=result["url"],
                success=True,
                data={"title": result["title"], "html": result["html"]},
                markdown=None,
                html=result["html"],
                metadata={"title": result["title"], "status_code": 200},
                engine=self.metadata.name,
                latency_ms=latency_ms,
            )
            self.metrics.record_request(True, latency_ms)
            return res

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            LOG.warning(f"PlaywrightEngineV2 scrape failed for {request.url}: {e}")

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

    def _scrape_sync(self, url: str, timeout: int, agent: str, wait_for: Optional[str], wait_until: Optional[str]) -> dict:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self._engine_config.get("headless", True))
            try:
                page = browser.new_page(user_agent=agent)
                page.goto(url, wait_until=wait_until or "networkidle", timeout=timeout)

                if wait_for:
                    page.wait_for_selector(wait_for, timeout=timeout)

                html = page.content()
                from .local import record_from_html
                record = record_from_html(page.url, html, self.metadata.name)
                record["html"] = html
                return record
            finally:
                browser.close()

    async def crawl(self, urls: list[str], config: dict) -> AsyncIterator[ScrapeResponse]:
        for url in urls:
            yield await self.scrape(ScrapeRequest(url=url, engine_options=config))

    async def _crawl_impl(self, strategy) -> AsyncIterator[Any]:
        pass  # Not used in legacy interface