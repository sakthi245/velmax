#!/usr/bin/env python3
"""Script Generation CLI - Standalone command for generating production-ready scraper scripts.

Usage:
    python -m scripts.cli generate --target URL --goal GOAL [options]
    python -m scripts.cli generate-from-profile --profile-file FILE [options]
    python -m scripts.cli validate --script-file FILE
    python -m scripts.cli list-templates
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Optional

from scraper.config.schemas import (
    GenerationRequirements,
    EngineType,
    OutputFormat,
    ProfileDepth,
)
from scripts.codegen import ScriptGenerator
from scripts.cache import ScriptCache, CacheConfig
from scripts.validators import validate_generated_script

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Universal Scraper Script Generator",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    
    subparsers = parser.add_subparsers(dest="command", required=True, help="Command to run")
    
    # generate command
    gen_parser = subparsers.add_parser("generate", help="Generate scraper script from URL")
    gen_parser.add_argument("--target", required=True, help="Target URL to generate scraper for")
    gen_parser.add_argument("--goal", required=True, help="Extraction goal (e.g., 'Extract product listings')")
    gen_parser.add_argument("--output", required=True, help="Output directory for generated script")
    gen_parser.add_argument("--engine", choices=[e.value for e in EngineType], help="Force specific engine")
    gen_parser.add_argument("--depth", choices=[d.value for d in ProfileDepth], default=ProfileDepth.DEEP.value, help="Profile depth")
    gen_parser.add_argument("--output-formats", nargs="+", choices=[f.value for f in OutputFormat], default=["jsonl"], help="Output formats")
    gen_parser.add_argument("--enrichment-steps", nargs="+", default=[], help="Enrichment steps")
    gen_parser.add_argument("--force-regenerate", action="store_true", help="Force regeneration even if cached")
    gen_parser.add_argument("--no-cache", action="store_true", help="Skip cache")
    gen_parser.add_argument("--cache-dir", type=Path, default=Path("./scripts_cache"), help="Cache directory")
    gen_parser.add_argument("--template-dir", type=Path, help="Custom template directory")
    gen_parser.add_argument("--llm-model", default="groq/compound", help="LLM model for analysis")
    
    # generate-from-profile command
    profile_parser = subparsers.add_parser("generate-from-profile", help="Generate script from existing profile JSON")
    profile_parser.add_argument("--profile-file", required=True, type=Path, help="Path to DeepSiteProfile JSON file")
    profile_parser.add_argument("--output", required=True, type=Path, help="Output directory")
    profile_parser.add_argument("--engine", choices=[e.value for e in EngineType], help="Force specific engine")
    profile_parser.add_argument("--output-formats", nargs="+", choices=[f.value for f in OutputFormat], default=["jsonl"])
    profile_parser.add_argument("--enrichment-steps", nargs="+", default=[])
    
    # validate command
    validate_parser = subparsers.add_parser("validate", help="Validate a generated script")
    validate_parser.add_argument("--script-file", required=True, type=Path, help="Path to generated script JSON")
    
    # list-templates command
    list_parser = subparsers.add_parser("list-templates", help="List available templates")
    
    # cache management
    cache_parser = subparsers.add_parser("cache", help="Cache management")
    cache_subparsers = cache_parser.add_subparsers(dest="cache_command")
    
    cache_clear = cache_subparsers.add_parser("clear", help="Clear script cache")
    cache_clear.add_argument("--cache-dir", type=Path, default=Path("./scripts_cache"))
    
    cache_stats = cache_subparsers.add_parser("stats", help="Show cache statistics")
    cache_stats.add_argument("--cache-dir", type=Path, default=Path("./scripts_cache"))
    
    return parser.parse_args()


async def cmd_generate(args: argparse.Namespace) -> int:
    """Generate scraper script from URL."""
    
    # Setup requirements
    requirements = GenerationRequirements(
        engine_preference=EngineType(args.engine) if args.engine else None,
        output_formats=[OutputFormat(f) for f in args.output_formats],
        enrichment_steps=args.enrichment_steps,
    )
    
    # Setup generator
    generator = ScriptGenerator(
        template_dir=args.template_dir,
    )
    
    # Setup cache
    cache = None
    if not args.no_cache:
        cache_config = CacheConfig(
            cache_dir=args.cache_dir,
            ttl_days=7,
            change_detection=True,
            max_failures_before_regenerate=3,
        )
        cache = ScriptCache(cache_config)
    
    try:
        logger.info(f"Generating script for {args.target}")
        
        # Check cache first
        if cache:
            from scraper.config.schemas import DeepSiteProfile
            profile = await generator.profiler.profile(args.target, depth=ProfileDepth(args.depth))
            cache_key = profile.hash()
            cached = await cache.get(cache_key)
            if cached and not args.force_regenerate:
                if not cache._should_regenerate(cached, {}):
                    logger.info("Using cached script")
                    script = cached.script
                else:
                    script = await generator.generate(args.target, requirements, depth=ProfileDepth(args.depth))
            else:
                script = await generator.generate(args.target, requirements, depth=ProfileDepth(args.depth))
        else:
            script = await generator.generate(args.target, requirements, depth=ProfileDepth(args.depth))
        
        # Save output
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Write main script
        (output_dir / "scraper.py").write_text(script.main_code)
        (output_dir / "config.py").write_text(script.config_code)
        (output_dir / "test_scraper.py").write_text(script.test_code)
        (output_dir / "requirements.txt").write_text(script.requirements_code)
        
        # Write metadata
        metadata = {
            "strategy": {
                "engine": script.strategy.engine.value,
                "template": script.strategy.template,
                "confidence": script.strategy.confidence,
                "reasoning": script.strategy.reasoning,
            },
            "validation": {
                "passed": script.validation.passed,
                "lint_errors": script.validation.lint_errors,
                "type_errors": script.validation.type_errors,
                "test_errors": script.validation.test_errors,
                "success_probability": script.validation.success_probability,
            },
            "metadata": {
                "profile_hash": script.metadata.profile_hash,
                "generator_version": script.metadata.generator_version,
                "timestamp": script.metadata.timestamp,
                "estimated_success_rate": script.metadata.estimated_success_rate,
            },
        }
        (output_dir / "generation_metadata.json").write_text(json.dumps(metadata, indent=2))
        
        logger.info(f"Script generated in {output_dir}")
        logger.info(f"Validation: {'PASSED' if script.validation.passed else 'FAILED'} (success prob: {script.validation.success_probability:.2f})")
        
        # Cache the script
        if cache:
            await cache.set(cache_key, script)
        
        return 0
        
    except Exception as e:
        import traceback
        logger.error(f"Generation failed: {e}")
        traceback.print_exc()
        return 1


async def cmd_generate_from_profile(args: argparse.Namespace) -> int:
    """Generate script from existing profile."""
    
    # Load profile
    try:
        from scraper.config.schemas import DeepSiteProfile
        profile_data = json.loads(args.profile_file.read_text())
        profile = DeepSiteProfile(**profile_data)
    except Exception as e:
        logger.error(f"Failed to load profile: {e}")
        return 1
    
    requirements = GenerationRequirements(
        engine_preference=EngineType(args.engine) if args.engine else None,
        output_formats=[OutputFormat(f) for f in args.output_formats],
        enrichment_steps=args.enrichment_steps,
    )
    
    generator = ScriptGenerator()
    
    try:
        logger.info(f"Generating script from profile: {args.profile_file}")
        script = await generator.generate_from_profile(profile, requirements)
        
        output_dir = Path(args.output)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        (output_dir / "scraper.py").write_text(script.main_code)
        (output_dir / "config.py").write_text(script.config_code)
        (output_dir / "test_scraper.py").write_text(script.test_code)
        (output_dir / "requirements.txt").write_text(script.requirements_code)
        
        metadata = {
            "strategy": {
                "engine": script.strategy.engine.value,
                "template": script.strategy.template,
                "confidence": script.strategy.confidence,
                "reasoning": script.strategy.reasoning,
            },
            "validation": {
                "passed": script.validation.passed,
                "lint_errors": script.validation.lint_errors,
                "type_errors": script.validation.type_errors,
                "test_errors": script.validation.test_errors,
                "success_probability": script.validation.success_probability,
            },
        }
        (output_dir / "generation_metadata.json").write_text(json.dumps(metadata, indent=2))
        
        logger.info(f"Script generated in {output_dir}")
        return 0
        
    except Exception as e:
        logger.error(f"Generation failed: {e}")
        return 1


async def cmd_validate(args: argparse.Namespace) -> int:
    """Validate a generated script."""
    
    try:
        script_data = json.loads(args.script_file.read_text())
        main_code = script_data.get("main_code", "")
        config_code = script_data.get("config_code", "")
        test_code = script_data.get("test_code", "")
        req_code = script_data.get("requirements_code", "")
        
        validation = await validate_generated_script(main_code, config_code, test_code, req_code)
        
        print(f"Validation: {'PASSED' if validation.passed else 'FAILED'}")
        print(f"Success probability: {validation.success_probability:.2f}")
        
        if validation.lint_errors:
            print(f"\nLint errors:")
            for err in validation.lint_errors:
                print(f"  - {err}")
        
        if validation.type_errors:
            print(f"\nType errors:")
            for err in validation.type_errors:
                print(f"  - {err}")
        
        if validation.test_errors:
            print(f"\nTest errors:")
            for err in validation.test_errors:
                print(f"  - {err}")
        
        return 0 if validation.passed else 1
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return 1


async def cmd_list_templates(args: argparse.Namespace) -> int:
    """List available templates."""
    
    from scripts.templates import TemplateLibrary
    
    lib = TemplateLibrary(Path(__file__).parent / "templates")
    
    print("Available templates:")
    for name, templates in TemplateLibrary.BUILTIN_TEMPLATES.items():
        print(f"\n  {name}:")
        for key, path in templates.items():
            print(f"    {key}: {path}")
    
    return 0


async def cmd_cache(args: argparse.Namespace) -> int:
    """Cache management commands."""
    
    if args.cache_command == "clear":
        cache_dir = Path(args.cache_dir)
        if cache_dir.exists():
            import shutil
            shutil.rmtree(cache_dir)
            logger.info(f"Cleared cache at {cache_dir}")
        else:
            logger.info(f"Cache directory {cache_dir} does not exist")
        return 0
    
    elif args.cache_command == "stats":
        cache_dir = Path(args.cache_dir)
        if not cache_dir.exists():
            logger.info("Cache directory does not exist")
            return 0
        
        # Count cached scripts
        script_files = list((cache_dir / "scripts").glob("*.json")) if (cache_dir / "scripts").exists() else []
        print(f"Cache directory: {cache_dir}")
        print(f"Cached scripts: {len(script_files)}")
        
        # Try to read index
        index_db = cache_dir / "cache_index.db"
        if index_db.exists():
            import sqlite3
            conn = sqlite3.connect(str(index_db))
            cursor = conn.execute("SELECT COUNT(*) FROM cache_index")
            count = cursor.fetchone()[0]
            print(f"Index entries: {count}")
        return 0
    
    return 1


async def main(args: argparse.Namespace) -> int:
    if args.command == "generate":
        return await cmd_generate(args)
    elif args.command == "generate-from-profile":
        return await cmd_generate_from_profile(args)
    elif args.command == "validate":
        return await cmd_validate(args)
    elif args.command == "list-templates":
        return await cmd_list_templates(args)
    elif args.command == "cache":
        return await cmd_cache(args)
    else:
        logger.error(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    args = parse_args()
    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)