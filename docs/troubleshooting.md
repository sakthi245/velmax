# Troubleshooting Guide

## Common Issues and Solutions

### Engine Selection Issues

#### Firecrawl not selected for PDF/anti-bot sites
**Problem**: PDF URLs or anti-bot sites use crawlee/playwright instead of firecrawl.

**Solution**: Check routing rules in `config/engines.yaml`:
```yaml
routing:
  rules:
    - pattern: "*.pdf"
      engine: "firecrawl"
      reason: "Better PDF parsing and text extraction"
```
Ensure `firecrawl` is registered in `scraper/engines/__init__.py`.

#### Playwright selected instead of Crawlee for JS sites
**Problem**: JS-heavy sites use Playwright instead of Crawlee.

**Fix**: Check routing rules for `requires_js: true` mapping to `crawlee`:
```yaml
routing:
  rules:
    - requires_js: true
      engine: "crawlee"
      reason: "Managed browser pool with session persistence"
```

### Engine Initialization Issues

#### Playwright browsers not installed
```
Error: playwright install chromium
```
**Fix**: Run `playwright install chromium` after installing dependencies.

#### Firecrawl Docker not starting
```
Error: Failed to start Firecrawl Docker
```
**Solutions**:
1. Check Docker is running: `docker ps`
2. Check ports 3002, 3003 available
3. Check `.env.firecrawl` has valid `OPENAI_API_KEY` (Groq key)
3. Check Docker logs: `docker logs firecrawl-api`

#### Crawlee session pool exhaustion
```
Error: Session pool exhausted
```
**Fix**: Increase `session_pool_size` in config, or reduce `max_concurrency`.

### Network/Connection Issues

#### Connection timeout
```
Error: TimeoutError: Request timeout
```
**Solutions**:
1. Increase timeout: `timeout: 60` in engine config
2. Check proxy configuration
3. Verify target site is accessible

#### DNS resolution failures
```
Error: DNS resolution failed
```
**Fix**: Check DNS settings, try alternative DNS (8.8.8.8, 1.1.1.1)

#### SSL/TLS certificate errors
```
Error: SSL certificate verify failed
```
**Solutions**:
1. Use `--ignore-https-errors` in browser config
2. Update CA certificates
3. For testing: `ignore_https_errors: true` in browser config

### Rate Limiting / 429 Errors

#### HTTP 429 Too Many Requests
**Solutions**:
1. Reduce `requests_per_second` in config
2. Enable autothrottle: `autothrottle_enabled: true`
3. Add delays: `download_delay: 2`
4. Use proxy rotation (configure proxy pools)

#### Cloudflare/Akamai blocking
**Solutions**:
1. Enable Firecrawl (auto-selected for Cloudflare)
2. Use stealth mode: `stealth_mode: true`
3. Add realistic headers/user-agents
4. Use residential proxies

### Parsing/Extraction Issues

#### Empty results / empty selectors
```
Warning: No data extracted, selectors returned empty
```
**Debugging**:
1. Check if page loads JavaScript (needs browser engine)
2. Verify selectors in browser dev tools
3. Check for iframe content
4. Wait for dynamic content: `wait_for_selector: ".content"`

#### Encoding issues / garbled text
**Fix**: Set explicit encoding in HTTP engine:
```yaml
http_engine:
  force_encoding: "utf-8"
```

#### Empty response body (204 No Content)
**Fix**: Handle 204 responses in extraction logic, or treat as empty result.

#### JavaScript errors in page
```
Error: JavaScript error in page
```
**Fix**: Use `wait_for_function` to wait for JS execution, or add `extra_wait_ms`.

### Memory/Performance Issues

#### High memory usage
```
MemoryError: Out of memory
```
**Solutions**:
1. Reduce browser pool: `pool_max: 3`
2. Recycle contexts: `recycle_after_pages: 20`
3. Enable resource blocking: `images: true, fonts: true, media: true`
4. Reduce concurrency: `max_concurrent_browsers: 2`

#### Browser context leaks
```
Warning: Browser context not closed properly
```
**Fix**: Ensure proper cleanup in shutdown, increase `recycle_after_pages: 20`.

#### High CPU usage
**Fix**: 
- Reduce concurrency
- Disable unnecessary features (screenshots, video, HAR)
- Use HTTP engine where possible

### Engine Selection Failures

#### No engine available
```
Error: No engine available for request
```
**Debug**:
1. Check engine registration: `EngineRegistry.get_available()`
2. Verify engine dependencies installed
3. Check engine health: `engine.health_check()`

#### Fallback not working
```
Error: All engines failed
```
**Debug**:
1. Check circuit breaker states
2. Verify fallback chain configuration
3. Check individual engine health

### Configuration Issues

#### Config not loading
```
Error: Configuration validation failed
```
**Debug**:
1. Run `python -m scraper.run --help` to validate config
2. Check YAML syntax: `python -c "import yaml; yaml.safe_load(open('config.yaml'))"`

#### Environment variables not loading
**Fix**: Check `SCRAPER_` prefix in `.env` file:
```
SCRAPER_LOG_LEVEL=DEBUG
SCRAPER_OUTPUT_DIR=./my_output
```

#### Config validation errors
```
ValidationError: 1 validation error for UniversalConfig
```
**Fix**: Run `python -c "from scraper.config import load_config; load_config()"` to see full error.

### Output Issues

#### No output files generated
**Check**:
1. Output directory exists: `mkdir -p output`
2. Write permissions: `ls -la output/`
3. Check data extraction logic

#### CSV export missing columns
**Fix**: Ensure all items have same keys, or use `dict.get(key, "")`

#### JSONL format issues
**Fix**: Ensure all items are valid JSON objects, handle None/NaN values.

### Performance Tuning

#### Slow scraping
**Optimizations**:
1. Use `scrapy` for static sites (fastest)
2. Reduce `wait_for_timeout` / `extra_wait_ms`
3. Increase concurrency (within rate limits)
4. Use HTTP engine for static sites

#### High latency
**Optimizations**:
1. Enable HTTP/2: `http2: true` in httpx client
2. Enable connection pooling
3. Use keep-alive headers
4. Geographic proximity to target

### Debugging Tips

#### Enable debug logging
```bash
SCRAPER_LOG_LEVEL=DEBUG python -m scraper.run ...
```

#### Enable debug logging in config
```yaml
observability:
  log_level: DEBUG
  structured_logging: true
  log_format: json
```

#### Capture HAR for debugging
```yaml
browser_engine:
  har_recording: true
  har_path: "./debug.har"
```

#### Screenshot on error
```yaml
browser_engine:
  screenshot_on_error: true
```

#### Enable HAR recording
```bash
python -m scraper.run --target "https://example.com" --goal "debug" --har ./debug.har
```

### Engine-Specific Debugging

#### Playwright debugging
```python
# Run with headed mode for debugging
result = await scrape(url, goal, engine="playwright", headless=False)

# Use Playwright inspector
page.pause()  # Pauses execution
```

#### Firecrawl debugging
```bash
# Check Firecrawl API health
curl http://localhost:3002/health

# Check Firecrawl logs
docker logs firecrawl-api
```

#### Crawlee debugging
```python
# Enable Crawlee debugging
import os
os.environ["CRAWLEE_LOG_LEVEL"] = "DEBUG"
```

### Getting Help

1. **Check logs**: `SCRAPER_LOG_LEVEL=DEBUG`
2. **Enable HAR/Screenshots**: For visual debugging
3. **Check engine health**: `engine.health_check()`
3. **Check circuit breakers**: `breaker.get_state()`
4. **File issues**: Include logs, config, and minimal reproduction case