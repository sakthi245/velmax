from __future__ import annotations

import asyncio
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from prometheus_client import Counter, Gauge, Histogram, CollectorRegistry, start_http_server
from prometheus_client.core import CollectorRegistry as CoreCollectorRegistry

from ..config import WorkerConfig


@dataclass
class WorkerMetricsConfig:
    port: int = 9090
    prefix: str = "scraper_worker"
    enable_default_metrics: bool = True
    buckets_latency: List[float] = field(default_factory=lambda: [
        0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, 300.0
    ])
    buckets_queue_depth: List[float] = field(default_factory=lambda: [
        0, 1, 5, 10, 25, 50, 100, 250, 500, 1000
    ])


class WorkerMetrics:
    def __init__(self, worker_id: str, config: WorkerMetricsConfig):
        self.worker_id = worker_id
        self.config = config
        self.registry = CollectorRegistry()
        
        prefix = config.prefix
        
        # Task metrics
        self.tasks_total = Counter(
            f"{prefix}_tasks_total",
            "Total number of tasks processed",
            ["worker_id", "status", "engine", "domain"],
            registry=self.registry,
        )
        
        self.task_duration = Histogram(
            f"{prefix}_task_duration_seconds",
            "Task processing duration in seconds",
            ["worker_id", "engine", "domain"],
            buckets=config.buckets_latency,
            registry=self.registry,
        )
        
        self.task_retries = Counter(
            f"{prefix}_task_retries_total",
            "Total number of task retries",
            ["worker_id", "engine", "domain"],
            registry=self.registry,
        )
        
        self.task_dlq = Counter(
            f"{prefix}_task_dlq_total",
            "Total number of tasks sent to DLQ",
            ["worker_id", "engine", "domain"],
            registry=self.registry,
        )

        # Queue metrics
        self.queue_depth = Gauge(
            f"{prefix}_queue_depth",
            "Current queue depth",
            ["worker_id", "queue_type"],
            registry=self.registry,
        )
        
        self.queue_wait_time = Histogram(
            f"{prefix}_queue_wait_seconds",
            "Time tasks spend waiting in queue",
            ["worker_id", "queue_type"],
            buckets=config.buckets_latency,
            registry=self.registry,
        )

        # Rate limiting metrics
        self.rate_limit_wait = Histogram(
            f"{prefix}_rate_limit_wait_seconds",
            "Time spent waiting for rate limits",
            ["worker_id", "domain"],
            buckets=config.buckets_latency,
            registry=self.registry,
        )
        
        self.rate_limit_tokens = Gauge(
            f"{prefix}_rate_limit_tokens",
            "Available tokens in rate limiter bucket",
            ["worker_id", "domain"],
            registry=self.registry,
        )

        # Browser pool metrics
        self.browser_pool_size = Gauge(
            f"{prefix}_browser_pool_size",
            "Current browser pool size",
            ["worker_id"],
            registry=self.registry,
        )
        
        self.browser_pool_active = Gauge(
            f"{prefix}_browser_pool_active",
            "Active browser contexts",
            ["worker_id"],
            registry=self.registry,
        )

        # Worker health metrics
        self.worker_health = Gauge(
            f"{prefix}_health",
            "Worker health status (1=healthy, 0=unhealthy)",
            ["worker_id"],
            registry=self.registry,
        )
        
        self.worker_uptime = Gauge(
            f"{prefix}_uptime_seconds",
            "Worker uptime in seconds",
            ["worker_id"],
            registry=self.registry,
        )

        self.worker_memory = Gauge(
            f"{prefix}_memory_bytes",
            "Worker memory usage in bytes",
            ["worker_id"],
            registry=self.registry,
        )

        self.worker_cpu = Gauge(
            f"{prefix}_cpu_percent",
            "Worker CPU usage percentage",
            ["worker_id"],
            registry=self.registry,
        )

        # Task outcome metrics
        self.task_errors = Counter(
            f"{prefix}_task_errors_total",
            "Total number of task errors by type",
            ["worker_id", "error_type", "domain"],
            registry=self.registry,
        )

        # Custom metrics storage
        self._start_time = time.time()
        self._worker_id = ""
        
        # Custom gauges for dynamic metrics
        self._custom_gauges: Dict[str, Gauge] = {}
        self._custom_counters: Dict[str, Counter] = {}

    def set_worker_id(self, worker_id: str) -> None:
        self._worker_id = worker_id

    def record_task_start(
        self,
        domain: str,
        engine: str = "managed",
    ) -> Dict[str, Any]:
        """Record task start and return context for recording completion."""
        return {
            "start_time": time.time(),
            "domain": domain,
            "engine": engine,
        }

    def record_task_completion(
        self,
        context: Dict[str, Any],
        success: bool,
        engine: str = "managed",
        error_type: Optional[str] = None,
    ) -> None:
        """Record task completion with metrics."""
        duration = time.time() - context["start_time"]
        domain = context["domain"]
        engine = context.get("engine", engine)
        
        status = "success" if success else "failed"
        
        self.tasks_total.labels(
            worker_id=self._worker_id,
            status=status,
            engine=engine,
            domain=domain,
        ).inc()
        
        self.task_duration.labels(
            worker_id=self._worker_id,
            engine=engine,
            domain=domain,
        ).observe(duration)
        
        if not success and error_type:
            self.task_errors.labels(
                worker_id=self._worker_id,
                error_type=error_type,
                domain=domain,
            ).inc()

    def record_retry(self, domain: str, engine: str = "managed") -> None:
        self.task_retries.labels(
            worker_id=self._worker_id,
            engine=engine,
            domain=domain,
        ).inc()

    def record_dlq(self, domain: str, engine: str = "managed") -> None:
        self.task_dlq.labels(
            worker_id=self._worker_id,
            engine=engine,
            domain=domain,
        ).inc()

    def set_queue_depth(self, queue_type: str, depth: int) -> None:
        self.queue_depth.labels(
            worker_id=self._worker_id,
            queue_type=queue_type,
        ).set(depth)

    def record_queue_wait(self, queue_type: str, wait_time: float) -> None:
        self.queue_wait_time.labels(
            worker_id=self._worker_id,
            queue_type=queue_type,
        ).observe(wait_time)

    def record_rate_limit_wait(self, domain: str, wait_time: float) -> None:
        self.rate_limit_wait.labels(
            worker_id=self._worker_id,
            domain=domain,
        ).observe(wait_time)

    def set_rate_limit_tokens(self, domain: str, tokens: float) -> None:
        self.rate_limit_tokens.labels(
            worker_id=self._worker_id,
            domain=domain,
        ).set(tokens)

    def set_browser_pool_size(self, size: int) -> None:
        self.browser_pool_size.labels(worker_id=self._worker_id).set(size)

    def set_browser_pool_active(self, active: int) -> None:
        self.browser_pool_active.labels(worker_id=self._worker_id).set(active)

    def set_health(self, healthy: bool) -> None:
        self.worker_health.labels(worker_id=self._worker_id).set(1 if healthy else 0)

    def update_uptime(self) -> None:
        self.worker_uptime.labels(worker_id=self._worker_id).set(time.time() - self._start_time)

    def update_system_metrics(self, memory_bytes: int, cpu_percent: float) -> None:
        self.worker_memory.labels(worker_id=self._worker_id).set(memory_bytes)
        self.worker_cpu.labels(worker_id=self._worker_id).set(cpu_percent)

    def get_or_create_gauge(self, name: str, description: str, labels: List[str] = None) -> Gauge:
        """Get or create a custom gauge."""
        if name not in self._custom_gauges:
            self._custom_gauges[name] = Gauge(
                f"{self.config.prefix}_{name}",
                description,
                labels or ["worker_id"],
                registry=self.registry,
            )
        return self._custom_gauges[name]

    def get_or_create_counter(self, name: str, description: str, labels: List[str] = None) -> Counter:
        """Get or create a custom counter."""
        if name not in self._custom_counters:
            self._custom_counters[name] = Counter(
                f"{self.config.prefix}_{name}",
                description,
                labels or ["worker_id"],
                registry=self.registry,
            )
        return self._custom_counters[name]


class MetricsServer:
    def __init__(self, metrics: WorkerMetrics, port: int):
        self.metrics = metrics
        self.port = port
        self._server_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        
        self._running = True
        # Start Prometheus HTTP server in background thread
        import threading
        def run_server():
            start_http_server(self.port, registry=self.metrics.registry)
        
        thread = threading.Thread(target=run_server, daemon=True)
        thread.start()
        self._server_task = asyncio.create_task(self._update_loop())
        print(f"Metrics server started on port {self.port}")

    async def stop(self) -> None:
        self._running = False
        if self._server_task:
            self._server_task.cancel()
            try:
                await self._server_task
            except asyncio.CancelledError:
                pass

    async def _update_loop(self) -> None:
        while self._running:
            try:
                self.metrics.update_uptime()
            except Exception:
                pass
            await asyncio.sleep(10)


@asynccontextmanager
async def create_metrics_server(
    worker_id: str,
    config: Optional[WorkerMetricsConfig] = None,
) -> AsyncIterator[tuple[WorkerMetrics, MetricsServer]]:
    config = config or WorkerMetricsConfig()
    metrics = WorkerMetrics(worker_id, config)
    metrics.set_worker_id(worker_id)
    
    server = MetricsServer(metrics, config.port)
    await server.start()
    
    try:
        yield metrics, server
    finally:
        await server.stop()


async def create_metrics_server_sync(
    worker_id: str,
    config: Optional[WorkerMetricsConfig] = None,
) -> tuple[WorkerMetrics, MetricsServer]:
    """Synchronous version that returns metrics and server directly (for non-context-manager usage)."""
    config = config or WorkerMetricsConfig()
    metrics = WorkerMetrics(worker_id, config)
    metrics.set_worker_id(worker_id)
    
    server = MetricsServer(metrics, config.port)
    await server.start()
    
    return metrics, server