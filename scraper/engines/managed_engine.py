from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from .base_v2 import BaseManagedEngineV2
from .interfaces import (
    EngineConfig,
    EngineMetadata,
    CrawlStrategy,
    PageResult,
    APIEndpoint,
)
from ..utils.observability import get_logger, MetricsCollector
from ..utils.rate_limiter import RateLimiter, RateLimitConfig, DistributedRateLimiter
from ..utils.retry import RetryPolicy, create_retry_policy
from ..utils.dedup import DeduplicationManager, DedupConfig
from ..utils.state import CrawlStateManager, create_state_manager, CheckpointConfig
from ..utils.queue import QueueManager, ScrapeTask, TaskScheduler, TaskPriority
from ..utils.coordinator import WorkerCoordinator
from ..config.schemas import BrowserType, EngineType, EngineCapability, UniversalConfig


@dataclass
class ManagedEngineConfig:
    enabled: bool = True
    headless: bool = True
    browser_type: BrowserType = BrowserType.CHROMIUM
    max_requests_per_crawl: int = 100
    max_concurrency: int = 10
    request_queue_size: int = 10000
    session_pool_size: int = 50
    session_max_usage: int = 15
    session_max_age_hours: int = 2
    proxy_tiers: List[List[Optional[str]]] = field(default_factory=lambda: [[None]])
    blocked_status_codes: Set[int] = field(default_factory=lambda: {403, 429, 503})
    blocked_error_patterns: List[str] = field(default_factory=lambda: [
        "captcha", "access denied", "blocked", "rate limit"
    ])
    persist_storage: bool = True
    storage_dir: Optional[Path] = None
    dataset_export: bool = True
    key_value_store_export: bool = False
    follow_links: bool = False
    link_selector: str = "a[href]"
    rpm: int = 120


@dataclass
class CrawleeCrawlerState:
    """Track crawler state for pause/resume."""
    pending_urls: List[str] = field(default_factory=list)
    processed_urls: Set[str] = field(default_factory=set)
    failed_urls: Dict[str, int] = field(default_factory=dict)
    stats: Dict[str, Any] = field(default_factory=dict)
    paused: bool = False


class ManagedEngine(BaseManagedEngineV2):
    metadata = EngineMetadata(
        name="managed",
        engine_type=EngineType.MANAGED,
        capabilities={
            EngineCapability.JAVASCRIPT,
            EngineCapability.LARGE_CRAWL,
            EngineCapability.PROXY_ROTATION,
            EngineCapability.SESSION_PERSISTENCE,
            EngineCapability.AUTH_FLOWS,
        },
        max_concurrent=10,
        avg_latency_ms=5000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
        queue_manager: Optional[Any] = None,
        coordinator: Optional[Any] = None,
        distributed_rate_limiter: Optional[Any] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._engine_config = ManagedEngineConfig()
        self._crawler = None
        self._state = CrawleeCrawlerState()
        self._storage_dir: Optional[Path] = None
        self._dataset = None
        self._key_value_store = None
        self._running = False
        self._pause_event = asyncio.Event()
        self._pause_event.set()
        self._state_manager: Optional[CrawlStateManager] = None
        self._checkpoint_config: Optional[CheckpointConfig] = None
        
        # Distributed components
        self._queue_manager: Optional[Any] = queue_manager
        self._coordinator: Optional[Any] = coordinator
        self._distributed_rate_limiter: Optional[Any] = distributed_rate_limiter
        self._task_scheduler: Optional[Any] = None
        self._resume_session_id: Optional[str] = None
        self._session_id: Optional[str] = None
        self._resume_session_id: Optional[str] = None

    async def _initialize_impl(self, config: EngineConfig) -> None:
        self._engine_config = ManagedEngineConfig(**config.config.get("managed_engine", {}))

        # Checkpoint configuration
        checkpoint_cfg = config.config.get("checkpoint", {})
        if checkpoint_cfg:
            self._checkpoint_config = CheckpointConfig(**checkpoint_cfg)

        # Storage setup
        if self._engine_config.persist_storage:
            self._storage_dir = self._engine_config.storage_dir or Path("./storage/crawlee")
            self._storage_dir.mkdir(parents=True, exist_ok=True)

        # Initialize rate limiter (use distributed if available, otherwise local)
        rate_limit_cfg = config.config.get("rate_limit", {})
        if rate_limit_cfg:
            if self._distributed_rate_limiter:
                self.rate_limiter = self._distributed_rate_limiter
            else:
                self.rate_limiter = RateLimiter(RateLimitConfig(**rate_limit_cfg))

        # Retry policy
        retry_cfg = config.config.get("retry_policy", {})
        if retry_cfg:
            self.retry_policy = RetryPolicy(**retry_cfg)

        # Deduplication
        self._dedup = DeduplicationManager(DedupConfig(
            strategy="url_content",
            persistent_storage=True,
        ))

        # Initialize task scheduler if queue manager is available
        if self._queue_manager:
            from ..utils.queue import TaskScheduler
            self._task_scheduler = TaskScheduler(self._queue_manager, UniversalConfig())
            # Load pending tasks from queue
            await self._load_pending_tasks()

        # Initialize state manager if checkpointing is enabled
        if self._checkpoint_config and self._checkpoint_config.enabled:
            dsn = config.config.get("storage", {}).get("postgres_dsn")
            if dsn:
                self._state_manager = CrawlStateManager(self._checkpoint_config)
                await self._state_manager.initialize(dsn)

                # Check if we're resuming a session
                if self._resume_session_id:
                    session = await self._state_manager.resume_session(self._resume_session_id)
                    if session:
                        self._session_id = session.session_id
                        self.logger.info("Resumed crawl session", session_id=self._session_id)
                    else:
                        self.logger.warning("Could not resume session", session_id=self._resume_session_id)
                else:
                    # Create new session
                    session = await self._state_manager.create_session(
                        name=config.name,
                        start_urls=config.config.get("start_urls", []),
                        config_snapshot=config.config,
                    )
                    self._session_id = session.session_id
                    self.logger.info("Created new crawl session", session_id=self._session_id)

        self.logger.info("Managed engine (Crawlee) initialized")

    async def scrape(self, request: "BrowserRequest") -> "BrowserResponse":
        """Scrape a single URL using the managed crawler."""
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        # Initialize crawler if needed
        if not self._crawler:
            await self._initialize_crawler()

        from playwright.async_api import Page
        from .interfaces import BrowserResponse

        start_time = time.time()

        # Create a page for single URL scraping
        context = await self._crawler.browser.new_context()
        page = await context.new_page()

        try:
            await page.goto(request.url, wait_until="networkidle", timeout=60000)
            html = await page.content()
            title = await page.title()
            text = await page.evaluate("() => document.body.innerText")

            elapsed_ms = int((time.time() - start_time) * 1000)

            return BrowserResponse(
                url=request.url,
                status_code=200,
                title=title,
                html=html,
                text=text,
                markdown="",
                elapsed_ms=elapsed_ms,
                success=True,
            )
        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            return BrowserResponse(
                url=request.url,
                status_code=0,
                error=str(e),
                elapsed_ms=elapsed_ms,
                success=False,
            )
        finally:
            await context.close()

    async def _shutdown_impl(self) -> None:
        if self._crawler:
            await self._crawler.stop()
            self._crawler = None
        self._running = False

        # Save checkpoint on shutdown
        if self._state_manager and self._session_id:
            await self._checkpoint_if_needed()

            # Close state manager
            await self._state_manager.close()
            self._state_manager = None

    async def _checkpoint_if_needed(self) -> None:
        """Create a checkpoint if conditions are met."""
        if not self._state_manager or not self._session_id:
            return

        if await self._state_manager.should_checkpoint():
            # Get current frontier data from crawler
            frontier_data = {"pending_count": 0}
            try:
                if self._crawler:
                    stats = await self._crawler.get_statistics()
                    frontier_data = {
                        "pending_count": stats.get("requests_pending", 0),
                        "requests_finished": stats.get("requests_finished", 0),
                        "requests_failed": stats.get("requests_failed", 0),
                    }
            except Exception:
                pass

            await self._state_manager.create_checkpoint(frontier_data)
            self.logger.info("Checkpoint created")

    def _health_check_impl(self) -> bool:
        return True

    async def _crawl_impl(self, strategy: CrawlStrategy) -> "AsyncIterator[PageResult]":
        """Implementation of crawl for abstract base class."""
        # This is a placeholder - the actual crawl logic would need to be implemented
        # based on the strategy parameter
        if False:  # pragma: no cover
            yield PageResult(url="", status_code=200, content="", metadata={})

    async def _add_urls_impl(self, urls: List[str], priority: int) -> None:
        """Implementation of add_urls for abstract base class."""
        if self._queue_manager:
            for url in urls:
                await self._queue_manager.enqueue(ScrapeTask(url=url, priority=priority))
        else:
            self._state.pending_urls.extend(urls)

    async def _get_statistics_impl(self) -> Dict[str, Any]:
        """Implementation of get_statistics for abstract base class."""
        stats = {
            "pending": len(self._state.pending_urls),
            "processed": len(self._state.processed_urls),
            "failed": len(self._state.failed_urls),
            "paused": self._state.paused,
        }
        if self._crawler:
            try:
                crawler_stats = await self._crawler.get_statistics()
                stats.update(crawler_stats)
            except Exception:
                pass
        return stats

    async def _pause_impl(self) -> None:
        """Implementation of pause for abstract base class."""
        self._state.paused = True
        self._pause_event.clear()
        self.logger.info("Crawl paused")

    async def _resume_impl(self) -> None:
        """Implementation of resume for abstract base class."""
        self._state.paused = False
        self._pause_event.set()
        self.logger.info("Crawl resumed")

    async def _initialize_crawler(self):
        """Initialize the Crawlee PlaywrightCrawler."""
        try:
            from crawlee.crawlers import PlaywrightCrawler
            from crawlee.proxy_configuration import ProxyConfiguration
            from crawlee.sessions import SessionPool
        except ImportError:
            raise RuntimeError("Crawlee not installed. Run: pip install crawlee[playwright]")

        # Proxy configuration - flatten and filter out None values
        proxy_urls = []
        for tier in self._engine_config.proxy_tiers:
            for url in tier:
                if url is not None:
                    proxy_urls.append(url)
        proxy_config = ProxyConfiguration(proxy_urls=proxy_urls) if proxy_urls else None

        # Session pool with rotation
        session_pool = SessionPool(
            max_pool_size=self._engine_config.session_pool_size,
            create_session_settings={
                "max_usage_count": self._engine_config.session_max_usage,
                "max_age": timedelta(hours=self._engine_config.session_max_age_hours),
                "blocked_status_codes": list(self._engine_config.blocked_status_codes),
            }
        )

        # Create crawler
        from crawlee import ConcurrencySettings
        concurrency_settings = ConcurrencySettings(
            max_concurrency=self._engine_config.max_concurrency,
            desired_concurrency=self._engine_config.max_concurrency,
        )
        self._crawler = PlaywrightCrawler(
            proxy_configuration=proxy_config,
            use_session_pool=True,
            session_pool=session_pool,
            max_requests_per_crawl=self._engine_config.max_requests_per_crawl,
            concurrency_settings=concurrency_settings,
            headless=self._engine_config.headless,
            browser_type=self._engine_config.browser_type.value if hasattr(self._engine_config.browser_type, 'value') else self._engine_config.browser_type,
        )

        # Set up router with default handler
        @self._crawler.router.default_handler
        async def default_handler(context):
            await self._handle_page(context)

    async def _handle_page(self, context):
        """Handle a page in the crawler."""
        from crawlee.crawlers import PlaywrightCrawlingContext

        if isinstance(context, PlaywrightCrawlingContext):
            page = context.page
            request = context.request

            # Wait for page load
            await page.wait_for_load_state("networkidle")

            # Extract content
            html = await page.content()
            title = await page.title()
            text = await page.evaluate("() => document.body.innerText")

            # Create page result
            result = PageResult(
                url=request.url,
                page_type="unknown",
                data={
                    "html": html,
                    "title": title,
                    "text": text,
                },
                raw_html=html,
                engine_used="managed",
                metadata={
                    "status_code": 200,
                    "depth": request.user_data.get("depth", 0) if request.user_data else 0,
                },
            )

            # Export to dataset if enabled
            if self._engine_config.dataset_export:
                await self._export_to_dataset(result)

            # Follow links if enabled
            if self._engine_config.follow_links:
                await context.enqueue_links(
                    selector=self._engine_config.link_selector,
                    label="detail",
                )

    async def _export_to_dataset(self, result: PageResult):
        """Export result to Crawlee dataset."""
        try:
            from crawlee.storages import Dataset
            dataset = await Dataset.open()
            await dataset.push_data({
                "url": result.url,
                "title": result.metadata.get("title", ""),
                "data": result.data,
                "metadata": result.metadata,
                "scraped_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            self.logger.warning("Failed to export to dataset", error=str(e))

    async def crawl(self, strategy: CrawlStrategy) -> AsyncIterator[PageResult]:
        """Crawl using the strategy."""
        if not self._crawler:
            await self._initialize_crawler()

        # Prepare start URLs
        start_urls = strategy.start_urls
        if not start_urls:
            return

        # If using distributed queue, get tasks from queue manager
        if self._task_scheduler and self._queue_manager:
            # Load pending tasks from queue
            await self._load_pending_tasks()
            
            # Process tasks from queue
            async for result in self._process_queue_tasks():
                yield result
            return

        # Traditional crawl mode (non-distributed)
        # If resuming, get pending URLs from state manager
        if self._state_manager and self._session_id:
            pending_urls = await self._state_manager.get_next_urls(count=100)
            for entry in pending_urls:
                if self._dedup and self._dedup.is_duplicate(entry.url):
                    continue
                self._crawler.add_requests([{
                    "url": entry.url,
                    "user_data": {"depth": entry.depth, "page_type": "list"},
                }])
        else:
            # Add initial URLs to crawler
            for url in start_urls:
                if self._dedup and self._dedup.is_duplicate(url):
                    continue
                self._crawler.add_requests([{
                    "url": url,
                    "user_data": {"depth": 0, "page_type": "list"},
                }])

        # Run crawler
        self._running = True
        await self._crawler.run()

        # Checkpoint after crawl if enabled
        if self._state_manager and self._session_id:
            await self._checkpoint_if_needed()

        # Yield results from dataset
        try:
            from crawlee.storages import Dataset
            dataset = await Dataset.open()
            async for item in dataset.iterate():
                yield PageResult(
                    url=item.get("url", ""),
                    page_type=item.get("metadata", {}).get("page_type", "unknown"),
                    data=item.get("data", {}),
                    raw_html=item.get("data", {}).get("html", ""),
                    engine_used="managed",
                    metadata=item.get("metadata", {}),
                )
        except Exception:
            pass

    async def _load_pending_tasks(self) -> None:
        """Load pending tasks from queue manager into task scheduler."""
        if not self._task_scheduler or not self._queue_manager:
            return
        
        tasks = await self._queue_manager.get_tasks(batch_size=100)
        if tasks:
            await self._task_scheduler.add_tasks(tasks)
            self.logger.info(f"Loaded {len(tasks)} pending tasks from queue")

    async def _process_queue_tasks(self) -> AsyncIterator[PageResult]:
        """Process tasks from the distributed queue."""
        if not self._task_scheduler or not self._queue_manager or not self._crawler:
            return

        while True:
            # Check if we have pending tasks
            if self._task_scheduler.pending_count() == 0:
                # Try to load more tasks
                await self._load_pending_tasks()
                if self._task_scheduler.pending_count() == 0:
                    break

            # Get next task
            task = await self._task_scheduler.get_next_task()
            if not task:
                await asyncio.sleep(0.1)
                continue

            # Process task
            result = await self._process_single_task(task)
            if result:
                yield result

    async def _process_single_task(self, task: Any) -> Optional[PageResult]:
        """Process a single scrape task."""
        if not self._crawler:
            return None

        # Use coordinator to track task
        if self._coordinator:
            if not self._coordinator.register_task(task.task_id):
                # Requeue if at capacity
                if self._queue_manager:
                    await self._queue_manager.publish_task(task)
                return None

        try:
            # Acquire rate limit
            domain = task.url.split("/")[2] if "//" in task.url else "default"
            if self._distributed_rate_limiter:
                await self._distributed_rate_limiter.acquire(domain)
            elif self.rate_limiter:
                await self.rate_limiter.acquire(domain)

            # Add task to crawler
            self._crawler.add_requests([{
                "url": task.url,
                "user_data": {"depth": task.depth, "page_type": "list", "task_id": task.task_id},
            }])

            # Wait for result (simplified - in real impl would use result callback)
            # For now, just yield a placeholder
            return PageResult(
                url=task.url,
                page_type="pending",
                data={"task_id": task.task_id},
                raw_html="",
                engine_used="managed",
                metadata={"status": "queued"},
            )
        except Exception as e:
            self.logger.error(f"Task {task.task_id} failed: {e}")
            if self._coordinator:
                self._coordinator.complete_task(task.task_id, success=False)
            return None

    async def add_urls(self, urls: List[str], priority: int = 0) -> None:
        """Add URLs to the crawl queue."""
        if not self._crawler:
            await self._initialize_crawler()

        requests = []
        for url in urls:
            if self._dedup and self._dedup.is_duplicate(url):
                continue
            requests.append({
                "url": url,
                "priority": priority,
                "user_data": {"depth": 0, "page_type": "list"},
            })

        if requests:
            self._crawler.add_requests(requests)

    async def get_statistics(self) -> Dict[str, Any]:
        """Get crawler statistics."""
        stats = {
            "engine": "managed",
            "running": self._running,
            "pending_urls": len(self._state.pending_urls),
            "processed_urls": len(self._state.processed_urls),
            "failed_urls": len(self._state.failed_urls),
            "paused": self._state.paused,
        }

        if self._crawler:
            try:
                stats["crawler_stats"] = await self._crawler.get_statistics()
            except Exception:
                pass

        return stats

    async def pause(self) -> None:
        """Pause the crawler."""
        if self._crawler:
            await self._crawler.pause()
            self._state.paused = True
            self._pause_event.clear()

    async def resume(self) -> None:
        """Resume the crawler."""
        if self._crawler:
            await self._crawler.resume()
            self._state.paused = False
            self._pause_event.set()

    async def get_results(self) -> AsyncIterator[PageResult]:
        """Get results from the dataset."""
        try:
            from crawlee.storages import Dataset
            dataset = await Dataset.open()
            async for item in dataset.iterate():
                yield PageResult(
                    url=item.get("url", ""),
                    page_type=item.get("metadata", {}).get("page_type", "unknown"),
                    data=item.get("data", {}),
                    raw_html=item.get("data", {}).get("html", ""),
                    engine_used="managed",
                    metadata=item.get("metadata", {}),
                )
        except Exception as e:
            self.logger.error("Failed to get results", error=str(e))


async def create_managed_engine(config: EngineConfig) -> ManagedEngine:
    """Factory function to create managed engine."""
    engine = ManagedEngine()
    await engine.initialize(config)
    return engine