from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union, Awaitable
from playwright.async_api import (
    Browser as PlaywrightBrowser,
    BrowserContext as PlaywrightBrowserContext,
    Page,
    Playwright,
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

from .base_v2 import BaseBrowserEngineV2, BrowserContextWrapper
from .browser_pool import AdaptiveBrowserPool, create_adaptive_pool
from .interfaces import (
    BrowserRequest,
    BrowserResponse,
    EngineConfig,
    EngineMetadata,
)
from .interactions import (
    InteractionExecutor, 
    create_interaction_executor, 
    InteractionConfig,
    ActionType,
    InteractionStep,
    InteractionSequence,
    InteractionResult,
)
from .stealth import StealthManager, apply_stealth
from ..utils.observability import get_logger, MetricsCollector
from ..config.schemas import (
    BrowserType, 
    BrowserContextConfig, 
    EngineType, 
    EngineCapability, 
    RateLimitConfig, 
    RetryPolicy, 
    SessionManager,
    BrowserEngineConfig as BrowserEngineConfigSchema,
)


class BrowserEngine(BaseBrowserEngineV2):
    metadata = EngineMetadata(
        name="browser",
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

    _engine_config: BrowserEngineConfigSchema

    def __init__(
        self,
        rate_limit_config: Optional[RateLimitConfig] = None,
        retry_policy: Optional[RetryPolicy] = None,
        session_manager: Optional[SessionManager] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[PlaywrightBrowser] = None
        self._engine_config = BrowserEngineConfigSchema()
        self._stealth_manager: Optional[StealthManager] = None
        self._default_context_config: Dict[str, Any] = {}

    async def _launch_browser(self) -> PlaywrightBrowser:
        """Launch the Playwright browser with configured options."""
        if self._playwright is None:
            self._playwright = await async_playwright().start()

        browser_type = self._playwright.chromium
        if self._engine_config.browser_type == BrowserType.FIREFOX:
            browser_type = self._playwright.firefox
        elif self._engine_config.browser_type == BrowserType.WEBKIT:
            browser_type = self._playwright.webkit

        launch_args = [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-gpu",
            "--disable-web-security",
            "--disable-features=IsolateOrigins,site-per-process",
        ]

        if self._engine_config.headless:
            launch_args.append("--headless=new")

        if self._engine_config.ignore_https_errors:
            launch_args.append("--ignore-certificate-errors")

        self._browser = await browser_type.launch(
            headless=self._engine_config.headless,
            args=launch_args,
            timeout=60000,
        )

        return self._browser

    def _create_context_fn(self) -> Callable[[Dict[str, Any]], Awaitable[PlaywrightBrowserContext]]:
        """Return a function that creates new browser contexts."""
        async def create_context(config: Dict[str, Any]) -> PlaywrightBrowserContext:
            if not self._browser:
                raise RuntimeError("Browser not launched")

            # Merge default context config with provided config
            merged_config = {**self._default_context_config, **config}

            context = await self._browser.new_context(**merged_config)

            # Apply stealth if enabled
            if self._engine_config.stealth_mode and self._stealth_manager:
                await self._stealth_manager.apply_to_context(context)

            # Set up resource blocking
            if self._engine_config.resource_blocking:
                await self._setup_resource_blocking(context)

            # Set up HAR recording if enabled
            if self._engine_config.har_recording and self._engine_config.har_path:
                await context.record_har(path=self._engine_config.har_path)  # type: ignore[attr-defined]

            # Set up video recording if enabled
            if self._engine_config.video_recording and self._engine_config.video_dir:
                await context.record_video(dir=self._engine_config.video_dir)  # type: ignore[attr-defined]

            # Enable CDP if requested
            if self._engine_config.cdp_enabled:
                await self._setup_cdp(context)

            return context

        return create_context

    async def _setup_resource_blocking(self, context: PlaywrightBrowserContext) -> None:
        """Set up resource blocking based on configuration."""
        block_types = []
        blocking = self._engine_config.resource_blocking

        if blocking.get("images"):
            block_types.append("image")
        if blocking.get("fonts"):
            block_types.append("font")
        if blocking.get("css"):
            block_types.append("stylesheet")
        if blocking.get("media"):
            block_types.extend(["media", "video", "audio"])
        if blocking.get("websocket"):
            block_types.append("websocket")

        if block_types:
            await context.route("**/*", lambda route: route.abort()
                if route.request.resource_type in block_types else route.continue_())

    async def _setup_cdp(self, context: PlaywrightBrowserContext) -> None:
        """Set up CDP session for advanced features."""
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)

        for cmd in self._engine_config.cdp_commands:
            try:
                await cdp.send(cmd.get("method"), cmd.get("params", {}))
            except Exception as e:
                self.logger.warning("CDP command failed", command=cmd, error=str(e))

    async def _initialize_impl(self, config: EngineConfig) -> None:
        # Store engine config
        self._engine_config = BrowserEngineConfigSchema(**config.config.get("browser_engine", {}))

        # Initialize stealth manager
        if self._engine_config.stealth_mode:
            from .stealth import StealthConfig
            stealth_config = StealthConfig(**self._engine_config.stealth_config)
            self._stealth_manager = StealthManager(stealth_config)

        # Build default context config from schema
        ctx_cfg = self._engine_config.context_config
        self._default_context_config = {
            "viewport": {
                "width": ctx_cfg.viewport_width,
                "height": ctx_cfg.viewport_height,
            },
            "device_scale_factor": ctx_cfg.device_scale_factor,
            "is_mobile": ctx_cfg.is_mobile,
            "has_touch": ctx_cfg.has_touch,
            "locale": ctx_cfg.locale,
            "timezone_id": ctx_cfg.timezone_id,
            "geolocation": ctx_cfg.geolocation,
            "permissions": ctx_cfg.permissions,
            "color_scheme": ctx_cfg.color_scheme,
            "reduced_motion": ctx_cfg.reduced_motion,
            "forced_colors": ctx_cfg.forced_colors,
            "ignore_https_errors": self._engine_config.ignore_https_errors,
            "java_script_enabled": self._engine_config.java_script_enabled,
            "service_workers": self._engine_config.service_workers,
            "user_agent": ctx_cfg.user_agent if hasattr(ctx_cfg, 'user_agent') else None,
        }

        # Launch browser
        await self._launch_browser()

        # Create adaptive pool
        self._pool = create_adaptive_pool(
            config=self._engine_config,
            create_context_fn=self._create_context_fn(),
            engine_name=self.metadata.name,
        )
        await self._pool.start()

        # Initialize interaction executor
        self._interaction_config = InteractionConfig(
            default_timeout=self._engine_config.navigation_timeout,
            default_wait_ms=self._engine_config.extra_wait_ms,
            human_like=self._engine_config.realistic_timing,
            min_delay_ms=50,
            max_delay_ms=300,
            scroll_behavior="smooth",
            screenshot_on_error=self._engine_config.screenshot_on_error,
            capture_console=True,
            capture_network=self._engine_config.har_recording,
        )

        self.logger.info("Browser engine initialized with adaptive pool")

    async def _shutdown_impl(self) -> None:
        if self._pool:
            await self._pool.stop()
            self._pool = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    def _health_check_impl(self) -> bool:
        return self._browser is not None and self._browser.is_connected()

    async def _get_context(self) -> PlaywrightBrowserContext:
        """Get a context from the adaptive pool."""
        if not self._pool:
            raise RuntimeError("Browser pool not initialized")
        return await self._pool.get_context()

    async def _return_context(self, context: PlaywrightBrowserContext) -> None:
        """Return context to the adaptive pool."""
        if self._pool:
            await self._pool.return_context(context)

    async def _create_context(self, config: Dict[str, Any]) -> PlaywrightBrowserContext:
        """Create a new browser context (used by the pool)."""
        if not self._browser:
            raise RuntimeError("Browser not launched")

        merged_config = {**self._default_context_config, **config}
        context = await self._browser.new_context(**config)

        # Apply stealth
        if self._engine_config.stealth_mode and self._stealth_manager:
            await self._stealth_manager.apply_to_context(context)

        # Resource blocking
        if self._engine_config.resource_blocking:
            await self._setup_resource_blocking(context)

        # HAR/Video
        if self._engine_config.har_recording and self._engine_config.har_path:
            await context.record_har(path=self._engine_config.har_path)  # type: ignore[attr-defined]

        if self._engine_config.video_recording and self._engine_config.video_dir:
            await context.record_video(dir=self._engine_config.video_dir)  # type: ignore[attr-defined]

        # CDP
        if self._engine_config.cdp_enabled:
            await self._setup_cdp(context)

        return context

    async def _navigate_impl(self, context: PlaywrightBrowserContext, request: BrowserRequest) -> BrowserResponse:
        """Navigate to URL and extract content."""
        page = await context.new_page()
        page.set_default_timeout(self._engine_config.navigation_timeout)

        # Set up console/error listeners if needed
        console_logs = []
        network_requests = []

        if self._interaction_config.capture_console:
            page.on("console", lambda msg: console_logs.append({
                "type": msg.type,
                "text": msg.text,
                "location": msg.location,
            }))

        if self._interaction_config.capture_network:
            page.on("request", lambda req: network_requests.append({
                "url": req.url,
                "method": req.method,
                "headers": dict(req.headers),
                "timestamp": time.time(),
            }))
            page.on("response", lambda resp: next(
                (r.update({"status": resp.status, "headers": dict(resp.headers)})
                 for r in network_requests if r["url"] == resp.url), None))

        try:
            # Navigate
            response = await page.goto(
                request.url,
                wait_until=request.wait_until or self._engine_config.wait_until,
                timeout=request.timeout or self._engine_config.navigation_timeout,
            )

            # Wait for selector if specified
            wait_selector = request.wait_for_selector or self._engine_config.wait_for_selector
            if wait_selector:
                await page.wait_for_selector(wait_selector, timeout=request.timeout or self._engine_config.navigation_timeout)

            # Wait for function if specified
            if request.wait_for_function or self._engine_config.wait_for_function:
                await page.wait_for_function(
                    request.wait_for_function or self._engine_config.wait_for_function,
                    timeout=request.timeout or self._engine_config.navigation_timeout,
                )

            # Extra wait
            wait_time = request.wait_for_timeout or self._engine_config.wait_for_timeout or self._engine_config.extra_wait_ms
            if wait_time:
                await page.wait_for_timeout(wait_time)

            # Handle infinite scroll
            if self._engine_config.infinite_scroll:
                await self._handle_infinite_scroll(page)

            # Execute interaction sequences
            if self._engine_config.interaction_sequences:
                for seq_config in self._engine_config.interaction_sequences:
                    seq = InteractionSequence(
                        steps=[InteractionStep(**s) for s in seq_config.get("steps", [])],
                        name=seq_config.get("name", ""),
                        description=seq_config.get("description", ""),
                        stop_on_error=seq_config.get("stop_on_error", True),
                    )
                    await self._execute_interactions(page, seq)

            # Extract content
            html = await page.content()
            title = await page.title()
            text = await page.evaluate("() => document.body.innerText")

            # Screenshot on error if needed
            screenshot = None
            if self._engine_config.screenshot_on_error:
                try:
                    screenshot = await page.screenshot(full_page=True)
                except Exception:
                    pass

            # Get cookies
            cookies = {}
            for cookie in await context.cookies():
                cookies[cookie["name"]] = cookie["value"]

            # Get localStorage/sessionStorage
            local_storage = await page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
            session_storage = await page.evaluate("() => Object.fromEntries(Object.entries(sessionStorage))")

            return BrowserResponse(
                url=page.url,
                status_code=response.status if response else 200,
                title=title,
                html=html,
                text=text,
                markdown="",
                screenshot=screenshot,
                pdf=None,
                har=None,
                console_logs=console_logs,
                network_requests=network_requests,
                cookies=cookies,
                local_storage=local_storage,
                session_storage=session_storage,
                metadata={
                    "title": title,
                    "status_code": response.status if response else 200,
                },
            )

        except PlaywrightTimeoutError as e:
            raise TimeoutError(f"Navigation timeout: {e}")
        except Exception as e:
            # Capture screenshot on error
            screenshot = None
            if self._engine_config.screenshot_on_error:
                try:
                    screenshot = await page.screenshot(full_page=True)
                except Exception:
                    pass

            return BrowserResponse(
                url=request.url,
                error=str(e),
                screenshot=screenshot,
            )
        finally:
            await page.close()

    async def _handle_infinite_scroll(self, page: Page):
        """Handle infinite scroll pagination."""
        max_iterations = self._engine_config.infinite_scroll_max_iterations
        wait_ms = self._engine_config.infinite_scroll_wait_ms

        last_height = 0
        for i in range(max_iterations):
            # Scroll to bottom
            await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            await asyncio.sleep(wait_ms / 1000)

            # Check if we've reached the bottom
            new_height = await page.evaluate("document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height

    async def _execute_interactions(self, page: Page, sequence: InteractionSequence):
        """Execute an interaction sequence on the page."""
        executor = create_interaction_executor(page, self._interaction_config)
        await executor.execute(sequence)

    async def _interact_impl(self, context: PlaywrightBrowserContext, sequence: InteractionSequence) -> InteractionResult:
        """Execute interaction sequence on a new page."""
        page = await context.new_page()

        try:
            executor = create_interaction_executor(page, self._interaction_config)
            return await executor.execute(sequence)
        finally:
            await page.close()

    async def _execute_cdp_impl(self, context: PlaywrightBrowserContext, commands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Execute CDP commands."""
        page = await context.new_page()
        cdp = await context.new_cdp_session(page)

        results = []
        for cmd in commands:
            try:
                result = await cdp.send(cmd.get("method"), cmd.get("params", {}))
                results.append({"success": True, "result": result, "command": cmd})
            except Exception as e:
                results.append({"success": False, "error": str(e), "command": cmd})

        await page.close()
        return results

    async def _evaluate_impl(self, context: PlaywrightBrowserContext, script: str, await_promise: bool) -> Any:
        """Evaluate JavaScript in a new page."""
        page = await context.new_page()
        try:
            if await_promise:
                return await page.evaluate(script)
            else:
                return await page.evaluate(f"() => {{ {script} }}")
        finally:
            await page.close()

    def create_context(self, config: Dict[str, Any]) -> BrowserContextWrapper:
        return BrowserContextWrapper(self, config)

    async def _scrape_impl(self, request: BrowserRequest) -> BrowserResponse:
        """Scrape implementation - navigates to URL and extracts content."""
        return await self._navigate_impl(await self._get_context(), request)

    async def get_page_count(self) -> int:
        if self._pool:
            metrics = await self._pool.get_metrics()
            return sum(c.get("pages_processed", 0) for c in metrics.get("contexts", {}).values())
        return 0

    async def get_pool_metrics(self) -> Dict[str, Any]:
        """Get adaptive pool metrics."""
        if self._pool:
            return await self._pool.get_metrics()
        return {}

    async def recycle_context(self, context_id: str) -> None:
        """Manually trigger context recycle."""
        if self._pool:
            await self._pool._recycle_context(context_id, "manual")


async def create_browser_engine(config: EngineConfig) -> BrowserEngine:
    """Factory function to create browser engine."""
    engine = BrowserEngine()
    await engine.initialize(config)
    return engine