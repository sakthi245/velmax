#!/usr/bin/env python3
"""Distributed Scraper Worker Entry Point.

This module provides the main entry point for running a distributed scraper worker.
Workers connect to RabbitMQ for task distribution and PostgreSQL for state management.

Usage:
    python -m scraper.worker [options]
    
Environment Variables:
    RABBITMQ_HOST, RABBITMQ_PORT, RABBITMQ_USER, RABBITMQ_PASS
    REDIS_HOST, REDIS_PORT
    POSTGRES_DSN
    WORKER_ID, WORKER_MAX_CONCURRENT, WORKER_HEARTBEAT_INTERVAL
    METRICS_PORT
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .config import (
    load_config,
    QueueConfig,
    WorkerConfig,
    UniversalConfig,
    CheckpointConfig,
)
from .engines.managed_engine import ManagedEngine, create_managed_engine
from .engines.interfaces import EngineConfig
from .utils.queue import QueueManager, ScrapeTask, TaskScheduler, TaskPriority, create_task_from_url
from .utils.coordinator import WorkerCoordinator
from .utils.rate_limiter import DistributedRateLimiter, RateLimitConfig
from .utils.metrics_worker import WorkerMetrics, WorkerMetricsConfig, MetricsServer, create_metrics_server_sync
from .utils.state import CrawlStateManager, create_state_manager

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class WorkerRuntimeConfig:
    worker_id: str
    max_concurrent: int = 5
    heartbeat_interval: int = 30
    graceful_shutdown_timeout: int = 60
    metrics_port: int = 9090
    log_level: str = "INFO"
    
    queue_host: str = "localhost"
    queue_port: int = 5672
    queue_user: str = "guest"
    queue_pass: str = "guest"
    queue_vhost: str = "/"
    
    redis_url: str = "redis://localhost:6379"
    postgres_dsn: str = ""
    
    checkpoint_enabled: bool = True
    checkpoint_interval_pages: int = 100
    checkpoint_interval_seconds: int = 300


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Distributed Scraper Worker",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    
    parser.add_argument(
        "--worker-id",
        type=str,
        default=os.environ.get("WORKER_ID", ""),
        help="Unique worker ID (auto-generated if not provided)",
    )
    parser.add_argument(
        "--max-concurrent",
        type=int,
        default=int(os.environ.get("MAX_CONCURRENT", "5")),
        help="Maximum concurrent tasks",
    )
    parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=int(os.environ.get("HEARTBEAT_INTERVAL", "30")),
        help="Heartbeat interval in seconds",
    )
    parser.add_argument(
        "--graceful-shutdown-timeout",
        type=int,
        default=int(os.environ.get("GRACEFUL_SHUTDOWN_TIMEOUT", "60")),
        help="Graceful shutdown timeout in seconds",
    )
    parser.add_argument(
        "--metrics-port",
        type=int,
        default=int(os.environ.get("METRICS_PORT", "9090")),
        help="Prometheus metrics port",
    )
    parser.add_argument(
        "--log-level",
        type=str,
        default=os.environ.get("LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Log level",
    )
    
    # RabbitMQ
    parser.add_argument(
        "--queue-host",
        type=str,
        default=os.environ.get("QUEUE_HOST", "localhost"),
        help="RabbitMQ host",
    )
    parser.add_argument(
        "--queue-port",
        type=int,
        default=int(os.environ.get("QUEUE_PORT", "5672")),
        help="RabbitMQ port",
    )
    parser.add_argument(
        "--queue-user",
        type=str,
        default=os.environ.get("QUEUE_USER", "guest"),
        help="RabbitMQ username",
    )
    parser.add_argument(
        "--queue-pass",
        type=str,
        default=os.environ.get("QUEUE_PASS", "guest"),
        help="RabbitMQ password",
    )
    parser.add_argument(
        "--queue-vhost",
        type=str,
        default=os.environ.get("QUEUE_VHOST", "/"),
        help="RabbitMQ vhost",
    )
    
    # Redis
    parser.add_argument(
        "--redis-url",
        type=str,
        default=os.environ.get("REDIS_URL", "redis://localhost:6379"),
        help="Redis connection URL",
    )
    
    # PostgreSQL
    parser.add_argument(
        "--postgres-dsn",
        type=str,
        default=os.environ.get("POSTGRES_DSN", ""),
        help="PostgreSQL DSN for state management",
    )
    
    # Checkpoint
    parser.add_argument(
        "--checkpoint-enabled",
        action="store_true",
        default=os.environ.get("CHECKPOINT_ENABLED", "true").lower() == "true",
        help="Enable checkpointing",
    )
    parser.add_argument(
        "--checkpoint-interval-pages",
        type=int,
        default=100,
        help="Checkpoint every N pages",
    )
    parser.add_argument(
        "--checkpoint-interval-seconds",
        type=int,
        default=300,
        help="Checkpoint every N seconds",
    )
    
    return parser.parse_args()


def load_runtime_config(args: argparse.Namespace) -> WorkerRuntimeConfig:
    return WorkerRuntimeConfig(
        worker_id=args.worker_id or f"worker-{uuid.uuid4().hex[:8]}",
        max_concurrent=args.max_concurrent,
        heartbeat_interval=args.heartbeat_interval,
        graceful_shutdown_timeout=args.graceful_shutdown_timeout,
        metrics_port=args.metrics_port,
        log_level=args.log_level,
        queue_host=args.queue_host,
        queue_port=args.queue_port,
        queue_user=args.queue_user,
        queue_pass=args.queue_pass,
        queue_vhost=args.queue_vhost,
        redis_url=args.redis_url,
        postgres_dsn=args.postgres_dsn,
        checkpoint_enabled=args.checkpoint_enabled,
        checkpoint_interval_pages=args.checkpoint_interval_pages,
        checkpoint_interval_seconds=args.checkpoint_interval_seconds,
    )


async def create_managers(config: WorkerRuntimeConfig):
    """Create all manager instances."""
    
    # Queue config
    queue_config = QueueConfig(
        host=config.queue_host,
        port=config.queue_port,
        username=config.queue_user,
        password=config.queue_pass,
        vhost=config.queue_vhost,
    )
    
    # Worker config
    worker_config = WorkerConfig(
        worker_id=config.worker_id,
        max_concurrent=config.max_concurrent,
        heartbeat_interval=config.heartbeat_interval,
        graceful_shutdown_timeout=config.graceful_shutdown_timeout,
        metrics_port=config.metrics_port,
        log_level=config.log_level,
    )
    
    # Rate limit config
    rate_limit_config = RateLimitConfig(
        requests_per_second=2.0,
        per_domain=True,
        adaptive=True,
    )
    
    # Checkpoint config
    checkpoint_config = CheckpointConfig(
        enabled=config.checkpoint_enabled,
        interval_pages=config.checkpoint_interval_pages,
        interval_seconds=config.checkpoint_interval_seconds,
    )
    
    # Create queue manager
    queue_manager = QueueManager(queue_config)
    await queue_manager.connect()
    
    # Create rate limiter
    rate_limiter = DistributedRateLimiter(config.redis_url, rate_limit_config)
    await rate_limiter.initialize()
    
    # Create coordinator
    coordinator = WorkerCoordinator(queue_manager, worker_config, queue_config)
    await coordinator.start()
    
    # Create state manager if checkpointing is enabled
    state_manager = None
    if config.postgres_dsn and config.checkpoint_enabled:
        state_manager = CrawlStateManager(checkpoint_config)
        await state_manager.initialize(config.postgres_dsn)
    
    # Create metrics
    metrics_config = WorkerMetricsConfig(port=config.metrics_port)
    metrics, metrics_server = await create_metrics_server_sync(
        worker_id=config.worker_id,
        config=metrics_config,
    )
    
    return {
        "queue_manager": queue_manager,
        "coordinator": coordinator,
        "rate_limiter": rate_limiter,
        "state_manager": state_manager,
        "metrics": metrics,
        "metrics_server": metrics_server,
        "queue_config": queue_config,
        "worker_config": worker_config,
        "checkpoint_config": checkpoint_config,
    }


async def process_task(
    task: ScrapeTask,
    engine: ManagedEngine,
    managers: Dict[str, Any],
) -> bool:
    """Process a single scrape task."""
    coordinator = managers["coordinator"]
    metrics = managers["metrics"]
    rate_limiter = managers["rate_limiter"]
    
    # Register task with coordinator
    if not coordinator.register_task(task.task_id):
        logger.warning(f"Worker at capacity, requeueing task {task.task_id}")
        return False
    
    # Acquire rate limit
    domain = task.url.split("/")[2] if "//" in task.url else "default"
    await rate_limiter.acquire(domain)
    
    start_time = time.time()
    success = False
    error_type = None
    
    try:
        # Create engine config
        engine_config = EngineConfig(
            name="managed",
            config={
                "managed_engine": {
                    "max_concurrent": 1,
                    "headless": True,
                    "browser_type": "chromium",
                },
                "rate_limit": {
                    "requests_per_second": 2.0,
                },
            },
        )
        
        # Process the task
        async for result in engine.crawl(
            type("CrawlStrategy", (), {
                "start_urls": [task.url],
                "max_depth": task.depth,
                "max_pages": 1,
                "allowed_domains": [domain],
                "page_type_selectors": {},
                "pagination_selectors": [],
            })()
        ):
            success = True
            
            # Record metrics
            metrics.record_task_completion(
                {"start_time": time.time() - (time.time() - time.time()), "domain": domain},
                success=success,
                engine="managed",
            )
            
            # Complete task
            coordinator.complete_task(task.task_id, success=True)
            return True
            
    except Exception as e:
        logger.error(f"Task {task.task_id} failed: {e}")
        error_type = type(e).__name__
        success = False
    finally:
        coordinator.complete_task(task.task_id, success)
        
        # Record metrics
        metrics.record_task_completion(
            {"start_time": time.time() - (time.time() - start_time), "domain": domain},
            success=success,
            engine="managed",
            error_type=error_type,
        )
    
    return success


async def worker_loop(managers: Dict[str, Any], config: WorkerRuntimeConfig) -> None:
    """Main worker loop."""
    queue_manager = managers["queue_manager"]
    coordinator = managers["coordinator"]
    task_scheduler = TaskScheduler(queue_manager, UniversalConfig())
    
    logger.info(f"Worker {config.worker_id} started, waiting for tasks...")
    
    while True:
        try:
            # Get next batch of tasks
            tasks = await queue_manager.get_tasks(batch_size=config.max_concurrent)
            
            if not tasks:
                await asyncio.sleep(1)
                continue
            
            # Add tasks to scheduler
            await task_scheduler.add_tasks(tasks)
            
            # Process tasks
            while task_scheduler.pending_count() > 0:
                # Check if we can accept more tasks
                if not coordinator.register_task("temp"):
                    await asyncio.sleep(0.5)
                    continue
                
                # Flush one task
                published = await task_scheduler.flush(batch_size=1)
                if published == 0:
                    break
                
                # Small delay to prevent busy loop
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            logger.info("Worker loop cancelled")
            break
        except Exception as e:
            logger.error(f"Worker loop error: {e}")
            await asyncio.sleep(5)


async def main(config: WorkerRuntimeConfig) -> int:
    logger.info(f"Starting worker {config.worker_id}")
    
    managers = await create_managers(config)
    
    # Setup signal handlers
    shutdown_event = asyncio.Event()
    
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()
    
    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, signal_handler)
    
    try:
        # Start worker loop
        await worker_loop(managers, config)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logger.error(f"Worker error: {e}")
        return 1
    finally:
        logger.info("Shutting down worker...")
        
        # Graceful shutdown
        try:
            await asyncio.wait_for(
                managers["coordinator"].stop(),
                timeout=config.graceful_shutdown_timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("Coordinator shutdown timeout")
        
        try:
            await managers["queue_manager"].close()
        except Exception:
            pass
        
        try:
            await managers["rate_limiter"].close()
        except Exception:
            pass
        
        try:
            if managers["state_manager"]:
                await managers["state_manager"].close()
        except Exception:
            pass
        
        try:
            await managers["metrics_server"].stop()
        except Exception:
            pass
    
    logger.info(f"Worker {config.worker_id} stopped")
    return 0


if __name__ == "__main__":
    args = parse_args()
    runtime_config = load_runtime_config(args)
    
    # Set log level
    logging.getLogger().setLevel(getattr(logging, runtime_config.log_level))
    
    exit_code = asyncio.run(main(runtime_config))
    sys.exit(exit_code)