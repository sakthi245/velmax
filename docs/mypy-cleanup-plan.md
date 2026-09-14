# Mypy Type Safety Cleanup Plan

**Project**: Hybrid Web Scraper  
**Generated**: 2026-08-24  
**Current Status**: 726 errors across 50 files  
**Target**: 0 errors with `mypy --strict` before production release

---

## Error Category Summary

| Category | Count | Description | Primary Files |
|----------|-------|-------------|---------------|
| **no-untyped-def** | 239 | Missing function return type annotations | base_v2.py, cloud_engine.py, managed_engine.py, api_engine.py, http_engine.py, browser_engine.py, scripts/* |
| **attr-defined** | 99 | Accessing attributes on objects that may not have them | browser_pool.py, base_v2.py, cloud_engine.py, managed_engine.py |
| **no-untyped-call** | 76 | Calling functions without type annotations | base_v2.py, browser_pool.py, cloud_engine.py, managed_engine.py, strategy.py |
| **assignment** | 62 | Type mismatches in assignments | base_v2.py, cloud_engine.py, managed_engine.py, browser_engine.py |
| **type-arg** | 53 | Missing generic type arguments (`dict`, `list`, `Queue`, `Task`) | browser_pool.py, base_v2.py, registry.py, selectors.py, interfaces.py |
| **arg-type** | 51 | Argument type mismatches | browser_engine.py, cloud_engine.py, api_engine.py, http_engine.py |
| **no-any-return** | 35 | Functions returning `Any` when specific type declared | base_v2.py, cloud_engine.py, managed_engine.py, api_engine.py |
| **union-attr** | 31 | Accessing attrs on `Optional`/`Union` types without guard | base_v2.py, cloud_engine.py, managed_engine.py, http_engine.py |
| **name-defined** | 17 | Undefined names (imports, forward refs) | api_engine.py, crawlee_engine.py, firecrawl_engine.py, selectors.py |
| **var-annotated** | 16 | Variables needing explicit type annotations | browser_pool.py, base_v2.py, dedup.py, template_library.py |
| **misc** | 11 | Various other issues | crawlee_engine.py, base_v2.py, interfaces.py |
| **override** | 6 | Liskov substitution principle violations | browser_engine.py, crawlee_engine.py, firecrawl_engine.py, local.py |
| **call-arg** | 6 | Call argument issues | api_engine.py, http_engine.py, selectors.py |
| **abstract** | 7 | Abstract class instantiation | cloud_engine.py, managed_engine.py, api_engine.py, http_engine.py |
| **return-value** | 5 | Return type mismatches | api_engine.py, browser_engine.py, base_v2.py |
| **operator** | 3 | Operator type issues | base_v2.py, http_engine.py, dedup.py |
| **no-redef** | 4 | Name redefinition | codegen.py, template_library.py |
| **type-abstract** | 3 | Abstract type issues | __init__.py |

**Total**: 726 errors across 50 files

---

## 4-Sprint Cleanup Schedule

### Sprint 1: Foundation Fixes (Week 1) — ~200 errors, ~7 hours

| Task | Target Errors | Files | Effort | Dependencies |
|------|---------------|-------|--------|--------------|
| Add return types to all `no-untyped-def` in `base_v2.py` | 50 | scraper/engines/base_v2.py | 2h | None |
| Fix `attr-defined` in `browser_pool.py` (MetricsCollector, BrowserContext) | 40 | scraper/engines/browser_pool.py | 2h | None |
| Add generic type args (`dict`, `list`, `Queue`, `Task`) in browser_pool, base_v2, registry | 53 | browser_pool.py, base_v2.py, registry.py | 1.5h | None |
| Fix `union-attr` guards in base_v2, cloud_engine, managed_engine | 31 | base_v2.py, cloud_engine.py, managed_engine.py | 1.5h | None |

**Sprint 1 Goal**: Core engine infrastructure fully typed

---

### Sprint 2: Engine Implementations (Week 2) — ~300 errors, ~8.5 hours

| Task | Target Errors | Files | Effort | Dependencies |
|------|---------------|-------|--------|--------------|
| cloud_engine.py: Fix config dict access, add return types, implement abstract methods | 60 | scraper/engines/cloud_engine.py | 2h | Sprint 1 |
| managed_engine.py: Fix crawlee imports, config access, implement abstract methods | 80 | scraper/engines/managed_engine.py | 2h | Sprint 1 |
| api_engine.py: Fix MockModeConfig, return types, implement abstract methods | 70 | scraper/engines/api_engine.py | 2h | Sprint 1 |
| http_engine.py: Fix config dict access, httpx client typing | 50 | scraper/engines/http_engine.py | 1.5h | Sprint 1 |
| browser_engine.py: Fix wait_until literal, InteractionResult override | 20 | scraper/engines/browser_engine.py | 1h | Sprint 1 |

**Sprint 2 Goal**: All 5 engine implementations type-safe

---

### Sprint 3: Core, Utilities & Scripts (Week 3) — ~150 errors, ~5.5 hours

| Task | Target Errors | Files | Effort | Dependencies |
|------|---------------|-------|--------|--------------|
| strategy.py: Add dict type args, fix shutdown_all call | 10 | scraper/strategy.py | 0.5h | Sprint 1 |
| api.py: Fix list append types, config access | 10 | scraper/api.py | 0.5h | Sprint 1 |
| utils/dedup.py: Fix bytes/str, xxh64, db functions | 20 | scraper/utils/dedup.py | 1h | Sprint 1 |
| utils/observability.py: Add MetricsCollector.get_success_rate() | 5 | scraper/utils/observability.py | 0.5h | Sprint 1 |
| scripts/profiler.py: Add type annotations, fix abstract engine instantiation | 30 | scripts/profiler.py | 1h | Sprint 2 |
| scripts/codegen.py: Fix imports, GeneratedScript validation type | 25 | scripts/codegen.py | 1h | Sprint 2 |
| scripts/cache.py, executor.py, validators.py, models.py: Add type annotations | 50 | scripts/*.py | 2h | Sprint 2 |

**Sprint 3 Goal**: Core utilities and script generator fully typed

---

### Sprint 4: Registry & Legacy Engines (Week 4) — ~70 errors, ~3.5 hours

| Task | Target Errors | Files | Effort | Dependencies |
|------|---------------|-------|--------|--------------|
| engines/__init__.py: Fix registry imports, EngineMetadata types | 15 | scraper/engines/__init__.py | 0.5h | Sprint 2 |
| registry.py / registry_v2.py: Fix dict type args, defaults | 15 | scraper/engines/registry*.py | 0.5h | Sprint 1 |
| local.py: Legacy Scrapy/Playwright engine typing | 20 | scraper/engines/local.py | 1h | Sprint 2 |
| crawlee_engine.py: Fix crawlee imports, async iterator override | 15 | scraper/engines/crawlee_engine.py | 1h | Sprint 2 |
| firecrawl_engine.py: Fix async iterator override, dict type args | 5 | scraper/engines/firecrawl_engine.py | 0.5h | Sprint 2 |

**Sprint 4 Goal**: All legacy and registry code type-safe

---

## CI Gate Proposal

### Phase 1: Baseline Generation (Start of Sprint 1)

```bash
# Generate baseline to track progress
mypy --strict scraper/ scripts/ --baseline-file=.mypy-baseline.json 2>&1 | tee mypy-baseline.log
```

### Phase 2: Incremental CI (Each Sprint)

```yaml
# .github/workflows/typecheck.yml
name: Type Check
on: [push, pull_request]

jobs:
  mypy:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
          cache: 'pip'
      - run: pip install -e ".[dev]"
      - name: Type check with baseline
        run: |
          mypy --strict scraper/ scripts/ \
            --baseline-file=.mypy-baseline.json \
            --show-error-codes \
            --no-error-summary
      - name: Check for new errors
        run: |
          # Fail if new errors introduced (baseline errors ignored)
          mypy --strict scraper/ scripts/ \
            --baseline-file=.mypy-baseline.json \
            --show-error-codes 2>&1 | grep -v "^.*: note:" | grep "error:" && exit 1 || exit 0
```

### Phase 3: Strict Gate (After Sprint 4)

```yaml
# .github/workflows/typecheck.yml (final)
run: mypy --strict scraper/ scripts/ --show-error-codes
# No baseline - zero errors required
```

### Local Development Helper

```bash
# scripts/check-types.sh
#!/bin/bash
set -e
echo "Running mypy with baseline..."
mypy --strict scraper/ scripts/ --baseline-file=.mypy-baseline.json "$@"
echo "✓ Type check passed (baseline errors ignored)"
```

---

## Dependencies & Ordering

```
Sprint 1 (Foundation) ──► Sprint 2 (Engines) ──► Sprint 3 (Core/Scripts) ──► Sprint 4 (Registry/Legacy)
       │                      │                        │                         │
       ▼                      ▼                        ▼                         ▼
  base_v2,                cloud, managed,          strategy, api,           __init__, registry,
  browser_pool,           api, http,               dedup, observability,   local, crawlee,
  registry types          browser                  scripts (profiler,      firecrawl
                          engine types             codegen, cache,         (optional)
                                               executor, validators)
```

**Critical Path**: Sprint 1 → Sprint 2 → Sprint 3 → Sprint 4 (sequential for core types)

**Parallelizable within sprints**: Each engine in Sprint 2 can be done independently.

---

## Definition of Done per Sprint

| Sprint | Criteria |
|--------|----------|
| **Sprint 1** | `mypy --strict scraper/engines/base_v2.py scraper/engines/browser_pool.py scraper/engines/registry.py` passes (baseline ignored) |
| **Sprint 2** | `mypy --strict scraper/engines/*_engine.py` passes for all 5 engines |
| **Sprint 3** | `mypy --strict scraper/utils/ scripts/` passes |
| **Sprint 4** | `mypy --strict scraper/engines/__init__.py scraper/engines/registry*.py scraper/engines/local.py scraper/engines/crawlee_engine.py scraper/engines/firecrawl_engine.py` passes |

**Final Gate**: `mypy --strict scraper/ scripts/` exits 0 with **no baseline**

---

## Tracking Progress

```bash
# After each sprint, update baseline
mypy --strict scraper/ scripts/ --baseline-file=.mypy-baseline.json 2>&1 | grep "Found.*errors" 

# Expected progression:
# Sprint 0: 726 errors
# Sprint 1: ~500 errors  
# Sprint 2: ~200 errors
# Sprint 3: ~50 errors
# Sprint 4: 0 errors
```

---

## Notes

- **scripts/ included**: Script generator (Option B) is in scope for production
- **Excluded**: `custom_scripts/`, `tests/`, `docs/` - not part of runtime
- **Baseline file**: Commit `.mypy-baseline.json` to track progress in git
- **Team allocation**: 2 developers can parallelize Sprint 2 (engines) and Sprint 3 (utils/scripts)

---

## Related Files

- Baseline tracking: `.mypy-baseline.json` (generated, committed)
- CI workflow: `.github/workflows/typecheck.yml` (to be created)
- Local helper: `scripts/check-types.sh` (to be created)