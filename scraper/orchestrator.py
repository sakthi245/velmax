from __future__ import annotations

import asyncio
import json
import dataclasses
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from pathlib import Path

from scraper.config import UniversalConfig, UniversalRequest, UniversalResult
from scraper.universal_runner import UniversalRunner
from scraper.scripts import ScriptGenerator, DeepSiteProfiler, ProfileDepth, GenerationRequirements
from scraper.scripts.cache import ScriptCache, CacheConfig as ScriptCacheConfig
from scraper.scripts.executor import GeneratedScriptExecutor, ExecutionConfig
from scraper.config.schemas import ExecutionMode, CachedScript, CacheEntry, OutputFormat
from scraper.failure_classifier import FailureClassifier, FailureClassification
from scraper.utils.observability import get_logger


@dataclass
class HybridOrchestrator:
    """Main entry: Option A (Universal Runner) → fallback → Option B (Script Generator)"""

    config: UniversalConfig

    def __post_init__(self):
        self.runner = UniversalRunner(self.config)
        self.generator = ScriptGenerator()
        # Translate pydantic CacheConfig (ttl_days) to dataclass CacheConfig (ttl_hours)
        pydantic_cache_config = self.config.script_generation.cache
        self.cache = ScriptCache(ScriptCacheConfig(
            cache_dir=str(pydantic_cache_config.cache_dir),
            max_entries=pydantic_cache_config.max_entries,
            ttl_hours=pydantic_cache_config.ttl_days * 24,
            enable_compression=pydantic_cache_config.enable_compression,
            max_size_mb=pydantic_cache_config.max_size_mb,
            cleanup_interval_hours=pydantic_cache_config.cleanup_interval_hours,
        ))
        self.executor = GeneratedScriptExecutor(self.config.script_generation.execution)
        self.classifier = FailureClassifier()
        self.logger = get_logger("orchestrator")

    async def scrape(self, request: UniversalRequest) -> UniversalResult:
        """Main entry: Option A → fallback → Option B"""

        # Try Option A (Universal Runner)
        try:
            result = await self.runner.scrape(request)
            return result
        except Exception as e:
            # Classify failure
            classification = self.classifier.classify(e, None, None)
            self.logger.info(f"Option A failed: {classification.category} - {classification.severity}, falling back to Option B")
            
            fallback_context = {
                "error": str(e),
                "classification": classification.__dict__,
                "timestamp": datetime.utcnow().isoformat(),
            }

        # Option B: Generate + Execute
        return await self._execute_option_b(request, fallback_context)

    async def _execute_option_b(self, request: UniversalRequest, fallback_context: Dict) -> UniversalResult:
        # Check cache (TTL + hash + manual)
        cache_key = self._cache_key(request.url, request.model_dump())
        cached = await self.cache.get(cache_key)

        if cached and not self._should_regenerate(cached, fallback_context):
            self.logger.info("Using cached script", cache_key=cache_key)
            script = cached.script
            cache_hit = True
        else:
            # Deep profile with fallback context
            profiler = DeepSiteProfiler()  # TODO: inject LLM client via stealth_config if needed
            profile = await profiler.profile(
                request.url,
                depth=ProfileDepth.DEEP,
            )

            # Generate with LLM assistance
            script = await self.generator.generate(profile, GenerationRequirements(
                engine_preference=None,
                output_formats=[OutputFormat.JSONL],
                max_pages=request.max_pages or 10,
                depth=request.depth or 0,
                use_stealth=request.engine_options.get("stealth_mode", True) if request.engine_options else True,
                use_proxy=request.use_proxy or False,
                extraction_schema=request.extract_schema,
                goal=request.goal or "",
            ))

            # Cache with metadata (convert dataclass to dict for pydantic v2 compatibility)
            script_dict = dataclasses.asdict(script)
            # Add strategy field for pydantic v2 GeneratedScript compatibility
            script_dict["strategy"] = None
            await self.cache.set(cache_key, CachedScript(
                script=script_dict,
                metadata=CacheEntry(
                    key=cache_key,
                    url=request.url,
                    profile_hash=profile.hash(),
                    script_path="",
                    created_at=datetime.utcnow().isoformat(),
                    ttl_days=self.config.script_generation.cache.ttl_days,
                ),
            ))
            cache_hit = False

        # Execute (configurable: in-process or subprocess)
        if self.config.script_generation.execution.mode == ExecutionMode.IN_PROCESS:
            result = await self.executor.run_in_process(script, request)
        else:
            result = await self.executor.run_subprocess(script, request)

        # Process output (raw → cleaned → validated → enriched → user formats)
        final_result = self._process_output(result, request, {
            "cache_hit": cache_hit,
            "script_generated": not cache_hit,
            "fallback_context": fallback_context,
        })

        # Update cache success metrics
        if final_result.success:
            await self.cache.record_success(cache_key)
        else:
            await self.cache.record_failure(cache_key)

        return final_result

    def _cache_key(self, url: str, config: Dict) -> str:
        import hashlib
        content = f"{url}{json.dumps(config, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    def _should_regenerate(self, cached: CachedScript, context: Dict) -> bool:
        # Manual invalidation check
        if context.get("force_regenerate"):
            return True
        # Failure threshold
        if cached.metadata.failure_count >= self.config.script_generation.cache.max_failures_before_regenerate:
            return True
        return False

    def _process_output(self, result: UniversalResult, request: UniversalRequest, metadata: Dict) -> UniversalResult:
        """Process through output pipeline: raw → cleaned → validated → enriched → formats"""
        from .output_pipeline import OutputPipeline
        pipeline = OutputPipeline(self.config)
        return pipeline.process(result, request, metadata)


class OrchestratorPool:
    """Parallel execution with shared cache"""

    def __init__(self, pool_size: int = 5, config: UniversalConfig = None):
        self.pool_size = pool_size
        self.config = config or UniversalConfig()
        self.semaphore = asyncio.Semaphore(pool_size)
        self.shared_cache = ScriptCache(ScriptCacheConfig())
        self.logger = get_logger("orchestrator_pool")

    async def map(self, func: callable, items: List[Any]) -> List[Any]:
        async def bounded(item):
            async with self.semaphore:
                return await func(item)

        return await asyncio.gather(*[bounded(item) for item in items])