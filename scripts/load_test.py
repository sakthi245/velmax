#!/usr/bin/env python3
"""
Load testing and benchmarking script for the hybrid web scraper.
"""

import argparse
import asyncio
import json
import statistics
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scraper.universal_runner import UniversalRunner
from scraper.config.schemas import UniversalConfig, UniversalRequest
from scraper.config import load_config


@dataclass
class BenchmarkResult:
    """Results from a benchmark run."""
    name: str
    url: str
    total_requests: int
    successful_requests: int
    failed_requests: int
    total_time: float
    requests_per_second: float
    latency_ms: List[float]
    errors: List[str]
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class LoadTester:
    """Load testing utility for the scraper."""
    
    def __init__(self, config: UniversalConfig = None):
        if config is None:
            from scraper.config.schemas import ObservabilityConfig
            config = UniversalConfig(
                observability=ObservabilityConfig()
            )
        self.config = config
        self.runner = UniversalRunner(config)
        self.results: List[BenchmarkResult] = []
    
    async def run_benchmark(
        self,
        url: str,
        goal: str,
        num_requests: int = 100,
        concurrency: int = 10,
        engine: str = "auto",
    ) -> BenchmarkResult:
        """Run a load test against a URL."""
        
        latencies = []
        errors = []
        successful = 0
        failed = 0
        start_time = time.time()
        
        semaphore = asyncio.Semaphore(10)  # Limit concurrent requests
        
        async def make_request(url: str) -> tuple:
            """Make a single request and return (latency, error)."""
            async with semaphore:
                start = time.time()
                try:
                    request = UniversalRequest(
                        url=url,
                        goal="Extract page content",
                        engine=engine if engine != "auto" else None,
                    )
                    result = await self.runner.scrape(request)
                    latency = (time.time() - start) * 1000
                    if result.success:
                        return latency, None
                    else:
                        return latency, result.error or "Unknown error"
                except Exception as e:
                    latency = (time.time() - start) * 1000
                    return latency, str(e)
        
        # Run with limited concurrency using semaphore
        semaphore = asyncio.Semaphore(10)
        
        async def make_request_limited(url: str) -> tuple:
            async with semaphore:
                return await make_request(url)
        
        # Create tasks with semaphore
        tasks = [make_request_limited(url) for _ in range(num_requests)]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Process results
        latencies = []
        errors = []
        for result in results:
            if isinstance(result, Exception):
                error_msg = str(result)
                errors.append(error_msg)
                failed += 1
                print(f"  ERROR: {error_msg}")
            else:
                latency, error = result
                if error:
                    errors.append(error)
                    failed += 1
                    print(f"  ERROR: {error}")
                else:
                    latencies.append(latency)
                    successful += 1
        
        total_time = time.time() - start_time
        
        return BenchmarkResult(
            name=f"benchmark_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            url=url,
            total_requests=num_requests,
            successful_requests=successful,
            failed_requests=failed,
            total_time=time.time() - start_time,
            requests_per_second=successful / total_time if total_time > 0 else 0,
            latency_ms=latencies,
            errors=errors,
        )
    
    async def run_benchmark_suite(self, urls: List[Dict[str, Any]]) -> List[BenchmarkResult]:
        """Run benchmarks for multiple URLs."""
        results = []
        for item in urls:
            url = item["url"]
            goal = item.get("goal", "Extract page content")
            num_requests = item.get("num_requests", 100)
            concurrency = item.get("concurrency", 10)
            engine = item.get("engine", "auto")
            
            print(f"\nRunning benchmark for {url}...")
            result = await self.run_benchmark(
                url=url,
                goal=goal,
                num_requests=num_requests,
                concurrency=concurrency,
                engine=engine,
            )
            results.append(result)
            print(f"  Completed: {result.successful_requests}/{result.total_requests} successful")
            print(f"  RPS: {result.requests_per_second:.2f}")
            print(f"  Avg latency: {statistics.mean(result.latency_ms):.2f}ms")
            if result.errors:
                print(f"  Errors: {len(result.errors)}")
        
        return results
    
    def print_summary(self, results: List[BenchmarkResult]):
        """Print benchmark summary."""
        print("\n" + "="*60)
        print("BENCHMARK SUMMARY")
        print("="*60)
        
        total_requests = sum(r.total_requests for r in self.results)
        total_successful = sum(r.successful_requests for r in self.results)
        total_failed = sum(r.failed_requests for r in self.results)
        total_time = sum(r.total_time for r in self.results)
        
        all_latencies = []
        for r in self.results:
            all_latencies.extend(r.latency_ms)
        
        print(f"\nTotal Requests: {total_requests}")
        print(f"Successful: {total_successful}")
        print(f"Failed: {total_failed}")
        print(f"Success Rate: {total_successful/max(1,total_requests)*100:.1f}%")
        print(f"Total Time: {total_time:.2f}s")
        print(f"Overall RPS: {total_successful/max(1,sum(r.total_time for r in self.results)):.2f}")
        
        if all_latencies:
            print(f"\nLatency Percentiles:")
            print(f"  p50: {statistics.median(all_latencies):.2f}ms")
            print(f"  p90: {statistics.quantiles(all_latencies, n=10)[8]:.2f}ms")
            print(f"  p95: {statistics.quantiles(all_latencies, n=20)[18]:.2f}ms")
            print(f"  p99: {statistics.quantiles(all_latencies, n=100)[98]:.2f}ms")
            print(f"  Max: {max(all_latencies):.2f}ms")
        
        # Per-URL breakdown
        print("\nPer-URL Results:")
        for r in self.results:
            print(f"\n  {r.url}")
            print(f"    Requests: {r.successful_requests}/{r.total_requests}")
            print(f"    RPS: {r.requests_per_second:.2f}")
            if r.latency_ms:
                print(f"    Latency: avg={statistics.mean(r.latency_ms):.0f}ms, "
                      f"p95={statistics.quantiles(r.latency_ms, n=20)[18]:.0f}ms")
            if r.errors:
                print(f"    Errors: {len(r.errors)}")


async def run_load_test():
    """Run the load test with predefined scenarios."""
    
    test_scenarios = [
        {
            "url": "https://httpbin.org/html",
            "goal": "Extract page content",
            "num_requests": 50,
            "concurrency": 10,
            "engine": "http",
        },
        {
            "url": "https://httpbin.org/html",
            "goal": "Extract page content",
            "num_requests": 50,
            "concurrency": 10,
            "engine": "browser",
        },
    ]
    
    print("Starting load test...")
    tester = LoadTester()
    results = await tester.run_benchmark_suite(test_scenarios)
    tester.results = results
    tester.print_summary(results)
    
    # Save results
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"benchmark_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    
    with open(filename, 'w') as f:
        json.dump({
            "timestamp": datetime.now().isoformat(),
            "results": [
                {
                    "name": r.name,
                    "url": r.url,
                    "total_requests": r.total_requests,
                    "successful_requests": r.successful_requests,
                    "failed_requests": r.failed_requests,
                    "total_time": r.total_time,
                    "requests_per_second": r.requests_per_second,
                    "latency_ms": r.latency_ms,
                    "errors": r.errors,
                    "timestamp": r.timestamp,
                }
                for r in results
            ]
        }, f, indent=2)
    
    print(f"\nResults saved to {filename}")
    return results


async def run_benchmark(
    url: str,
    num_requests: int = 100,
    concurrency: int = 10,
    engine: str = "auto",
    goal: str = "Extract page content",
):
    """Run a single benchmark."""
    tester = LoadTester()
    return await tester.run_benchmark(url, goal, num_requests, concurrency, engine)


def run_benchmark(
    url: str,
    num_requests: int = 100,
    concurrency: int = 10,
    engine: str = "auto",
    goal: str = "Extract page content",
):
    """Run a single benchmark."""
    async def _run():
        tester = LoadTester()
        return await tester.run_benchmark(url, goal, num_requests, concurrency, engine)
    
    try:
        return asyncio.run(_run())
    except RuntimeError as e:
        if "cannot be called from a running event loop" in str(e):
            # Already in an event loop, run the coroutine directly
            loop = asyncio.get_event_loop()
            return loop.run_until_complete(_run())
        raise


def benchmark_engines():
    """Compare engine performance."""
    urls = [
        "https://httpbin.org/html",
        "https://httpbin.org/links/10",
    ]
    
    engines = ["http", "browser", "managed"]
    
    async def _run():
        tester = LoadTester()
        results = []
        
        for url in urls:
            for engine in ["http", "browser", "managed"]:
                print(f"\nTesting {url} with {engine} engine...")
                try:
                    result = await tester.run_benchmark(
                        url=url,
                        goal="Extract page content",
                        num_requests=20,
                        concurrency=5,
                        engine=engine,
                    )
                    results.append({
                        "url": url,
                        "engine": engine,
                        "result": result,
                    })
                    print(f"  {engine}: {result.successful_requests}/{result.total_requests} "
                          f"({result.requests_per_second:.2f} RPS)")
                except Exception as e:
                    print(f"  {engine}: FAILED - {e}")
        
        # Print comparison
        print("\n" + "="*60)
        print("ENGINE COMPARISON")
        print("="*60)
        for url in urls:
            print(f"\n{url}:")
            for engine in ["http", "browser", "managed"]:
                r = next((r for r in results if r["url"] == url and r["engine"] == engine), None)
                if r and r["result"]:
                    r = r["result"]
                    print(f"  {engine}: {r.successful_requests}/{r.total_requests} "
                          f"({r.requests_per_second:.2f} RPS, "
                          f"avg={statistics.mean(r.latency_ms):.0f}ms)")
    
    asyncio.run(_run())


def main():
    parser = argparse.ArgumentParser(description="Load testing for hybrid web scraper")
    parser.add_argument("--url", help="URL to test")
    parser.add_argument("--requests", type=int, default=100, help="Number of requests")
    parser.add_argument("--concurrency", type=int, default=10, help="Concurrent requests")
    parser.add_argument("--engine", choices=["auto", "http", "browser", "managed"], default="auto")
    parser.add_argument("--goal", default="Extract page content")
    parser.add_argument("--suite", action="store_true", help="Run full benchmark suite")
    parser.add_argument("--compare-engines", action="store_true", help="Compare engine performance")
    
    args = parser.parse_args()
    
    if args.suite:
        run_benchmark_suite()
    elif args.compare_engines:
        benchmark_engines()
    elif args.url:
        result = run_benchmark(args.url, args.requests, args.concurrency, args.engine, args.goal)
        if asyncio.iscoroutine(result):
            result = asyncio.run(result)
        print(f"\nBenchmark Results for {args.url}:")
        print(f"  Requests: {result.successful_requests}/{result.total_requests}")
        print(f"  RPS: {result.requests_per_second:.2f}")
        if result.latency_ms:
            print(f"  Avg Latency: {statistics.mean(result.latency_ms):.0f}ms")
            print(f"  p95: {statistics.quantiles(result.latency_ms, n=20)[18]:.0f}ms")
        if result.errors:
            print(f"  Errors: {len(result.errors)}")
    else:
        print("Please specify --url, --suite, or --compare-engines")
        parser.print_help()


if __name__ == "__main__":
    main()