# Distributed Workers Setup Guide

## Overview

The distributed workers system enables horizontal scaling of the scraper across multiple worker processes. Each worker runs independently with its own browser pool, connects to a shared RabbitMQ task queue, Redis for distributed rate limiting, and PostgreSQL for shared state management.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Shared Infrastructure                     │
├─────────────────────────────────────────────────────────────┤
│  PostgreSQL (crawl state)     RabbitMQ (task queue)          │
│  - crawl_sessions             - scrapy.tasks.detail (prio=10)│
│  - url_frontier               - scrapy.tasks.list   (prio=5) │
│  - visited_urls               - scrapy.tasks.other  (prio=1) │
│  - checkpoints                - scrapy.dlq (dead letter)     │
└─────────────────────────────────────────────────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
        ┌──────────┐    ┌──────────┐    ┌──────────┐
        │ Worker 1 │    │ Worker 2 │    │ Worker 3 │
        │ Browser  │    │ Browser  │    │ Browser  │
        │ Pool     │    │ Pool     │    │ Pool     │
        └──────────┘    └──────────┘    └──────────┘
```

## Quick Start

### Prerequisites

- Docker & Docker Compose
- Existing Firecrawl stack running (ports 3002/3003)

### Start the Distributed Stack

```bash
# Start the distributed infrastructure
docker compose -f docker-compose.distributed.yml up -d

# Check service health
docker compose -f docker-compose.distributed.yml ps

# View logs
docker compose -f docker-compose.distributed.yml logs -f worker
```

### Scale Workers

```bash
# Scale to 5 workers
docker compose -f docker-compose.distributed.yml up --scale worker=5 -d

# Scale down
docker compose -f docker-compose.distributed.yml up --scale worker=2 -d
```

### Access Monitoring

- **Prometheus**: http://localhost:9090
- **Grafana**: http://localhost:3000 (admin/admin)
- **RabbitMQ Management**: http://localhost:15673 (guest/guest)

## Configuration

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `WORKER_ID` | auto | Unique worker identifier |
| `MAX_CONCURRENT` | 5 | Max concurrent tasks per worker |
| `HEARTBEAT_INTERVAL` | 30 | Heartbeat interval (seconds) |
| `GRACEFUL_SHUTDOWN_TIMEOUT` | 60 | Shutdown timeout (seconds) |
| `METRICS_PORT` | 9090 | Prometheus metrics port |
| `QUEUE_HOST` | rabbitmq-distributed | RabbitMQ host |
| `QUEUE_PORT` | 5672 | RabbitMQ port |
| `REDIS_URL` | redis://redis-distributed:6379 | Redis URL |
| `POSTGRES_DSN` | postgresql://scraper:scraper@postgres-distributed:5432/scraper_distributed | PostgreSQL DSN |

### Task Priority

Tasks are processed by priority (higher = first):
- **DETAIL** (10) - Product/detail pages
- **LIST** (5) - Listing/category pages  
- **OTHER** (1) - Everything else

### Retry Policy

- Max retries: 3
- Exponential backoff: 30s, 60s, 120s
- After max retries → Dead Letter Queue (DLQ)

## Submitting Tasks

### Via Python API

```python
from scraper.utils.queue import QueueManager, ScrapeTask, TaskPriority, create_task_from_url
from scraper.config import QueueConfig

async def submit_tasks():
    config = QueueConfig(host="localhost", port=5673)
    async with QueueManager(config) as qm:
        task = await create_task_from_url(
            url="https://example.com/product/123",
            session_id="session-123",
            goal="Extract product details",
            priority=TaskPriority.DETAIL,
            depth=1,
        )
        await qm.publish_task(task)
```

### Via CLI (Future)

```bash
python -m scraper.worker --help
```

## Monitoring

### Prometheus Metrics

Each worker exposes metrics on port 9090+worker_id:

| Metric | Type | Description |
|--------|------|-------------|
| `scraper_worker_tasks_total` | Counter | Tasks processed by status/engine/domain |
| `scraper_worker_task_duration_seconds` | Histogram | Task processing duration |
| `scraper_worker_queue_depth` | Gauge | Current queue depth by type |
| `scraper_worker_rate_limit_wait_seconds` | Histogram | Time waiting for rate limits |
| `scraper_worker_browser_pool_size` | Gauge | Browser pool size |
| `scraper_worker_health` | Gauge | Health status (1=up, 0=down) |

### Grafana Dashboard

Import `grafana/dashboards/scraper-workers.json` for a pre-built dashboard showing:
- Worker CPU/Memory usage
- Task throughput (success/failed/sec)
- Queue depths by priority
- Rate limit wait times
- Worker health status

## Troubleshooting

### Worker Not Starting

```bash
# Check logs
docker compose -f docker-compose.distributed.yml logs worker

# Common issues:
# 1. RabbitMQ not ready - wait for health check
# 2. PostgreSQL connection - check DSN and network
# 2. Port conflicts - check METRICS_PORT
```

### Tasks Stuck in Queue

```bash
# Check RabbitMQ management UI
# http://localhost:15673 (guest/guest)

# Check queue depths
curl http://localhost:9091/metrics | grep queue_depth

# Requeue DLQ tasks
# (manual intervention needed)
```

### High Memory Usage

```bash
# Reduce MAX_CONCURRENT
# Check browser pool settings in config
# Monitor via Grafana: scraper_worker_memory_bytes
```

## Development

### Running Worker Locally

```bash
# Install dependencies
pip install -e ".[all]"

# Set environment variables
export QUEUE_HOST=localhost
export QUEUE_PORT=5673
export REDIS_URL=redis://localhost:6380
export POSTGRES_DSN=postgresql://scraper:scraper@localhost:5433/scraper_distributed

# Run worker
python -m scraper.worker
```

### Adding Custom Tasks

```python
from scraper.utils.queue import create_task_from_url, TaskPriority

task = await create_task_from_url(
    url="https://example.com",
    session_id="my-session",
    goal="Extract data",
    priority=TaskPriority.DETAIL,
    depth=1,
    max_retries=3,
)
await queue_manager.publish_task(task)
```

## File Structure

```
├── docker-compose.distributed.yml    # Main compose file
├── Dockerfile.worker                  # Worker image
├── prometheus.distributed.yml         # Prometheus config
├── grafana/
│   ├── datasources/prometheus.yml     # Prometheus datasource
│   └── dashboards/scraper-workers.json # Grafana dashboard
├── scraper/
│   ├── worker.py                      # Worker entry point
│   ├── utils/
│   │   ├── queue.py                   # RabbitMQ wrapper
│   │   ├── coordinator.py             # Worker coordination
│   │   ├── rate_limiter.py            # Redis rate limiter
│   │   └── metrics_worker.py          # Prometheus metrics
│   └── engines/
│       └── managed_engine.py          # Modified for distributed
└── scraper/config/
    └── schemas.py                     # QueueConfig, WorkerConfig, TaskPriority
```

## Next Steps

1. **Phase 3**: Advanced Anti-Bot (fingerprint rotation, behavioral mimicry)
2. **Phase 4**: Data Quality (validation, deduplication, enrichment)
3. **Performance**: Load testing with 1000+ URLs
3. **Production**: Add TLS, secrets management, auto-scaling rules