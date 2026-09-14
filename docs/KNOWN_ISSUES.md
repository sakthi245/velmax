# Known Issues

This document tracks known issues in the current release. Community contributions to fix these are welcome!

## 1. Engine Registry Test Pollution

**Status**: Open
**Priority**: High
**Labels**: `testing`, `engine-registry`

### Description

The `EngineRegistryV2` uses class-level dictionaries (`_instances`, `_registrations`, etc.) that persist across test runs. When tests run in sequence, state from previous tests pollutes subsequent tests, causing flaky failures.

### Symptoms

- `test_regular_url_request` fails with `'EngineConfig' object has no attribute 'get'`
- `test_research_mode_auto_detection` fails with engine not registered errors
- Tests pass in isolation but fail in suite

### Root Cause

```python
# In registry_v2.py
class EngineRegistryV2:
    _registrations: Dict[EngineType, EngineRegistration] = {}
    _instances: Dict[EngineType, BaseEngine] = {}
    # ... other class-level state
```

Tests using `reload_scraper` fixture don't fully clear all class-level dictionaries.

### Workaround

Use the `reload_scraper` fixture which aggressively clears all registry state:
```python
@pytest.mark.asyncio
async def test_my_test(reload_scraper):
    # Test runs with clean registry
```

### Fix Needed

1. Add a `clear_all()` classmethod that clears ALL class dictionaries
2. Call it in the fixture's cleanup phase
3. Consider instance-based registry for better test isolation

---

## 2. Relevance Ranker JSON Validation

**Status**: Open
**Priority**: High
**Labels**: `groq`, `llm`, `json-validation`

### Description

The Groq model `openai/gpt-oss-20b` has strict JSON schema validation that rejects valid JSON if the prompt doesn't explicitly request the exact schema format.

### Symptoms

```
WARNING Relevance ranking failed: Error code: 400 - 
Failed to validate JSON. Please adjust your prompt. 
See 'failed_generation' for more details.
```

### Root Cause

The relevance ranker prompt doesn't explicitly specify the exact JSON output format required by the model's strict validation.

### Workaround

- Use `llama-3.1-70b-versatile` or `mixtral-8x7b` which are more lenient
- Reduce `max_tokens` to prevent truncation

### Fix Needed

1. Update prompt in `relevance_ranker.py` to explicitly request exact JSON format
2. Add JSON schema to the prompt for validation
3. Test with multiple Groq models

---

## 3. Playwright CAPTCHA Handling

**Status**: Open
**Priority**: Medium
**Labels**: `playwright`, `search`, `captcha`

### Description

DuckDuckGo search presents CAPTCHAs that block the PlaywrightSearchEngine, causing test failures.

### Symptoms

```
INFO  CAPTCHA not solved for query 'test query' (page 1), skipping
WARNING CAPTCHA not solved, returning 0 results
```

### Root Cause

DuckDuckGo aggressively CAPTCHAs automated browsers. The current implementation has a 1-second timeout for CAPTCHA solving which is too aggressive.

### Workaround

- Increase CAPTCHA timeout in tests
- Use alternative search engines (TinyFish, SerpAPI) as primary
- Mock PlaywrightSearchEngine in unit tests

### Fix Needed

1. Increase CAPTCHA wait timeout to 10-15 seconds
2. Add CAPTCHA detection and graceful degradation
3. Add mock mode for PlaywrightSearchEngine in tests
4. Consider using undetected-chromedriver or stealth plugins

---

## 4. Firecrawl Docker Integration

**Status**: Open
**Priority**: Low
**Labels**: `firecrawl`, `docker`, `integration`

### Description

Firecrawl cloud engine requires Docker Desktop running locally. Tests fail gracefully when Docker is unavailable but can't test the actual engine.

### Symptoms

```
WARNING Firecrawl Docker unavailable, continuing without cloud engine
Failed to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine
```

### Root Cause

Firecrawl runs as a Docker stack. Without Docker Desktop, the cloud engine can't start.

### Workaround

- Tests skip Firecrawl when Docker unavailable
- Use `mode: free_only` to avoid cloud engines
- CI/CD should have Docker available for full testing

### Fix Needed

1. Add Docker Compose to CI pipeline
2. Add integration test that runs when Docker is available
3. Consider adding Firecrawl API key fallback (hosted Firecrawl)

---

## 5. Deprecation Warnings

**Status**: Open
**Priority**: Low
**Labels**: `deprecation`, `python-3.12`

### Description

Multiple `datetime.utcnow()` deprecation warnings in Python 3.12+.

### Symptoms

```
DeprecationWarning: datetime.datetime.utcnow() is deprecated 
and scheduled for removal in a future version.
```

### Fix Needed

Replace all `datetime.utcnow()` with `datetime.now(timezone.utc)`:
- `universal_runner.py` (lines 67, 157, 858)
- `output_pipeline.py` (lines 195, 254)
- `base_v2.py` (lines 67, 212)

---

## Contributing Fixes

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup and PR process.

### Good First Issues

1. **Fix deprecation warnings** - Straightforward find-and-replace
2. **Add registry clear_all() method** - Isolated change in one file
3. **Increase CAPTCHA timeout** - Single config value change
4. **Add mock mode for PlaywrightSearchEngine** - Good learning exercise

### Need Help?

- Open a Discussion on GitHub
- Tag issue with `help wanted`
- Ping maintainers in PR comments