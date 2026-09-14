from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Union
from functools import wraps
from collections import defaultdict

import structlog
from structlog.typing import FilteringBoundLogger

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

try:
    from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, start_http_server
    PROMETHEUS_AVAILABLE = True
except ImportError:
    PROMETHEUS_AVAILABLE = False


@dataclass
class ObservabilityConfig:
    enabled: bool = True
    log_level: str = "INFO"
    structured_logging: bool = True
    log_format: str = "json"
    metrics_enabled: bool = True
    metrics_port: int = 9090
    metrics_path: str = "/metrics"
    tracing_enabled: bool = False
    tracing_endpoint: Optional[str] = None
    tracing_sample_rate: float = 0.1
    screenshot_on_error: bool = True
    har_on_error: bool = False
    alert_on_error_rate: float = 0.1
    alert_on_latency_p99: float = 30.0
    service_name: str = "hybrid-scraper"
    log_dir: Optional[Path] = None


class MetricsCollector:
    def __init__(self, engine_name: str, config: ObservabilityConfig):
        self.engine_name = engine_name
        self.config = config
        self._registry = CollectorRegistry()
        self._initialized = False
        self._success_counts: Dict[str, int] = {}
        self._failure_counts: Dict[str, int] = {}

        if config.metrics_enabled and PROMETHEUS_AVAILABLE:
            self._init_metrics()

    def _init_metrics(self):
        self.requests_total = Counter(
            "scraper_requests_total",
            "Total scrape requests",
            ["engine", "status", "domain"],
            registry=self._registry,
        )
        self.request_latency = Histogram(
            "scraper_request_latency_seconds",
            "Scrape request latency in seconds",
            ["engine", "domain"],
            registry=self._registry,
            buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120],
        )
        self.request_size = Histogram(
            "scraper_request_size_bytes",
            "Request response size in bytes",
            ["engine", "domain"],
            registry=self._registry,
        )
        self.active_requests = Gauge(
            "scraper_active_requests",
            "Currently active requests",
            ["engine"],
            registry=self._registry,
        )
        self.circuit_breaker_state = Gauge(
            "scraper_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=half_open, 2=open)",
            ["engine"],
            registry=self._registry,
        )
        self.engine_health = Gauge(
            "scraper_engine_health",
            "Engine health (1=healthy, 0=unhealthy)",
            ["engine"],
            registry=self._registry,
        )
        self.fallback_triggered = Counter(
            "scraper_fallback_triggered_total",
            "Total fallback triggers",
            ["engine", "reason"],
            registry=self._registry,
        )
        self.script_generation = Counter(
            "scraper_script_generation_total",
            "Total script generations",
            ["engine", "status"],
            registry=self._registry,
        )
        self.script_generation_time = Histogram(
            "scraper_script_generation_seconds",
            "Script generation time in seconds",
            ["engine"],
            registry=self._registry,
        )
        self.cache_hits = Counter(
            "scraper_cache_hits_total",
            "Cache hits",
            ["engine", "cache_type"],
            registry=self._registry,
        )
        self.cache_misses = Counter(
            "scraper_cache_misses_total",
            "Cache misses",
            ["engine", "cache_type"],
            registry=self._registry,
        )
        self.quality_score = Histogram(
            "scraper_quality_score",
            "Result quality score",
            ["engine"],
            registry=self._registry,
            buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
        )
        self._initialized = True

    def record_request(
        self,
        engine: str,
        success: bool,
        latency_ms: int,
        domain: str = "unknown",
        size_bytes: int = 0,
    ):
        if not self._initialized:
            return
        status = "success" if success else "error"
        self.requests_total.labels(engine=engine, status=status, domain=domain).inc()
        self.request_latency.labels(engine=engine, domain=domain).observe(latency_ms / 1000.0)
        if size_bytes:
            self.request_size.labels(engine=engine, domain=domain).observe(size_bytes)
        
        # Track success/failure counts for success rate calculation
        if success:
            self._success_counts[engine] = self._success_counts.get(engine, 0) + 1
        else:
            self._failure_counts[engine] = self._failure_counts.get(engine, 0) + 1

    def record_active(self, engine: str, delta: int):
        if not self._initialized:
            return
        self.active_requests.labels(engine=engine).inc(delta)

    def record_circuit_breaker(self, engine: str, state: str):
        if not self._initialized:
            return
        state_map = {"closed": 0, "half_open": 1, "open": 2}
        self.circuit_breaker_state.labels(engine=engine).set(state_map.get(state, 0))

    def record_engine_health(self, engine: str, healthy: bool):
        if not self._initialized:
            return
        self.engine_health.labels(engine=engine).set(1 if healthy else 0)

    def record_fallback(self, engine: str, reason: str):
        if not self._initialized:
            return
        self.fallback_triggered.labels(engine=engine, reason=reason).inc()

    def record_script_generation(self, engine: str, success: bool, duration: float):
        if not self._initialized:
            return
        status = "success" if success else "failure"
        self.script_generation.labels(engine=engine, status=status).inc()
        self.script_generation_time.labels(engine=engine).observe(duration)

    def record_cache(self, engine: str, cache_type: str, hit: bool):
        if not self._initialized:
            return
        if hit:
            self.cache_hits.labels(engine=engine, cache_type=cache_type).inc()
        else:
            self.cache_misses.labels(engine=engine, cache_type=cache_type).inc()

    def record_quality(self, engine: str, score: float):
        if not self._initialized:
            return
        self.quality_score.labels(engine=engine).observe(score)

    def get_registry(self):
        return self._registry

    def get_success_rate(self, engine: str, category: str = "") -> float:
        """Get success rate for an engine."""
        successes = self._success_counts.get(engine, 0)
        failures = self._failure_counts.get(engine, 0)
        total = successes + failures
        if total == 0:
            return 0.5  # Default neutral rate
        return successes / total


class ScreenshotCapture:
    def __init__(self, config: ObservabilityConfig):
        self.config = config
        self.enabled = config.screenshot_on_error
        self.capture_dir = config.log_dir / "screenshots" if config.log_dir else Path("./logs/screenshots")
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, page: Any, name: str, metadata: Dict[str, Any] = None) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{name}_{timestamp}_{uuid.uuid4().hex[:8]}.png"
            filepath = self.capture_dir / filename

            if hasattr(page, "screenshot"):
                await page.screenshot(path=str(filepath), full_page=True)
            elif hasattr(page, "page") and hasattr(page.page, "screenshot"):
                await page.page.screenshot(path=str(filepath), full_page=True)

            meta_file = filepath.with_suffix(".json")
            meta_file.write_text(json.dumps({
                "name": name,
                "timestamp": timestamp,
                "metadata": metadata or {},
            }))

            return str(filepath)
        except Exception as e:
            logger = structlog.get_logger("screenshot")
            logger.warning("Failed to capture screenshot", error=str(e))
            return None


class HARCapturer:
    def __init__(self, config: ObservabilityConfig):
        self.config = config
        self.enabled = config.har_on_error
        self.capture_dir = config.log_dir / "har" if config.log_dir else Path("./logs/har")
        self.capture_dir.mkdir(parents=True, exist_ok=True)

    async def capture(self, page: Any, name: str, metadata: Dict[str, Any] = None) -> Optional[str]:
        if not self.enabled:
            return None
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{name}_{timestamp}_{uuid.uuid4().hex[:8]}.har"
            filepath = self.capture_dir / filename

            har_data = None
            if hasattr(page, "context") and hasattr(page.context, "har"):
                har_data = await page.context.har()
            elif hasattr(page, "page") and hasattr(page.page.context, "har"):
                har_data = await page.page.context.har()

            if har_data:
                import json
                filepath.write_text(json.dumps(har_data, indent=2))
                return str(filepath)
        except Exception as e:
            logger = structlog.get_logger("har")
            logger.warning("Failed to capture HAR", error=str(e))
        return None


_logger_cache: Dict[str, FilteringBoundLogger] = {}
_metrics_collectors: Dict[str, MetricsCollector] = {}
_tracer = None
_config: Optional[ObservabilityConfig] = None


def configure_observability(config: ObservabilityConfig) -> None:
    global _config, _tracer

    _config = config

    if config.log_dir:
        config.log_dir.mkdir(parents=True, exist_ok=True)

    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    processors = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        timestamper,
        structlog.processors.StackInfoRenderer(),
        structlog.dev.set_exc_info,
    ]

    if config.structured_logging:
        if config.log_format == "json":
            processors.append(structlog.processors.JSONRenderer())
        else:
            processors.append(structlog.processors.KeyValueRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, config.log_level)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    if config.tracing_enabled and OTEL_AVAILABLE:
        resource = Resource.create({SERVICE_NAME: config.service_name})
        provider = TracerProvider(resource=resource)
        if config.tracing_endpoint:
            exporter = OTLPSpanExporter(endpoint=config.tracing_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(config.service_name)

    if config.metrics_enabled and PROMETHEUS_AVAILABLE:
        try:
            start_http_server(config.metrics_port, registry=CollectorRegistry())
        except Exception:
            pass


def get_logger(name: str) -> FilteringBoundLogger:
    if name not in _logger_cache:
        _logger_cache[name] = structlog.get_logger(name)
    return _logger_cache[name]


def get_tracer(name: str):
    global _tracer
    if _tracer is None and _config and _config.tracing_enabled and OTEL_AVAILABLE:
        _tracer = trace.get_tracer(name)
    return _tracer


def get_metrics_collector(engine_name: str) -> MetricsCollector:
    if engine_name not in _metrics_collectors and _config:
        _metrics_collectors[engine_name] = MetricsCollector(engine_name, _config)
    return _metrics_collectors.get(engine_name)


def configure_log_levels(config: ObservabilityConfig) -> None:
    """Configure log levels for specific modules."""
    import logging
    
    # Default levels
    levels = {
        "scraper": logging.INFO,
        "scraper.engines": logging.INFO,
        "scraper.utils": logging.WARNING,
        "scraper.engines.browser_engine": logging.INFO,
        "scraper.engines.managed_engine": logging.INFO,
        "scraper.engines.http_engine": logging.INFO,
        "urllib3": logging.WARNING,
        "httpx": logging.WARNING,
        "aiohttp": logging.WARNING,
        "tenacity": logging.WARNING,
    }
    
    # Override with config if provided
    if hasattr(config, 'log_levels') and config.log_levels:
        levels.update(config.log_levels)
    
    for logger_name, level in levels.items():
        logging.getLogger(logger_name).setLevel(level)


def configure_log_sampling(config: ObservabilityConfig, sample_rate: float = 1.0) -> None:
    """Configure log sampling for high-volume loggers."""
    import logging
    import random
    
    original_log = logging.Logger._log
    
    def sampled_log(self, level, msg, *args, **kwargs):
        if level >= logging.WARNING or random.random() < sample_rate:
            return original_log(self, level, msg, *args, **kwargs)
    
    logging.Logger._log = sampled_log


def configure_json_formatter(config: ObservabilityConfig) -> None:
    """Configure JSON formatter with additional fields."""
    import structlog
    
    def add_timestamp(logger, method_name, event_dict):
        event_dict["timestamp"] = datetime.now(timezone.utc).isoformat()
        return event_dict
    
    def add_service_info(logger, method_name, event_dict):
        event_dict["service"] = "hybrid-scraper"
        event_dict["version"] = "1.0.0"
        return event_dict
    
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            add_timestamp,
            add_service_info,
            structlog.processors.JSONRenderer()
        ] if _config and _config.log_format == "json" else [
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.dev.ConsoleRenderer()
        ],
    )


@contextmanager
def trace_span(name: str, attributes: Dict[str, Any] = None):
    tracer = get_tracer(name)
    if tracer and _config and _config.tracing_enabled:
        with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
            yield span
    else:
        yield None


def traced(name: str = None, attributes: Dict[str, Any] = None):
    def decorator(func: Callable):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            span_name = name or f"{func.__module__}.{func.__qualname__}"
            with trace_span(span_name, attributes) as span:
                return await func(*args, **kwargs)

        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            span_name = name or f"{func.__module__}.{func.__qualname__}"
            with trace_span(span_name, attributes) as span:
                return func(*args, **kwargs)

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper
    return decorator


@dataclass
class RequestContext:
    request_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    engine: str = ""
    url: str = ""
    domain: str = ""
    start_time: float = field(default_factory=time.time)
    metadata: Dict[str, Any] = field(default_factory=dict)
    screenshots: List[str] = field(default_factory=list)
    har_files: List[str] = field(default_factory=list)

    def elapsed_ms(self) -> int:
        return int((time.time() - self.start_time) * 1000)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "engine": self.engine,
            "url": self.url,
            "domain": self.domain,
            "elapsed_ms": self.elapsed_ms(),
            "metadata": self.metadata,
            "screenshots": self.screenshots,
            "har_files": self.har_files,
        }


class RequestLogger:
    def __init__(self, context: RequestContext):
        self.context = context
        self.logger = get_logger(f"request.{context.engine}")

    def info(self, message: str, **kwargs):
        self.logger.info(message, **self._enrich(kwargs))

    def warning(self, message: str, **kwargs):
        self.logger.warning(message, **self._enrich(kwargs))

    def error(self, message: str, **kwargs):
        self.logger.error(message, **self._enrich(kwargs))

    def debug(self, message: str, **kwargs):
        self.logger.debug(message, **self._enrich(kwargs))

    def _enrich(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        return {**self.context.to_dict(), **kwargs}

    def log_request_start(self):
        self.info("request_started")

    def log_request_end(self, success: bool, error: str = None):
        if success:
            self.info("request_completed", success=True)
        else:
            self.error("request_failed", success=False, error=error)

    def log_fallback(self, from_engine: str, to_engine: str, reason: str):
        self.warning("fallback_triggered", from_engine=from_engine, to_engine=to_engine, reason=reason)

    def log_quality(self, score: float, details: Dict[str, Any] = None):
        self.info("quality_check", quality_score=score, details=details or {})


@contextmanager
def request_context(
    engine: str,
    url: str,
    domain: str = "",
    metadata: Dict[str, Any] = None,
):
    if not domain:
        from urllib.parse import urlparse
        domain = urlparse(url).netloc

    context = RequestContext(
        engine=engine,
        url=url,
        domain=domain,
        metadata=metadata or {},
    )
    logger = RequestLogger(context)

    logger.log_request_start()
    try:
        yield context
    except Exception as e:
        logger.log_request_end(False, str(e))
        raise
    else:
        logger.log_request_end(True)


class AlertManager:
    def __init__(self, config: ObservabilityConfig):
        self.config = config
        self._error_counts: Dict[str, int] = {}
        self._total_requests: Dict[str, int] = {}
        self._latencies: Dict[str, List[float]] = {}

    def record_request(self, engine: str, success: bool, latency_ms: int):
        self._total_requests[engine] = self._total_requests.get(engine, 0) + 1
        if not success:
            self._error_counts[engine] = self._error_counts.get(engine, 0) + 1

        if engine not in self._latencies:
            self._latencies[engine] = []
        self._latencies[engine].append(latency_ms)
        if len(self._latencies[engine]) > 1000:
            self._latencies[engine] = self._latencies[engine][-1000:]

    def check_alerts(self, engine: str) -> List[Dict[str, Any]]:
        alerts = []

        total = self._total_requests.get(engine, 0)
        errors = self._error_counts.get(engine, 0)

        if total > 10:
            error_rate = errors / total
            if error_rate > self.config.alert_on_error_rate:
                alerts.append({
                    "type": "high_error_rate",
                    "engine": engine,
                    "error_rate": error_rate,
                    "threshold": self.config.alert_on_error_rate,
                    "severity": "warning",
                })

        latencies = self._latencies.get(engine, [])
        if latencies:
            sorted_lat = sorted(latencies)
            p99_idx = int(len(sorted_lat) * 0.99)
            p99 = sorted_lat[p99_idx] if p99_idx < len(sorted_lat) else sorted_lat[-1]
            if p99 > self.config.alert_on_latency_p99 * 1000:
                alerts.append({
                    "type": "high_latency_p99",
                    "engine": engine,
                    "p99_ms": p99,
                    "threshold_ms": self.config.alert_on_latency_p99 * 1000,
                    "severity": "warning",
                })

        return alerts


def init_observability(
    log_level: str = "INFO",
    structured: bool = True,
    log_format: str = "json",
    metrics: bool = True,
    metrics_port: int = 9090,
    tracing: bool = False,
    tracing_endpoint: str = None,
    service_name: str = "hybrid-scraper",
    log_dir: str = "./logs",
) -> ObservabilityConfig:
    config = ObservabilityConfig(
        log_level=log_level,
        structured_logging=structured,
        log_format=log_format,
        metrics_enabled=metrics,
        metrics_port=metrics_port,
        tracing_enabled=tracing,
        tracing_endpoint=tracing_endpoint,
        service_name=service_name,
        log_dir=Path(log_dir),
    )
    configure_observability(config)
    return config