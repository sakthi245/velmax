#!/usr/bin/env python3
"""
Universal Scraper V2 - Hybrid Architecture (Option A + Option B with Smart Fallback)
Supports: Real-time multi-engine scraping (Option A) + Script Generation (Option B) with Smart Fallback
"""

import asyncio
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field

from scraper.config import UniversalConfig, UniversalRequest, UniversalResult, OutputFormat, EngineType
from scraper.config.loader import load_config, get_low_memory_config
from scraper.universal_runner import UniversalRunner
from scraper.orchestrator import HybridOrchestrator
from scraper.scripts import ScriptGenerator, DeepSiteProfiler, ProfileDepth
from scraper.scripts.cache import ScriptCache, CacheConfig
from scraper.scripts.executor import GeneratedScriptExecutor, ExecutionConfig
from scraper.utils.observability import init_observability, get_logger
from scraper.engines.search_pipeline import SearchPipelineEngine
from scraper.engines.interfaces import EngineConfig

logger = get_logger("universal_scraper_v2")


@dataclass
class ScrapeTask:
    query: str
    urls: List[str]
    goal: str
    schema: Optional[Dict] = None
    engines: List[str] = field(default_factory=list)
    max_pages: int = 10
    output_formats: List[OutputFormat] = field(default_factory=lambda: [OutputFormat.JSONL])
    use_firecrawl: bool = True
    force_rescrape: bool = False


async def run_universal_runner(config: UniversalConfig, task: ScrapeTask) -> Any:
    """Run Option A: Universal Runner"""
    runner = UniversalRunner(config)
    request = UniversalRequest(
        url=task.urls[0] if task.urls else "",
        goal=task.goal,
        extract_schema=task.schema,
        max_pages=task.max_pages,
        output_formats=task.output_formats,
        engine=EngineType(task.engines[0]) if task.engines else None,
        force_rescrape=task.force_rescrape,
    )
    return await runner.scrape(request)


async def run_hybrid_orchestrator(config: UniversalConfig, task: ScrapeTask) -> Any:
    """Run Hybrid Orchestrator (Option A → Option B fallback)"""
    orchestrator = HybridOrchestrator(config)
    request = UniversalRequest(
        url=task.urls[0] if task.urls else "",
        goal=task.goal,
        extract_schema=task.schema,
        max_pages=task.max_pages,
        output_formats=task.output_formats,
        engine=EngineType(task.engines[0]) if task.engines else None,
        force_rescrape=task.force_rescrape,
    )
    return await orchestrator.scrape(request)


async def generate_script(config: UniversalConfig, task: ScrapeTask, depth: ProfileDepth = ProfileDepth.DEEP) -> Any:
    """Generate script (Option B)"""
    generator = ScriptGenerator()
    profiler = DeepSiteProfiler()
    profile = await profiler.profile(task.urls[0], depth=depth)
    
    from scraper.scripts import GenerationRequirements
    requirements = GenerationRequirements(
        engine_preference=EngineType(task.engines[0]) if task.engines else None,
        output_formats=[OutputFormat.JSONL],
        goal=task.goal,
    )
    
    return await generator.generate_from_profile(profile, requirements, task.goal)


async def run_generated_script(script_path: Path, request_data: Dict = None) -> Any:
    """Run generated script"""
    executor = GeneratedScriptExecutor()
    spec = importlib.util.spec_from_file_location("generated_script", script_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    
    if hasattr(module, "main"):
        if asyncio.iscoroutinefunction(module.main):
            return await module.main(request_data)
        else:
            return module.main(request_data)
    
    raise ValueError("Generated script has no main() function")


async def profile_site(url: str, depth: ProfileDepth = ProfileDepth.DEEP) -> Any:
    """Profile a site deeply"""
    profiler = DeepSiteProfiler()
    return await profiler.profile(url, depth=depth)


async def main():
    parser = argparse.ArgumentParser(
        description="Universal Scraper V2 - Hybrid Architecture (Option A + Option B) with Smart Fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Universal Runner (Option A) - Real-time scraping
  python universal_scraper_v2.py scrape --url "https://example.com" --goal "Extract products"
  
  # Hybrid Orchestrator (A → B fallback)
  python universal_scraper_v2.py scrape --url "https://example.com" --goal "Extract products" --mode auto
  
  # Generate script (Option B) - Deep profiling
  python universal_scraper_v2.py generate --url "https://example.com" --output ./my_scraper --depth deep
  
  # Run generated script
  python universal_scraper_v2.py run-script ./my_scraper --request request.json
  
  # Profile site
  python universal_scraper_v2.py profile --url "https://example.com" --depth deep
        """
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Scrape command
    scrape_parser = subparsers.add_parser("scrape", help="Scrape URL(s) using Universal Runner or Hybrid Orchestrator")
    scrape_parser.add_argument("--url", action="append", help="URL to scrape (can repeat, optional if --discover-urls is used)")
    scrape_parser.add_argument("--goal", required=True, help="Extraction goal/instruction")
    scrape_parser.add_argument("--schema", help="JSON schema for structured extraction")
    scrape_parser.add_argument("--schema-file", help="Path to JSON schema file")
    scrape_parser.add_argument("--max-pages", type=int, default=10, help="Max pages per URL")
    scrape_parser.add_argument("--engine", action="append", help="Force specific engine(s)")
    scrape_parser.add_argument("--output-format", action="append", choices=[f.value for f in OutputFormat], default=[OutputFormat.JSONL], help="Output format")
    scrape_parser.add_argument("--output-dir", default="./output", help="Output directory")
    scrape_parser.add_argument("--mode", choices=["auto", "runner_only", "generate_only"], default="auto", help="Execution mode")
    scrape_parser.add_argument("--fallback-threshold", type=float, default=0.7, help="Quality threshold for fallback")
    scrape_parser.add_argument("--cache-dir", default="./scripts_cache", help="Script cache directory")
    scrape_parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO", help="Log level")
    scrape_parser.add_argument("--discover-urls", action="store_true", help="Automatically discover URLs based on goal using search engines")
    scrape_parser.add_argument("--max-discovered-urls", type=int, default=5, help="Maximum URLs to discover when using --discover-urls")
    scrape_parser.add_argument("--discover-depth", choices=[d.value for d in ProfileDepth], default="quick", help="Depth of URL discovery profiling")
    scrape_parser.add_argument("--force-rescrape", action="store_true", help="Force re-scraping even if URL was previously scraped (bypass deduplication)")
    
    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate optimized scraper script (Option B)")
    gen_parser.add_argument("--url", required=True, help="URL to profile and generate script for")
    gen_parser.add_argument("--goal", help="Extraction goal")
    gen_parser.add_argument("--output", required=True, help="Output directory for generated script")
    gen_parser.add_argument("--engine", choices=[e.value for e in EngineType], help="Force specific engine")
    gen_parser.add_argument("--depth", choices=[d.value for d in ProfileDepth], default="deep", help="Profile depth")
    gen_parser.add_argument("--template-dir", help="Custom template directory")
    
    # Run script command
    run_parser = subparsers.add_parser("run-script", help="Run generated script")
    run_parser.add_argument("script_path", help="Path to generated script")
    run_parser.add_argument("--request", help="Request JSON file")
    run_parser.add_argument("--output-format", choices=[f.value for f in OutputFormat], default=OutputFormat.JSONL)
    
    # Profile command
    profile_parser = subparsers.add_parser("profile", help="Deep profile a site")
    profile_parser.add_argument("--url", required=True, help="URL to profile")
    profile_parser.add_argument("--depth", choices=[d.value for d in ProfileDepth], default="deep")
    profile_parser.add_argument("--output", help="Output file for profile")
    
    # Global options
    parser.add_argument("--config", help="Config YAML file")
    parser.add_argument("--engines-config", help="Engines YAML file")
    parser.add_argument("--low-memory", action="store_true", help="Use low-memory preset (for 8GB/6GB Docker)")
    parser.add_argument("--log-level", choices=["DEBUG", "INFO", "WARNING", "ERROR"], default="INFO")
    
    args = parser.parse_args()
    
    # Initialize observability
    init_observability(log_level=args.log_level)
    
    # Load configuration
    if args.low_memory:
        config = get_low_memory_config()
        logger.info("Using low-memory configuration preset")
    else:
        config = load_config(args.config, args.engines_config, args)
    
    # Override config with CLI args
    if hasattr(args, 'output_dir') and args.output_dir:
        config.output_dir = args.output_dir
    elif hasattr(args, 'output') and args.output:
        config.output_dir = Path(args.output)
    if hasattr(args, 'fallback_threshold') and args.fallback_threshold:
        config.fallback.quality_threshold = args.fallback_threshold
    if hasattr(args, 'cache_dir') and args.cache_dir:
        config.script_generation.cache.cache_dir = Path(args.cache_dir)
    
    # Parse schema
    schema = None
    if hasattr(args, 'schema_file') and args.schema_file:
        with open(args.schema_file) as f:
            schema = json.load(f)
    elif hasattr(args, 'schema') and args.schema:
        schema = json.loads(args.schema)
    
    # Parse output formats
    if hasattr(args, 'output_format') and args.output_format:
        output_formats = [OutputFormat(f) for f in args.output_format]
    else:
        output_formats = [OutputFormat.JSONL]
    
    # Parse engine types
    engines = [EngineType(e) for e in args.engine] if hasattr(args, 'engine') and args.engine else []
    
    try:
        if args.command == "scrape":
            # Handle automatic URL discovery
            urls = list(args.url) if args.url else []
            
            if args.discover_urls and not urls:
                logger.info("Discovering URLs based on goal using search engines...")
                
                # Get engine configs from config (some may be nested under engines)
                engines_cfg = getattr(config, 'engines', {})
                
                # Helper to get config from top-level or engines dict
                def get_engine_cfg(config_obj, engines_dict, name):
                    # Try top-level attribute first
                    attr = getattr(config_obj, name, None)
                    if attr is not None and hasattr(attr, 'api_key') and attr.api_key:
                        return attr.model_dump()
                    # Fall back to engines dict
                    cfg = engines_dict.get(name, {}) if isinstance(engines_dict, dict) else {}
                    return cfg if isinstance(cfg, dict) else {}
                
                tinyfish_cfg = get_engine_cfg(config, engines_cfg, 'tinyfish_search')
                serpapi_cfg = get_engine_cfg(config, engines_cfg, 'serpapi_search')
                query_expander_cfg = get_engine_cfg(config, engines_cfg, 'query_expander')
                relevance_ranker_cfg = get_engine_cfg(config, engines_cfg, 'relevance_ranker')
                
                search_pipeline = SearchPipelineEngine()
                await search_pipeline.initialize(EngineConfig(
                    name="search_pipeline",
                    config={
                        "search_pipeline": {
                            "enable_query_expansion": True,
                            "enable_relevance_ranking": True,
                            "max_queries_per_goal": 3,
                            "max_results_per_query": 10,
                            "tinyfish_search": tinyfish_cfg,
                            "serpapi_search": serpapi_cfg,
                            "query_expander": query_expander_cfg,
                            "relevance_ranker": relevance_ranker_cfg,
                        }
                    }
                ))
                
                urls = await search_pipeline.discover_urls(args.goal, max_urls=args.max_discovered_urls)
                logger.info(f"Discovered {len(urls)} URLs: {urls}")
                
                if not urls:
                    logger.warning("No URLs discovered, using default search")
                    urls = [f"https://www.google.com/search?q={args.goal.replace(' ', '+')}"]
            
            task = ScrapeTask(
                query=args.goal or "Extract data",
                urls=urls,
                goal=args.goal or "Extract all relevant information",
                schema=schema,
                engines=[e.value for e in engines] if engines else None,
                max_pages=args.max_pages,
                output_formats=output_formats,
                force_rescrape=args.force_rescrape,
            )
            
            if args.mode == "runner_only":
                result = await run_universal_runner(config, task)
            elif args.mode == "generate_only":
                result = await generate_script(config, task)
            else:
                result = await run_hybrid_orchestrator(config, task)
            
            # Print result
            print(f"\n{'='*60}")
            print("SCRAPE RESULT")
            print(f"{'='*60}")
            print(f"Success: {result.success}")
            print(f"Engine: {result.engine_used}")
            print(f"Quality Score: {result.quality_score:.2f}")
            print(f"Output Files: {result.formatted_outputs}")
            if result.error:
                print(f"Error: {result.error}")
            
        elif args.command == "generate":
            script = await generate_script(config, ScrapeTask(
                query=args.goal or "Extract data",
                urls=[args.url],
                goal=args.goal or "Extract all relevant information",
            ), depth=ProfileDepth(args.depth))
            
            # Write generated files
            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            (output_dir / "main.py").write_text(script.main_code)
            (output_dir / "config.py").write_text(script.config_code)
            (output_dir / "test.py").write_text(script.test_code)
            (output_dir / "requirements.txt").write_text(script.requirements_code)
            
            print(f"Generated script at: {args.output}")
            print(f"Validation: {'PASSED' if script.validation.passed else 'FAILED'}")
            print(f"Estimated Success Rate: {script.validation.success_probability:.1%}")
            
        elif args.command == "run-script":
            script_path = Path(args.script_path)
            request_data = None
            if args.request:
                with open(args.request) as f:
                    request_data = json.load(f)
            
            result = await run_generated_script(Path(args.script_path), request_data)
            print(json.dumps(result, indent=2, default=str))
        
        elif args.command == "profile":
            profile = await profile_site(args.url, ProfileDepth(args.depth))
            if args.output:
                with open(args.output, "w") as f:
                    json.dump(profile.__dict__, f, indent=2, default=str)
            else:
                print(json.dumps(profile.__dict__, indent=2, default=str))
        
        else:
            parser.print_help()
    
    except Exception as e:
        logger.error(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    import importlib.util
    asyncio.run(main())