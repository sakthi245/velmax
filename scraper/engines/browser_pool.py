from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from playwright.async_api import BrowserContext as PlaywrightBrowserContext

from ..config.schemas import BrowserEngineConfig, ObservabilityConfig
from ..utils.observability import get_logger, MetricsCollector
from ..utils.rate_limiter import RateLimiter, RateLimitConfig

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    psutil = None

logger = get_logger("browser_pool")


@dataclass
class CookieData:
    """Cookie data for persistence."""
    name: str
    value: str
    domain: str
    path: str = "/"
    expires: Optional[float] = None
    secure: bool = False
    http_only: bool = False
    same_site: str = "Lax"


@dataclass
class ContextCookies:
    """Cookie storage for a browser context."""
    context_id: str
    cookies: List[CookieData] = field(default_factory=list)
    last_saved: float = field(default_factory=time.time)
    domain: str = ""


@dataclass
class ContextMetrics:
    context_id: str
    pages_processed: int = 0
    memory_mb: float = 0.0
    error_count: int = 0
    last_used: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class AdaptiveBrowserPool:
    """Memory-aware browser context pool with auto-scaling for low-memory systems."""
    
    def __init__(
        self,
        config: BrowserEngineConfig,
        create_context_fn: Callable[[Dict[str, Any]], Any],
        engine_name: str = "browser",
    ):
        self.config = config
        self._create_context_fn = create_context_fn
        self.engine_name = engine_name
        self.logger = get_logger(f"browser_pool.{engine_name}")
        
        # Memory detection
        self._total_memory_mb = self._detect_total_memory()
        self._available_for_browser = self._calculate_budget()
        self._per_context_estimate_mb = 150
        
        # Pool sizing (adaptive)
        self._pool_min = config.pool_min
        self._pool_max = min(config.pool_max, self._available_for_browser // self._per_context_estimate_mb)
        self._idle_timeout_ms = config.min_idle_timeout_ms
        self._current_idle_timeout = config.min_idle_timeout_ms
        self._max_idle_timeout = config.max_idle_timeout_ms
        self._min_idle_timeout = config.min_idle_timeout_ms
        
        # Adaptive behavior config
        self._scale_up_queue_threshold = config.scale_up_on_queue
        self._scale_down_idle_ratio = config.scale_down_idle_ratio
        self._recycle_memory_mb = config.recycle_after_memory_mb
        self._recycle_pages = config.recycle_after_pages
        self._recycle_error_rate = config.recycle_on_error_rate
        self._adaptive_enabled = config.adaptive_pool
        
        # Pool state
        self._contexts: Dict[str, PlaywrightBrowserContext] = {}
        self._context_metrics: Dict[str, ContextMetrics] = {}
        self._idle_queue: asyncio.Queue = asyncio.Queue()
        self._context_lock = asyncio.Lock()
        
        # Cookie persistence
        self._context_cookies: Dict[str, ContextCookies] = {}
        self._cookie_storage: Optional[Any] = None  # SessionManager or custom storage
        
        # Background tasks
        self._recycle_task: Optional[asyncio.Task] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._running = False
        
        # Metrics
        observability_config = ObservabilityConfig(
            metrics_enabled=True,
            log_level="INFO",
            structured_logging=True,
        )
        self._metrics = MetricsCollector(engine_name, observability_config)
        
        # Log initial config
        self.logger.info(
            "Adaptive browser pool initialized",
            pool_min=self._pool_min,
            pool_max=self._pool_max,
            available_memory_mb=self._available_for_browser,
            adaptive_enabled=self._adaptive_enabled,
        )
    
    def _detect_total_memory(self) -> int:
        """Detect available system memory using psutil."""
        if PSUTIL_AVAILABLE:
            try:
                return psutil.virtual_memory().available // (1024 * 1024)
            except Exception:
                pass
        return 2048
    
    def _calculate_budget(self) -> int:
        """Calculate safe memory budget for browser pool."""
        reserved_mb = 500
        budget = max(256, self._total_memory_mb - reserved_mb)
        return min(budget, self.config.pool_max_memory_mb)
    
    async def start(self):
        """Start the pool and background tasks."""
        if self._running:
            return
        
        self._running = True
        self._recycle_task = asyncio.create_task(self._recycle_loop())
        self._monitor_task = asyncio.create_task(self._monitor_loop())
        
        # Pre-warm minimum contexts
        for _ in range(self._pool_min):
            try:
                await self._create_new_context()
            except Exception as e:
                self.logger.warning("Failed to pre-warm context", error=str(e))
        
        self.logger.info("Browser pool started", pool_size=len(self._contexts))
    
    async def stop(self):
        """Stop the pool and cleanup all contexts."""
        if not self._running:
            return
        
        self._running = False
        
        if self._recycle_task:
            self._recycle_task.cancel()
            try:
                await self._recycle_task
            except asyncio.CancelledError:
                pass
        
        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
        
        # Close all contexts
        async with self._context_lock:
            for ctx_id, context in list(self._contexts.items()):
                try:
                    await context.close()
                except Exception as e:
                    self.logger.warning("Error closing context", context_id=ctx_id, error=str(e))
            self._contexts.clear()
            self._context_metrics.clear()
        
        # Clear idle queue
        while not self._idle_queue.empty():
            try:
                context = self._idle_queue.get_nowait()
                await context.close()
            except asyncio.QueueEmpty:
                break
            except Exception:
                pass
        
        self.logger.info("Browser pool stopped")
    
    async def get_context(self) -> PlaywrightBrowserContext:
        """Get a context from the pool (creates new if needed)."""
        async with self._context_lock:
            # Try idle queue first
            if not self._idle_queue.empty():
                context = await self._idle_queue.get()
                ctx_id = str(id(context))
                if ctx_id in self._contexts and await self._is_context_healthy(context):
                    self._context_metrics[ctx_id].last_used = time.time()
                    # Restore cookies for existing context
                    await self._restore_context_cookies(ctx_id, context)
                    return context
                else:
                    # Stale context, discard
                    try:
                        await context.close()
                    except Exception:
                        pass
        
        # Check if we can create new context
        async with self._context_lock:
            if len(self._contexts) < self._pool_max:
                return await self._create_new_context()
        
        # Wait for available context (queue requests)
        self.logger.debug("Pool exhausted, waiting for available context")
        context = await self._idle_queue.get()
        # Restore cookies for context from queue
        ctx_id = str(id(context))
        if ctx_id in self._contexts:
            await self._restore_context_cookies(ctx_id, context)
        return context
    
    async def return_context(self, context: PlaywrightBrowserContext):
        """Return context to pool with health check."""
        async with self._context_lock:
            ctx_id = str(id(context))
            
            if ctx_id not in self._contexts:
                # Context was recycled, just close it
                try:
                    await context.close()
                except Exception:
                    pass
                return
            
            # Update metrics
            metrics = self._context_metrics.get(ctx_id)
            if metrics:
                metrics.pages_processed += 1
                metrics.last_used = time.time()
            
            # Check if context should be recycled
            if await self._should_recycle(ctx_id):
                await self._recycle_context(ctx_id, "recycle_condition")
                return
            
            # Return to idle queue
            await self._idle_queue.put(context)
        
        # Adaptive scaling (outside lock)
        await self._maybe_scale_down()
    
    async def _create_new_context(self) -> PlaywrightBrowserContext:
        """Create a new browser context."""
        context_config = {}
        if hasattr(self.config, 'context_config'):
            cc = self.config.context_config
            # Convert from Pydantic model to dict with proper viewport format
            if hasattr(cc, '__dict__'):
                d = cc.__dict__
                # Convert viewport_width/height to viewport dict
                if 'viewport_width' in d and 'viewport_height' in d:
                    d = {**d}
                    d['viewport'] = {'width': d.pop('viewport_width'), 'height': d.pop('viewport_height')}
                context_config = d
            else:
                context_config = {}
        context = await self._create_context_fn(context_config)
        
        ctx_id = str(id(context))
        self._contexts[ctx_id] = context
        self._context_metrics[ctx_id] = ContextMetrics(
            context_id=ctx_id,
            created_at=time.time(),
        )
        
        # Restore cookies for new context if we have saved cookies for this domain
        # Note: We use the context_id as key, but could also look up by domain
        await self._restore_context_cookies(ctx_id, context)
        
        # Update Prometheus metrics
        self._metrics.record_request(self.engine_name, True, 0)  # Track pool growth
        
        self.logger.debug("Created new context", pool_size=len(self._contexts), ctx_id=ctx_id[:8])
        return context
    
    async def _is_context_healthy(self, context: PlaywrightBrowserContext) -> bool:
        """Check if context is still healthy."""
        try:
            # Quick health check - try to evaluate simple script
            await context.evaluate("1+1")
            return True
        except Exception:
            return False
    
    async def _should_recycle(self, ctx_id: str) -> bool:
        """Check if context should be recycled."""
        metrics = self._context_metrics.get(ctx_id)
        if not metrics:
            return True
        
        # Memory pressure
        if metrics.memory_mb > self._recycle_memory_mb:
            return True
        
        # Page count
        if metrics.pages_processed >= self._recycle_pages:
            return True
        
        # Error rate
        if metrics.pages_processed > 0:
            error_rate = metrics.error_count / metrics.pages_processed
            if error_rate > self._recycle_error_rate:
                return True
        
        return False
    
    async def _recycle_context(self, ctx_id: str, reason: str):
        """Recycle a specific context."""
        context = self._contexts.pop(ctx_id, None)
        metrics = self._context_metrics.pop(ctx_id, None)
        
        # Save cookies before closing
        if context:
            await self._save_context_cookies(ctx_id, context)
            try:
                await context.close()
            except Exception as e:
                self.logger.warning("Error closing context", ctx_id=ctx_id[:8], error=str(e))
        
        # Remove cookie storage
        self._context_cookies.pop(ctx_id, None)
        
        recycle_events = await self._get_recycle_events()
        if recycle_events:
            await recycle_events.labels(engine=self.engine_name, reason=reason).inc()
        self.logger.debug("Recycled context", ctx_id=ctx_id[:8], reason=reason)

    async def _save_context_cookies(self, ctx_id: str, context: PlaywrightBrowserContext):
        """Save cookies from a browser context."""
        try:
            cookies = await context.cookies()
            cookie_list = []
            for c in cookies:
                cookie_list.append(CookieData(
                    name=c["name"],
                    value=c["value"],
                    domain=c["domain"],
                    path=c.get("path", "/"),
                    expires=c.get("expires"),
                    secure=c.get("secure", False),
                    http_only=c.get("httpOnly", False),
                    same_site=c.get("sameSite", "Lax"),
                ))
            
            # Extract domain from first cookie or use empty
            domain = ""
            if cookie_list:
                domain = cookie_list[0].domain.lstrip(".")
            
            self._context_cookies[ctx_id] = ContextCookies(
                context_id=ctx_id,
                cookies=cookie_list,
                last_saved=time.time(),
                domain=domain,
            )
            
            # Also persist to external storage if available
            if self._cookie_storage and cookie_list:
                try:
                    await self._cookie_storage.set_cookies(ctx_id, [c.to_dict() for c in cookie_list])
                except Exception as e:
                    self.logger.warning("Failed to persist cookies to storage", error=str(e))
                    
        except Exception as e:
            self.logger.warning("Failed to save context cookies", ctx_id=ctx_id[:8], error=str(e))

    async def _restore_context_cookies(self, ctx_id: str, context: PlaywrightBrowserContext):
        """Restore cookies to a browser context."""
        try:
            # Try to get cookies from memory first
            context_cookies = self._context_cookies.get(ctx_id)
            
            # If not in memory, try external storage
            if not context_cookies and self._cookie_storage:
                try:
                    cookies_data = await self._cookie_storage.get_cookies(ctx_id)
                    if cookies_data:
                        cookie_list = [CookieData.from_dict(c) for c in cookies_data]
                        context_cookies = ContextCookies(
                            context_id=ctx_id,
                            cookies=cookie_list,
                            last_saved=time.time(),
                        )
                except Exception:
                    pass
            
            if context_cookies and context_cookies.cookies:
                pw_cookies = []
                for c in context_cookies.cookies:
                    if not c.is_expired():
                        pw_cookies.append({
                            "name": c.name,
                            "value": c.value,
                            "domain": c.domain,
                            "path": c.path,
                            "secure": c.secure,
                            "httpOnly": c.http_only,
                            "sameSite": c.same_site,
                        })
                        if c.expires:
                            pw_cookies[-1]["expires"] = c.expires
                
                if pw_cookies:
                    await context.add_cookies(pw_cookies)
                    self.logger.debug("Restored cookies to context", ctx_id=ctx_id[:8], count=len(pw_cookies))
                    
        except Exception as e:
            self.logger.warning("Failed to restore context cookies", ctx_id=ctx_id[:8], error=str(e))

    def set_cookie_storage(self, storage: Any):
        """Set external cookie storage (e.g., SessionManager)."""
        self._cookie_storage = storage
    
    async def _recycle_one_idle(self, reason: str):
        """Recycle one idle context."""
        if self._idle_queue.empty():
            return
        
        try:
            context = self._idle_queue.get_nowait()
            ctx_id = str(id(context))
            if ctx_id in self._contexts:
                await self._recycle_context(ctx_id, reason)
        except asyncio.QueueEmpty:
            pass
    
    async def _maybe_scale_down(self):
        """Scale down idle contexts when memory pressure or high idle ratio."""
        if not self._adaptive_enabled:
            return
        
        async with self._context_lock:
            if len(self._contexts) <= self._pool_min:
                return
            
            idle_count = self._idle_queue.qsize()
            total_count = len(self._contexts)
            
            if total_count == 0:
                return
            
            idle_ratio = idle_count / total_count
            current_memory = await self._get_current_memory_mb()
            memory_pressure = current_memory > self._available_for_browser * 0.8
            
            if idle_ratio > self._scale_down_idle_ratio or memory_pressure:
                await self._recycle_one_idle("scale_down")
                scale_events = await self._get_scale_events()
                if scale_events:
                    await scale_events.labels(engine=self.engine_name, direction="down").inc()
                self._adjust_idle_timeout(increase=True)
    
    async def _maybe_scale_up(self):
        """Scale up when queue builds up."""
        if not self._adaptive_enabled:
            return
        
        idle_count = self._idle_queue.qsize()
        
        if idle_count > self._scale_up_queue_threshold:
            async with self._context_lock:
                if len(self._contexts) < self._pool_max:
                    await self._create_new_context()
                    scale_events = await self._get_scale_events()
                    if scale_events:
                        await scale_events.labels(engine=self.engine_name, direction="up").inc()
                    self._adjust_idle_timeout(increase=False)
    
    def _adjust_idle_timeout(self, increase: bool):
        """Dynamically adjust idle timeout based on scaling."""
        if increase:
            self._current_idle_timeout = min(
                int(self._current_idle_timeout * 1.5),
                self._max_idle_timeout
            )
        else:
            self._current_idle_timeout = max(
                int(self._current_idle_timeout * 0.8),
                self._min_idle_timeout
            )
    
    async def _get_current_memory_mb(self) -> float:
        """Get current process memory in MB."""
        if PSUTIL_AVAILABLE:
            try:
                process = psutil.Process()
                return process.memory_info().rss / (1024 * 1024)
            except Exception:
                pass
        return 0.0
    
    async def _update_context_memory(self, ctx_id: str):
        """Update memory usage for a context."""
        if not PSUTIL_AVAILABLE:
            return
        
        try:
            process = psutil.Process()
            mem_mb = process.memory_info().rss / (1024 * 1024)
            if ctx_id in self._context_metrics:
                self._context_metrics[ctx_id].memory_mb = mem_mb
        except Exception:
            pass
    
    async def _recycle_loop(self):
        """Background task to recycle idle contexts."""
        while self._running:
            try:
                await asyncio.sleep(30)
                
                if not self._running:
                    break
                
                current_time = time.time()
                timeout_ms = self._current_idle_timeout
                
                async with self._context_lock:
                    to_recycle = []
                    
                    # Only recycle contexts that are in the idle queue
                    idle_ctx_ids = set()
                    temp_queue = []
                    while not self._idle_queue.empty():
                        try:
                            ctx = self._idle_queue.get_nowait()
                            idle_ctx_ids.add(str(id(ctx)))
                            temp_queue.append(ctx)
                        except asyncio.QueueEmpty:
                            break
                    
                    # Put them back
                    for ctx in temp_queue:
                        await self._idle_queue.put(ctx)
                    
                    # Check idle contexts for timeout
                    for ctx_id, metrics in list(self._context_metrics.items()):
                        if ctx_id in idle_ctx_ids:
                            idle_ms = (current_time - metrics.last_used) * 1000
                            if idle_ms > timeout_ms and len(self._contexts) > self._pool_min:
                                to_recycle.append(ctx_id)
                    
                    for ctx_id in to_recycle:
                        context = self._contexts.pop(ctx_id, None)
                        if context:
                            try:
                                await context.close()
                            except Exception:
                                pass
                            self._context_metrics.pop(ctx_id, None)
                            recycle_events = await self._get_recycle_events()
                            if recycle_events:
                                await recycle_events.labels(engine=self.engine_name, reason="idle_timeout").inc()
                            self.logger.debug("Recycled idle context", ctx_id=ctx_id[:8])
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in recycle loop", error=str(e))
    
    async def _monitor_loop(self):
        """Background monitoring loop for metrics."""
        while self._running:
            try:
                await asyncio.sleep(60)
                
                if not self._running:
                    break
                
                # Update metrics
                current_memory = await self._get_current_memory_mb()
                pool_size = len(self._contexts)
                idle_count = self._idle_queue.qsize()
                
                self.logger.debug(
                    "Pool status",
                    pool_size=pool_size,
                    idle_count=idle_count,
                    memory_mb=round(current_memory, 1),
                    idle_timeout_ms=self._current_idle_timeout,
                )
                
                # Update Prometheus
                self._metrics.record_request(
                    self.engine_name, True, 0  # Just for metric updates
                )
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error("Error in monitor loop", error=str(e))
    
    async def get_metrics(self) -> Dict[str, Any]:
        """Get pool metrics for monitoring."""
        current_memory = await self._get_current_memory_mb()
        
        return {
            "pool_size": len(self._contexts),
            "idle_count": self._idle_queue.qsize(),
            "memory_mb": round(current_memory, 1),
            "budget_mb": self._available_for_browser,
            "utilization_pct": round(current_memory / max(1, self._available_for_browser) * 100, 1),
            "idle_timeout_ms": self._current_idle_timeout,
            "adaptive_enabled": self._adaptive_enabled,
            "contexts": {
                ctx_id: {
                    "pages_processed": metrics.pages_processed,
                    "memory_mb": round(metrics.memory_mb, 1),
                    "error_count": metrics.error_count,
                    "age_seconds": round(time.time() - metrics.created_at, 1),
                }
                for ctx_id, metrics in self._context_metrics.items()
            }
        }
    
    def record_error(self, context: PlaywrightBrowserContext):
        """Record an error for a context."""
        ctx_id = str(id(context))
        if ctx_id in self._context_metrics:
            self._context_metrics[ctx_id].error_count += 1
    
    # Prometheus metrics helpers
    _scale_events = None
    _recycle_events = None
    _metrics_collector = None
    _scale_events_lock = asyncio.Lock()
    _recycle_events_lock = asyncio.Lock()
    
    async def _get_recycle_events(self):
        if self._recycle_events is None:
            async with self._recycle_events_lock:
                if self._recycle_events is None:
                    from ..utils.observability import get_metrics_collector
                    collector = get_metrics_collector(self.engine_name)
                    if collector:
                        self._recycle_events = Counter(
                            "browser_pool_recycle_events_total",
                            "Context recycle events",
                            ["engine", "reason"],
                            registry=collector.get_registry()
                        )
        return self._recycle_events
    
    async def _get_scale_events(self):
        if self._scale_events is None:
            async with self._scale_events_lock:
                if self._scale_events is None:
                    from ..utils.observability import get_metrics_collector
                    collector = get_metrics_collector(self.engine_name)
                    if collector:
                        self._scale_events = Counter(
                            "browser_pool_scale_events_total",
                            "Pool scale events",
                            ["engine", "direction"],
                            registry=collector.get_registry()
                        )
        return self._scale_events
    
    async def _get_metrics_collector(self):
        if self._metrics_collector is None:
            from ..utils.observability import get_metrics_collector
            self._metrics_collector = get_metrics_collector(self.engine_name)
        return self._metrics_collector


def create_adaptive_pool(
    config: BrowserEngineConfig,
    create_context_fn: Callable[[Dict[str, Any]], Any],
    engine_name: str = "browser",
) -> AdaptiveBrowserPool:
    """Factory function to create adaptive browser pool."""
    return AdaptiveBrowserPool(config, create_context_fn, engine_name)