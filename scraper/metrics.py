from __future__ import annotations
from prometheus_client import Counter, Histogram, Gauge, CollectorRegistry, start_http_server
import threading
import logging
import os

LOG = logging.getLogger(__name__)

registry = CollectorRegistry()

SCRAPE_REQUESTS = Counter(
    'scraper_requests_total',
    'Total scrape requests',
    ['engine', 'status'],
    registry=registry
)

SCRAPE_LATENCY = Histogram(
    'scraper_latency_seconds',
    'Scrape latency in seconds',
    ['engine'],
    registry=registry
)

CIRCUIT_STATE = Gauge(
    'scraper_circuit_state',
    'Circuit breaker state (0=closed, 1=half_open, 2=open)',
    ['engine'],
    registry=registry
)

ENGINE_HEALTH = Gauge(
    'scraper_engine_health',
    'Engine health (1=healthy, 0=unhealthy)',
    ['engine'],
    registry=registry
)

ACTIVE_CRAWLS = Gauge(
    'scraper_active_crawls',
    'Active crawl jobs',
    registry=registry
)

ENGINE_INIT_DURATION = Histogram(
    'scraper_engine_init_duration_seconds',
    'Engine initialization duration',
    ['engine'],
    registry=registry
)

def record_scrape(engine: str, success: bool, latency_ms: int):
    SCRAPE_REQUESTS.labels(engine=engine, status="success" if success else "error").inc()
    SCRAPE_LATENCY.labels(engine=engine).observe(latency_ms / 1000.0)

def set_circuit_state(engine: str, state: int):
    CIRCUIT_STATE.labels(engine=engine).set(state)

def set_engine_health(engine: str, healthy: bool):
    ENGINE_HEALTH.labels(engine=engine).set(1 if healthy else 0)

def inc_active_crawls():
    ACTIVE_CRAWLS.inc()

def dec_active_crawls():
    ACTIVE_CRAWLS.dec()

def record_engine_init(engine: str, duration_seconds: float):
    ENGINE_INIT_DURATION.labels(engine=engine).observe(duration_seconds)

_metrics_server_started = False
_metrics_server_lock = threading.Lock()

def start_metrics_server(port: int = 9090, addr: str = "0.0.0.0"):
    global _metrics_server_started
    with _metrics_server_lock:
        if _metrics_server_started:
            return
        try:
            start_http_server(port, addr=addr, registry=registry)
            _metrics_server_started = True
            LOG.info(f"Prometheus metrics server started on {addr}:{port}")
        except Exception as e:
            LOG.warning(f"Failed to start metrics server: {e}")

def get_registry():
    return registry