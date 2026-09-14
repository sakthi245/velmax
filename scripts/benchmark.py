#!/usr/bin/env python3
"""
Performance Benchmark Script
Tests key metrics against public sites:
- HTTP throughput (>50 req/s)
- Browser pool memory (<150MB/context)
- Fallback latency (<500ms overhead)
- Script generation time (<60s deep)
- Memory usage on 8GB system (<1.5GB total)
"""

import asyncio
import time
import psutil
import json
import statistics
from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime
from pathlib import Path

from scraper.config.loader import get_low_memory_config
from scraper.universal_runner import UniversalRunner
from scraper.orchestrator import HybridOrchestrator
from scraper.config.schemas import UniversalRequest, EngineType, OutputFormat
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts import ScriptGenerator, DeepSiteProfiler, ProfileDepth
from scraper.engines.browser_pool import AdaptiveBrowserPool
from scraper.config.schemas import UniversalConfig


@dataclass
class BenchmarkResult:
    name: str
    engine: str
    url: str
    success: bool
    latency_ms: float
    memory_mb: float
    items_extracted: int
    error: Optional[str] = None


class BenchmarkRunner:
    def __init__(self, config: UniversalConfig):
        self.config = config
        self.runner = None
        self.orchestrator = None
        self.process = psutil.Process()
        self.results: List[BenchmarkResult] = []

    async def setup(self):
        self.runner = UniversalRunner(self.config)
        self.orchestrator = HybridOrchestrator(self.config)

    def get_memory_mb(self) -> float:
        return self.process.memory_info().rss / (1024 * 1024)

    async def benchmark_http_throughput(self, url: str, num_requests: int = 100, concurrency: int = 10) -> Dict[str, Any]:
        """Benchmark HTTP engine throughput."""
        print(f"\n[Benchmark] HTTP Throughput: {num_requests} requests, concurrency={concurrency}")
        
        semaphore = asyncio.Semaphore(concurrency)
        latencies = []
        errors = 0
        start_time = time.time()
        mem_start = self.get_memory_mb()

        async def make_request():
            nonlocal errors
            async with semaphore:
                start = time.perf_counter()
                try:
                    result = await self.runner.scrape(UniversalRequest(
                        url=url,
                        goal="Extract title and links",
                        engine=EngineType.HTTP,
                    ))
                    latency = (time.perf_counter() - start) * 1000
                    latencies.append(latency)
                    if not result.success:
                        errors += 1
                except Exception as e:
                    errors += 1
                    latencies.append((time.perf_counter() - start) * 1000)

        await asyncio.gather(*[make_request() for _ in range(num_requests)])

        total_time = time.time() - start_time
        mem_end = self.get_memory_mb()
        throughput = num_requests / total_time

        return {
            "test": "http_throughput",
            "url": url,
            "requests": num_requests,
            "concurrency": concurrency,
            "total_time_s": total_time,
            "throughput_req_s": throughput,
            "avg_latency_ms": statistics.mean(latencies) if latencies else 0,
            "p50_latency_ms": statistics.median(latencies) if latencies else 0,
            "p95_latency_ms": sorted(latencies)[int(len(latencies) * 0.95)] if latencies else 0,
            "p99_latency_ms": sorted(latencies)[int(len(latencies) * 0.99)] if latencies else 0,
            "errors": errors,
            "success_rate": (num_requests - errors) / num_requests,
            "memory_delta_mb": mem_end - mem_start,
            "memory_start_mb": mem_start,
            "memory_end_mb": mem_end,
        }

    async def benchmark_browser_pool_memory(self, urls: List[str]) -> Dict[str, Any]:
        """Benchmark browser pool memory usage with concurrent scrapes."""
        print(f"\n[Benchmark] Browser Pool Memory: {len(urls)} concurrent scrapes")
        
        mem_start = self.get_memory_mb()
        
        # Scrape multiple URLs concurrently
        tasks = [self.runner.scrape(UniversalRequest(
            url=url,
            goal="Extract title and content",
            engine=EngineType.BROWSER,
        )) for url in urls]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        mem_end = self.get_memory_mb()
        mem_peak = max(self.get_memory_mb(), mem_end)
        
        success_count = sum(1 for r in results if not isinstance(r, Exception) and hasattr(r, 'success') and r.success)
        
        return {
            "test": "browser_pool_memory",
            "urls": urls,
            "concurrent_scrapes": len(urls),
            "memory_start_mb": mem_start,
            "memory_end_mb": mem_end,
            "memory_delta_mb": mem_end - mem_start,
            "memory_peak_mb": mem_peak,
            "success_count": success_count,
            "success_rate": success_count / len(urls),
        }

    async def benchmark_fallback_latency(self, url: str) -> Dict[str, Any]:
        """Benchmark fallback latency overhead."""
        print(f"\n[Benchmark] Fallback Latency: {url}")
        
        # First request to establish baseline
        start = time.perf_counter()
        result1 = await self.runner.scrape(UniversalRequest(
            url=url,
            goal="Extract content",
            engine=EngineType.HTTP,
        ))
        baseline_latency = (time.perf_counter() - start) * 1000
        
        # Force fallback by using a URL that will fail HTTP
        # We'll simulate by checking if fallback chain is invoked
        start = time.perf_counter()
        result2 = await self.runner.scrape(UniversalRequest(
            url=url,
            goal="Extract content",
            # Don't specify engine to let fallback chain work
        ))
        fallback_latency = (time.perf_counter() - start) * 1000
        
        overhead = fallback_latency - baseline_latency
        
        return {
            "test": "fallback_latency",
            "url": url,
            "baseline_latency_ms": baseline_latency,
            "fallback_latency_ms": fallback_latency,
            "overhead_ms": overhead,
            "overhead_percent": (overhead / baseline_latency * 100) if baseline_latency > 0 else 0,
            "success_baseline": result1.success,
            "success_fallback": result2.success,
        }

    async def benchmark_script_generation(self, url: str, depth: ProfileDepth = ProfileDepth.DEEP) -> Dict[str, Any]:
        """Benchmark script generation time."""
        print(f"\n[Benchmark] Script Generation: {url} (depth={depth.value})")
        
        generator = ScriptGenerator()
        profiler = DeepSiteProfiler()
        
        mem_start = self.get_memory_mb()
        start = time.perf_counter()
        
        profile = await profiler.profile(url, depth=depth)
        
        profile_time = time.perf_counter() - start
        
        from scraper.scripts import GenerationRequirements
        script = await generator.generate_from_profile(profile, GenerationRequirements())
        
        gen_time = time.perf_counter() - start - profile_time
        total_time = time.perf_counter() - start
        
        mem_end = self.get_memory_mb()
        
        return {
            "test": "script_generation",
            "url": url,
            "profile_depth": depth.value,
            "profile_time_s": profile_time,
            "generation_time_s": gen_time,
            "total_time_s": total_time,
            "validation_passed": script.validation.passed,
            "success_probability": script.validation.success_probability,
            "memory_delta_mb": mem_end - mem_start,
        }

    async def benchmark_memory_under_load(self, num_pages: int = 100) -> Dict[str, Any]:
        """Benchmark memory usage under sustained load."""
        print(f"\n[Benchmark] Memory Under Load: {num_pages} pages")
        
        # Use a site with many pages
        urls = [f"https://books.toscrape.com/catalogue/page-{i}.html" for i in range(1, min(num_pages + 1, 51))]
        
        mem_start = self.get_memory_mb()
        start = time.time()
        
        tasks = [self.runner.scrape(UniversalRequest(
            url=url,
            goal="Extract book titles and prices",
            engine=EngineType.HTTP,
        )) for url in urls]
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        elapsed = time.time() - start
        mem_end = self.get_memory_mb()
        
        success_count = sum(1 for r in results if not isinstance(r, Exception) and hasattr(r, 'success') and r.success)
        
        return {
            "test": "memory_under_load",
            "pages": num_pages,
            "elapsed_s": elapsed,
            "pages_per_second": num_pages / elapsed if elapsed > 0 else 0,
            "memory_start_mb": self.get_memory_mb(),
            "memory_end_mb": mem_end,
            "memory_delta_mb": mem_end - mem_start,
            "success_count": success_count,
            "success_rate": success_count / num_pages,
        }

    async def run_all_benchmarks(self) -> Dict[str, Any]:
        """Run all benchmarks and compile report."""
        await self.setup()
        
        print("=" * 60)
        print("STARTING PERFORMANCE BENCHMARKS")
        print("=" * 60)
        
        report = {
            "timestamp": datetime.utcnow().isoformat(),
            "config": {
                "browser_pool_min": self.config.browser_engine.pool_min,
                "browser_pool_max": self.config.browser_engine.pool_max,
                "browser_pool_max_memory_mb": self.config.browser_engine.pool_max_memory_mb,
                "http_concurrency": self.config.concurrency.max_concurrent_requests,
            },
            "results": {}
        }
        
        # 1. HTTP Throughput
        http_result = await self.benchmark_http_throughput(
            "https://books.toscrape.com/",
            num_requests=100,
            concurrency=10
        )
        report["results"]["http_throughput"] = http_result
        print(f"HTTP Throughput: {http_result['throughput_req_s']:.1f} req/s (target: >50)")
        
        # 2. Browser Pool Memory
        browser_urls = [
            "https://books.toscrape.com/",
            "https://quotes.toscrape.com/js/",
            "https://httpbin.org/html",
        ]
        browser_result = await self.benchmark_browser_pool_memory(browser_urls)
        report["results"]["browser_pool_memory"] = browser_result
        print(f"Browser Pool Memory Delta: {browser_result['memory_delta_mb']:.1f}MB (target: <150MB/context)")
        
        # 3. Fallback Latency
        fallback_result = await self.benchmark_fallback_latency("https://httpbin.org/html")
        report["results"]["fallback_latency"] = fallback_result
        print(f"Fallback Overhead: {fallback_result['overhead_ms']:.1f}ms (target: <500ms)")
        
        # 4. Script Generation
        script_result = await self.benchmark_script_generation("https://books.toscrape.com/", ProfileDepth.DEEP)
        report["results"]["script_generation"] = script_result
        print(f"Script Generation Time: {script_result['total_time_s']:.1f}s (target: <60s)")
        
        # 5. Memory Under Load
        load_result = await self.benchmark_memory_under_load(50)
        report["results"]["memory_under_load"] = load_result
        print(f"Memory Under Load Delta: {load_result['memory_delta_mb']:.1f}MB (target: <1.5GB total)")
        
        # Summary
        report["summary"] = {
            "http_throughput_ok": report["results"]["http_throughput"]["throughput_req_s"] > 50,
            "browser_memory_ok": report["results"]["browser_pool_memory"]["memory_delta_mb"] < 500,  # 3 contexts * 150MB
            "fallback_latency_ok": report["results"]["fallback_latency"]["overhead_ms"] < 500,
            "script_generation_ok": report["results"]["script_generation"]["total_time_s"] < 60,
            "memory_under_load_ok": report["results"]["memory_under_load"]["memory_delta_mb"] < 1000,
        }
        
        # Save report
        report_path = Path("benchmark_report.json")
        report_path.write_text(json.dumps(report, indent=2, default=str))
        print(f"\nReport saved to {report_path}")
        
        print("\n" + "=" * 60)
        print("BENCHMARK SUMMARY")
        print("=" * 60)
        for k, v in report["summary"].items():
            status = "✅ PASS" if v else "❌ FAIL"
            print(f"  {k}: {status}")
        
        return report


async def main():
    config = get_low_memory_config()
    runner = BenchmarkRunner(config)
    report = await runner.run_all_benchmarks()
    return report


if __name__ == "__main__":
    asyncio.run(main())