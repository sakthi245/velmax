# Firecrawl Docker - Complete Error Inventory for Gordon AI

## Project Context
- **Project**: hybrid-web-scraper (robots-aware, free-first scraping pipeline)
- **Docker VM**: 3.48GB total memory (Docker Desktop on Windows/WSL2)
- **Goal**: Self-hosted Firecrawl API with Groq LLM integration
- **Current Status**: Non-Docker pipeline works (Groq+Crawlee, 17/17 tests pass)

---

## 1. Image Name Changes (BREAKING - Fixed in compose)

| Service | Old Image (404) | New Image (Working) |
|---------|-----------------|---------------------|
| Firecrawl API | `ghcr.io/mendableai/firecrawl:latest` | `ghcr.io/firecrawl/firecrawl:latest` |
| Playwright Service | `ghcr.io/mendableai/playwright-service:latest` | `ghcr.io/firecrawl/playwright-service:latest` |
| PostgreSQL (NUQ) | `postgres:15` | `ghcr.io/firecrawl/nuq-postgres:latest` |

**Error**: `pull access denied` / `manifest unknown` for old images.

---

## 2. Environment Variable Mismatches

| Variable | Wrong Value | Correct Value | Impact |
|----------|-------------|---------------|--------|
| `NUQ_BACKEND` | `postgres` | `pg` (or `fdb`) | App crashes - only accepts `pg`/`fdb` |
| `POSTGRES_DB` | `firecrawl` | `postgres` | NUQ schema hardcoded to `postgres` DB |
| `OPENAI_MODEL` | `llama-3.1-8b-instant` | `groq/compound` | Model not in Groq's available list |
| `OPENAI_API_KEY` | `[REDACTED]` | `${OPENAI_API_KEY}` | Must load from `.env.firecrawl` |

---

## 3. Authentication Required

**Error**: `Error response from daemon: pull access denied`

**Fix Required**:
```bash
docker login ghcr.io -u YOUR_GITHUB_USERNAME -p YOUR_GH_TOKEN
# PAT must have: packages:read scope
```

---

## 4. Memory/Resource Constraints (CRITICAL BLOCKER)

**Docker VM**: 3.48GB total  
**Firecrawl-api spawns**: 10+ Node.js processes:
- api (main)
- worker (queue)
- extract-worker
- 5× nuq-worker
- prefetch-worker
- reconciler

| Container | Required Memory | Available (3.48GB VM) |
|-----------|-----------------|----------------------|
| firecrawl-api | ~8GB (all workers) | **IMPOSSIBLE** |
| playwright | 2GB | Tight |
| postgres (nuq) | 2GB | Tight |
| redis | 512MB | OK |
| rabbitmq | 512MB | OK |

**Result**: `exit code 137` (OOM kill) on firecrawl-api within 30-40 seconds.

---

## 5. Worker Concurrency Must Be Minimized

All these must be set to `1` (or disabled) to attempt fit:

```yaml
environment:
  - CRAWL_CONCURRENT_REQUESTS=1
  - MAX_CONCURRENT_JOBS=1
  - BROWSER_POOL_SIZE=1
  - NUM_WORKERS_PER_QUEUE=1
  - NUQ_WORKER_CONCURRENCY=1
  - NUQ_PREFETCH_COUNT=1
  - NUQ_NUM_WORKERS=1
  - EXTRACT_WORKER_CONCURRENCY=1
  - PREFETCH_WORKER_CONCURRENCY=1
  - RECONCILER_WORKER_CONCURRENCY=1
  # Disable extra workers entirely:
  - NUQ_WORKERS_DISABLED=true
  - EXTRACT_WORKERS_DISABLED=true
  - PREFETCH_WORKERS_DISABLED=true
  - RECONCILER_WORKERS_DISABLED=true
  - QUEUE_WORKERS_DISABLED=true
```

**Even with all disabled**: Baseline harness + api + 1 worker ≈ 2.5GB minimum.

---

## 6. Playwright Service Browser Missing

**Error**: 
```
Executable doesn't exist at /ms-playwright/chromium_headless_shell-1208/chrome-headless-shell-linux64/chrome-headless-shell
```

**Root Cause**: `ghcr.io/firecrawl/playwright-service:latest` doesn't include Chromium.

**Fix Required in Container Startup**:
```bash
# Install browsers + create symlink
npx playwright install chromium --with-deps
ln -s /usr/local/share/playwright /ms-playwright
```

**Compose Requirements**:
```yaml
playwright:
  user: root  # Required for symlink permission
  command: sh -c "rm -rf /ms-playwright && ln -s /usr/local/share/playwright /ms-playwright; node dist/api.js"
  ports:
    - "3000:3000"  # Must expose for firecrawl-api
  healthcheck:
    test: ["CMD", "curl", "-f", "http://localhost:3000/health"]
```

**Additional**: Install `curl` for healthcheck: `apt-get update && apt-get install -y curl`

---

## 7. Health Check Failures

| Service | Problem | Fix |
|---------|---------|-----|
| playwright | No healthcheck defined | Add `curl -f http://localhost:3000/health` |
| playwright | `curl` not installed | Install via apt-get |
| firecrawl-api | Workers OOM before health | Increase `start_period: 180s+` |

---

## 8. RabbitMQ Authentication Mismatch

**All Must Match Exactly**:
```yaml
rabbitmq:
  environment:
    - RABBITMQ_DEFAULT_USER=guest
    - RABBITMQ_DEFAULT_PASS=guest

firecrawl-api:
  environment:
    - NUQ_RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672
    - RABBITMQ_URL=amqp://guest:guest@rabbitmq:5672
```

---

## 9. PostgreSQL NUQ Schema Requirements

```yaml
postgres:
  image: ghcr.io/firecrawl/nuq-postgres:latest
  environment:
    - POSTGRES_DB=postgres      # HARDCODED - cannot change
    - POSTGRES_USER=postgres
    - POSTGRES_PASSWORD=postgres
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U postgres -d postgres"]
```

---

## 10. Missing `env_file` Loading

**Problem**: `.env.firecrawl` not loaded → `OPENAI_API_KEY` blank warning

**Fix**: Add to both firecrawl-api and playwright:
```yaml
env_file:
  - .env.firecrawl
```

---

## 11. Port Exposure Missing

**Problem**: firecrawl-api cannot reach playwright service

**Fix**:
```yaml
playwright:
  ports:
    - "3000:3000"
```

---

## 12. Groq API Integration Issues

- Firecrawl expects OpenAI-compatible API
- Groq works via: `OPENAI_BASE_URL=https://api.groq.com/openai/v1`
- **But**: Firecrawl's internal workers may not respect custom model
- Model `groq/compound` verified working via direct API, but Firecrawl may default to other models

---

## 13. Container Restart Loop (Playwright)

1. Playwright restarts
2. Loses browser symlink (`/ms-playwright`)
3. Healthcheck fails
4. firecrawl-api won't start (depends_on: service_healthy)
5. Infinite loop

**Fix**: Symlink in startup command that runs every container start.

---

## 14. Current docker-compose.firecrawl.yml (Partial Fix Attempt)

```yaml
# Key settings applied:
firecrawl-api:
  mem_limit: 3.5g
  env_file: .env.firecrawl
  # All workers disabled via env vars

playwright:
  user: root
  command: sh -c "rm -rf /ms-playwright && ln -s /usr/local/share/playwright /ms-playwright; node dist/api.js"
  ports: ["3000:3000"]
  healthcheck: curl -f http://localhost:3000/health

postgres:
  image: ghcr.io/firecrawl/nuq-postgres:latest
  POSTGRES_DB=postgres
```

---

## 15. Verdict for 3.48GB VM

**NOT VIABLE** - Firecrawl's architecture (10+ Node processes) fundamentally conflicts with 3.48GB limit.

### Options:
1. **Increase Docker VM memory** to 8GB+ (Docker Desktop → Settings → Resources → Advanced)
2. **Use Firecrawl Cloud** (paid)
3. **Run on separate machine/server** with 8GB+ RAM
4. **Stick with Groq+Crawlee** (working, no Docker, free, 14.4k req/day)

---

## Current Working Alternative (No Docker)

| Feature | Status |
|---------|--------|
| Scrapy engine | ✅ Fast HTTP |
| Playwright engine | ✅ JS rendering |
| Crawlee engine | ✅ Browser pool |
| Groq LLM (Extract/Agent/Search) | ✅ groq/compound |
| All 17 tests | ✅ Passing |
| CLI + Python API | ✅ Working |

---

## Request for Gordon AI

Please provide:
1. **Minimal worker configuration** that actually works within 4GB
2. **Whether Firecrawl can run with ONLY api + 1 queue worker** (disable all others via env)
3. **Official memory requirements** for self-hosted Firecrawl
4. **If `NUQ_WORKERS_DISABLED` etc. are real env vars** or if we need different approach
5. **Lightweight alternative** - can we run just the scrape API without crawl/extract workers?