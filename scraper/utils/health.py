from __future__ import annotations

import asyncio
import signal
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set, Awaitable
from enum import Enum
import asyncio
import logging

from ..utils.observability import get_logger

logger = get_logger("health")


class HealthStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class HealthCheckResult:
    name: str
    status: HealthStatus
    message: str = ""
    latency_ms: float = 0.0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    details: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status.value,
            "message": self.message,
            "latency_ms": self.latency_ms,
            "timestamp": self.timestamp.isoformat(),
            "details": self.details,
        }


@dataclass
class HealthCheck:
    name: str
    check_fn: Callable[[], Awaitable[HealthCheckResult]]
    timeout: float = 5.0
    critical: bool = True
    interval: float = 30.0
    tags: List[str] = field(default_factory=list)


class HealthChecker:
    """Manages health checks for the application."""
    
    def __init__(self):
        self._checks: Dict[str, HealthCheck] = {}
        self._results: Dict[str, HealthCheckResult] = {}
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()
    
    def register(self, check: HealthCheck) -> None:
        """Register a health check."""
        self._checks[check.name] = check
    
    def unregister(self, name: str) -> None:
        """Unregister a health check."""
        self._checks.pop(name, None)
        self._results.pop(name, None)
    
    async def run_check(self, name: str) -> HealthCheckResult:
        """Run a single health check."""
        check = self._checks.get(name)
        if not check:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNKNOWN,
                message=f"Check '{name}' not found",
            )
        
        start = time.time()
        try:
            result = await asyncio.wait_for(check.check_fn(), timeout=check.timeout)
            result.latency_ms = (time.time() - start) * 1000
            return result
        except asyncio.TimeoutError:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check timed out after {check.timeout}s",
                latency_ms=(time.time() - start) * 1000,
            )
        except Exception as e:
            return HealthCheckResult(
                name=name,
                status=HealthStatus.UNHEALTHY,
                message=f"Check failed: {str(e)}",
                latency_ms=(time.time() - start) * 1000,
            )
    
    async def run_all(self) -> Dict[str, HealthCheckResult]:
        """Run all registered health checks."""
        results = {}
        async with self._lock:
            tasks = {
                name: self.run_check(name) 
                for name in self._checks
            }
            results = await asyncio.gather(*tasks.values(), return_exceptions=True)
            
            for i, (name, _) in enumerate(self._checks.items()):
                result = results[i]
                if isinstance(result, Exception):
                    self._results[name] = HealthCheckResult(
                        name=name,
                        status=HealthStatus.UNHEALTHY,
                        message=f"Check failed with exception: {result}",
                    )
                else:
                    self._results[name] = result
        
        return self._results
    
    def get_overall_status(self) -> HealthStatus:
        """Get overall system health status."""
        if not self._results:
            return HealthStatus.UNKNOWN
        
        has_unhealthy = any(r.status == HealthStatus.UNHEALTHY for r in self._results.values())
        has_degraded = any(r.status == HealthStatus.DEGRADED for r in self._results.values())
        
        if has_unhealthy:
            return HealthStatus.UNHEALTHY
        elif has_degraded:
            return HealthStatus.DEGRADED
        return HealthStatus.HEALTHY
    
    def get_results(self) -> Dict[str, HealthCheckResult]:
        """Get latest health check results."""
        return self._results.copy()
    
    async def start_periodic(self, interval: float = 30.0) -> None:
        """Start periodic health checks."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._periodic_check(interval))
    
    async def stop_periodic(self) -> None:
        """Stop periodic health checks."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
    
    async def _periodic_check(self, interval: float) -> None:
        while True:
            try:
                await self.run_all()
            except Exception as e:
                logger.error("Periodic health check failed", error=str(e))
            await asyncio.sleep(30)
    
    def get_summary(self) -> Dict[str, Any]:
        """Get health summary."""
        overall = self.get_overall_status()
        results = {name: r.to_dict() for name, r in self._results.items()}
        return {
            "status": overall.value,
            "checks": results,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# Default health checks
async def check_database(config: dict) -> HealthCheckResult:
    """Check database connectivity."""
    start = time.time()
    try:
        # This would be implemented with actual DB connection
        # await db.execute("SELECT 1")
        return HealthCheckResult(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Database connection OK",
            latency_ms=(time.time() - time.time()) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database check failed: {e}",
            latency_ms=(time.time() - time.time()) * 1000,
        )


async def check_redis(url: str) -> HealthCheckResult:
    """Check Redis connectivity."""
    import redis.asyncio as redis
    start = time.time()
    try:
        redis_client = redis.from_url(url)
        await redis_client.ping()
        await redis_client.close()
        return HealthCheckResult(
            name="redis",
            status=HealthStatus.HEALTHY,
            message="Redis connection OK",
            latency_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="redis",
            status=HealthStatus.UNHEALTHY,
            message=f"Redis check failed: {e}",
            latency_ms=(time.time() - start) * 1000,
        )


async def check_rabbitmq(url: str) -> HealthCheckResult:
    """Check RabbitMQ connectivity."""
    import aio_pika
    start = time.time()
    try:
        connection = await aio_pika.connect_robust(url)
        await connection.close()
        return HealthCheckResult(
            name="rabbitmq",
            status=HealthStatus.HEALTHY,
            message="RabbitMQ connection OK",
            latency_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="rabbitmq",
            status=HealthStatus.UNHEALTHY,
            message=f"RabbitMQ check failed: {e}",
            latency_ms=(time.time() - start) * 1000,
        )


async def check_disk_space(path: str = "/", threshold: float = 0.9) -> HealthCheckResult:
    """Check disk space."""
    import shutil
    start = time.time()
    try:
        total, used, free = shutil.disk_usage(path)
        usage = used / total
        if usage > threshold:
            return HealthCheckResult(
                name="disk_space",
                status=HealthStatus.UNHEALTHY,
                message=f"Disk usage {usage:.1%} exceeds threshold {threshold:.0%}",
                latency_ms=(time.time() - start) * 1000,
            )
        return HealthCheckResult(
            name="disk_space",
            status=HealthStatus.HEALTHY,
            message=f"Disk usage {usage:.1%}",
            latency_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="disk_space",
            status=HealthStatus.UNHEALTHY,
            message=f"Disk check failed: {e}",
            latency_ms=(time.time() - start) * 1000,
        )


async def check_memory(threshold: float = 0.9) -> HealthCheckResult:
    """Check memory usage."""
    import psutil
    start = time.time()
    try:
        mem = psutil.virtual_memory()
        if mem.percent > threshold * 100:
            return HealthCheckResult(
                name="memory",
                status=HealthStatus.UNHEALTHY,
                message=f"Memory usage {mem.percent:.1f}% exceeds threshold {threshold:.0%}",
                latency_ms=(time.time() - start) * 1000,
            )
        return HealthCheckResult(
            name="memory",
            status=HealthStatus.HEALTHY,
            message=f"Memory usage {mem.percent:.1f}%",
            latency_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="memory",
            status=HealthStatus.UNHEALTHY,
            message=f"Memory check failed: {e}",
            latency_ms=(time.time() - start) * 1000,
        )


async def check_cpu(threshold: float = 0.9) -> HealthCheckResult:
    """Check CPU usage."""
    import psutil
    start = time.time()
    try:
        cpu_percent = psutil.cpu_percent(interval=1)
        if cpu_percent > threshold * 100:
            return HealthCheckResult(
                name="cpu",
                status=HealthStatus.UNHEALTHY,
                message=f"CPU usage {cpu_percent:.1f}% exceeds threshold {threshold:.0%}",
                latency_ms=(time.time() - start) * 1000,
            )
        return HealthCheckResult(
            name="cpu",
            status=HealthStatus.HEALTHY,
            message=f"CPU usage {cpu_percent:.1f}%",
            latency_ms=(time.time() - start) * 1000,
        )
    except Exception as e:
        return HealthCheckResult(
            name="cpu",
            status=HealthStatus.UNHEALTHY,
            message=f"CPU check failed: {e}",
            latency_ms=(time.time() - start) * 1000,
        )


class GracefulShutdown:
    """Manages graceful shutdown of the application."""
    
    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self._shutdown_event = asyncio.Event()
        self._shutdown_started = False
        self._shutdown_tasks: List[Callable[[], Awaitable[None]]] = []
        self._shutdown_started_at: Optional[float] = None
        self._original_handlers: Dict[int, Callable] = {}
    
    def register_shutdown_task(self, task: Callable[[], Awaitable[None]]) -> None:
        """Register a task to run during shutdown."""
        self._shutdown_tasks.append(task)
    
    def remove_shutdown_task(self, task: Callable[[], Awaitable[None]]) -> None:
        """Remove a shutdown task."""
        if task in self._shutdown_tasks:
            self._shutdown_tasks.remove(task)
    
    def _signal_handler(self, signum: int, frame) -> None:
        """Handle shutdown signals."""
        logger.info(f"Received signal {signum}, initiating graceful shutdown")
        asyncio.create_task(self.shutdown())
    
    def install_signal_handlers(self) -> None:
        """Install signal handlers for graceful shutdown."""
        for sig in (signal.SIGTERM, signal.SIGINT):
            self._original_handlers[sig] = signal.signal(sig, self._signal_handler)
    
    def restore_signal_handlers(self) -> None:
        """Restore original signal handlers."""
        for sig, handler in self._original_handlers.items():
            signal.signal(sig, handler)
    
    async def shutdown(self, timeout: Optional[float] = None) -> None:
        """Perform graceful shutdown."""
        if self._shutdown_started:
            return
        
        self._shutdown_started = True
        self._shutdown_started_at = time.time()
        timeout = timeout or self.timeout
        
        logger.info("Starting graceful shutdown", timeout=timeout)
        
        # Run shutdown tasks with timeout
        tasks = [asyncio.create_task(task()) for task in self._shutdown_tasks]
        
        if tasks:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*tasks, return_exceptions=True),
                    timeout=timeout
                )
            except asyncio.TimeoutError:
                logger.warning("Shutdown tasks timed out")
        
        self._shutdown_event.set()
        logger.info("Graceful shutdown completed")
    
    def is_shutting_down(self) -> bool:
        return self._shutdown_started
    
    def wait_for_shutdown(self, timeout: Optional[float] = None) -> asyncio.Event:
        """Wait for shutdown to complete."""
        return self._shutdown_event.wait()
    
    def get_shutdown_info(self) -> Dict[str, Any]:
        """Get shutdown status info."""
        return {
            "shutting_down": self._shutdown_started,
            "started_at": self._shutdown_started_at,
            "elapsed": time.time() - self._shutdown_started_at if self._shutdown_started_at else 0,
            "pending_tasks": len(self._shutdown_tasks),
        }


@asynccontextmanager
async def lifespan(app_state: Dict[str, Any] = None):
    """Application lifespan manager with health checks and graceful shutdown."""
    health_checker = HealthChecker()
    shutdown_manager = GracefulShutdown()
    
    # Register default health checks
    health_checker.register(HealthCheck(
        name="redis",
        check_fn=lambda: check_redis("redis://localhost:6379"),
        critical=True,
    ))
    health_checker.register(HealthCheck(
        name="disk_space",
        check_fn=lambda: check_disk_space("/"),
        critical=True,
    ))
    health_checker.register(HealthCheck(
        name="memory",
        check_fn=lambda: check_memory(0.9),
        critical=True,
    ))
    
    # Install signal handlers
    shutdown_manager = GracefulShutdown()
    shutdown_manager.install_signal_handlers()
    
    try:
        # Start health checks
        await health_checker.start_periodic(30.0)
        
        # Yield control to application
        if app_state:
            app_state["health_checker"] = health_checker
            app_state["shutdown_manager"] = shutdown_manager
        yield app_state
    finally:
        # Cleanup
        await health_checker.stop_periodic()
        shutdown_manager.restore_signal_handlers()
        if shutdown_manager.is_shutting_down():
            await shutdown_manager.shutdown()


# Health check decorators
def health_check(
    name: str,
    timeout: float = 5.0,
    critical: bool = True,
    interval: float = 30.0,
    tags: List[str] = None,
):
    """Decorator to register a health check."""
    def decorator(func: Callable[[], Awaitable[HealthCheckResult]]) -> Callable:
        check = HealthCheck(
            name=name,
            check_fn=func,
            timeout=timeout,
            critical=critical,
            interval=interval,
            tags=tags or [],
        )
        # Register with global health checker (would need global instance)
        return func
    return decorator


# FastAPI/Starlette integration
def create_health_endpoint(health_checker: HealthChecker):
    """Create FastAPI/Starlette health check endpoints."""
    from fastapi import FastAPI, Response
    from fastapi.responses import JSONResponse
    
    async def health_live():
        """Liveness probe - is the service running?"""
        return {"status": "alive"}
    
    async def health_ready():
        """Readiness probe - is the service ready to serve traffic?"""
        results = await health_checker.run_all()
        overall = health_checker.get_overall_status()
        
        status_code = 200
        if health_checker.get_overall_status() == HealthStatus.UNHEALTHY:
            status_code = 503
        elif health_checker.get_overall_status() == HealthStatus.DEGRADED:
            status_code = 200  # Still serving but degraded
        
        return JSONResponse(
            content=health_checker.get_summary(),
            status_code=status_code,
        )
    
    async def health_check(name: str):
        """Run a specific health check."""
        result = await health_checker.run_check(name)
        return JSONResponse(content=result.to_dict())
    
    return {
        "live": health_live,
        "ready": health_ready,
        "check": health_check,
    }