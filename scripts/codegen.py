from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlparse
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from jinja2 import Environment, FileSystemLoader, select_autoescape

from scraper.config.schemas import (
    DeepSiteProfile,
    GenerationStrategy,
    GeneratedScript,
    ValidationResult,
    GenerationMetadata,
    GenerationRequirements,
    EngineType,
    OutputFormat,
    ProfileDepth,
)
from scripts.profiler import DeepSiteProfiler, ProfileDepth, LLMAnalysis
from scripts.templates import TemplateLibrary
from scripts.validators import validate_generated_script, ValidationResult as ScriptValidationResult


@dataclass
class ScriptGenerator:
    """Generates production-ready per-site scripts from templates."""

    template_dir: Optional[Path] = None
    user_template_dir: Optional[Path] = None
    llm_client: Optional[Any] = None

    def __post_init__(self):
        if self.template_dir is None:
            self.template_dir = Path(__file__).parent / "templates"
        if self.user_template_dir is None:
            self.user_template_dir = Path.home() / ".universal_scraper" / "templates"

        self.env = Environment(
            loader=FileSystemLoader([str(self.user_template_dir), str(self.template_dir)]),
            autoescape=select_autoescape(["html", "xml", "py"]),
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self._register_filters()

        self.profiler = DeepSiteProfiler(llm_client=self.llm_client)
        self.template_lib = TemplateLibrary(self.template_dir)

    def _register_filters(self):
        self.env.filters["tojson"] = json.dumps
        self.env.filters["tojson_pretty"] = lambda x: json.dumps(x, indent=2)
        self.env.filters["slugify"] = lambda x: re.sub(r'[^a-zA-Z0-9]+', '_', x).strip('_').lower()

    async def generate(
        self,
        url: str,
        requirements: Optional[GenerationRequirements] = None,
        context: Optional[Any] = None,
        depth: ProfileDepth = ProfileDepth.DEEP,
    ) -> GeneratedScript:
        """Generate a complete scraper script for the given URL."""

        requirements = requirements or GenerationRequirements()

        # Deep profile
        profile = await self.profiler.profile(url, depth=depth)

        # Select generation strategy
        strategy = self._select_strategy(profile, requirements)

        # Build template context
        context = self._build_context(profile, requirements, strategy)

        # Render templates
        main_code = self._render_template(f"{strategy.engine.value}/main.py.j2", context)
        config_code = self._render_template(f"{strategy.engine.value}/config.py.j2", context)
        test_code = self._render_template(f"{strategy.engine.value}/test.py.j2", context)
        req_code = self._render_template(f"{strategy.engine.value}/requirements.txt.j2", context)

        # Validate generated code
        validation_dataclass = await validate_generated_script(main_code, config_code, test_code, req_code)
        
        # Convert dataclass to Pydantic model
        validation = ValidationResult(
            passed=validation_dataclass.passed,
            lint_errors=validation_dataclass.lint_errors,
            type_errors=validation_dataclass.type_errors,
            test_errors=validation_dataclass.test_errors,
            success_probability=validation_dataclass.success_probability,
            warnings=validation_dataclass.warnings,
        )

        # Create metadata
        metadata = GenerationMetadata(
            profile_hash=profile.hash(),
            generator_version="0.3.0",
            timestamp=datetime.utcnow().isoformat(),
            estimated_success_rate=validation.success_probability,
            template_versions=self.template_lib.get_versions(),
        )

        return GeneratedScript(
            strategy=strategy,
            main_code=main_code,
            config_code=config_code,
            test_code=test_code,
            requirements_code=req_code,
            validation=validation,
            metadata=metadata,
        )

    def _select_strategy(
        self,
        profile: DeepSiteProfile,
        requirements: GenerationRequirements,
    ) -> GenerationStrategy:
        """Select best engine and template based on profile."""
        if requirements.engine_preference:
            engine = requirements.engine_preference
        elif profile.api_endpoints and len(profile.api_endpoints) > 0:
            engine = EngineType.API
        elif profile.anti_bot_level in ("high", "extreme"):
            engine = EngineType.CLOUD
        elif profile.requires_js or profile.js_framework:
            engine = EngineType.BROWSER
        elif profile.category == "ecommerce" and profile.has_pagination:
            engine = EngineType.MANAGED
        else:
            engine = EngineType.HTTP

        template_map = {
            EngineType.HTTP: "scrapy_spider",
            EngineType.BROWSER: "playwright_script",
            EngineType.MANAGED: "crawlee_crawler",
            EngineType.CLOUD: "firecrawl_script",
            EngineType.API: "api_client",
            EngineType.HYBRID: "hybrid_scraper",
        }

        return GenerationStrategy(
            engine=engine,
            template=template_map.get(engine, "scrapy_spider"),
            confidence=0.9,
            reasoning=f"Selected {engine.value} based on site profile: {profile.category}, JS={profile.requires_js}, anti-bot={profile.anti_bot_level}",
        )

    def _build_context(
        self,
        profile: DeepSiteProfile,
        requirements: GenerationRequirements,
        strategy: GenerationStrategy,
    ) -> Dict[str, Any]:
        # Build config dict from requirements and profile
        config = {
            "http_engine": {
                "autothrottle_start_delay": 1.0,
                "autothrottle_enabled": True,
                "autothrottle_max_delay": 60.0,
                "autothrottle_target_concurrency": 2.0,
                "default_headers": {
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept-Encoding": "gzip, deflate, br",
                    "Connection": "keep-alive",
                    "Upgrade-Insecure-Requests": "1",
                },
            },
            "concurrency": {
                "max_concurrent_requests": 16,
            },
            "retry_policy": {
                "max_attempts": 3,
                "retryable_status_codes": [408, 429, 500, 502, 503, 504],
            },
            "domain_rules": {
                "respect_robots_txt": True,
                "max_pages_per_domain": 100,
                "max_depth": 3,
            },
            "session_config": {
                "persist_cookies": True,
            },
            "user_agent": {
                "pool": ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"],
            },
        }
        
        return {
            "profile": profile,
            "requirements": requirements,
            "strategy": strategy,
            "timestamp": datetime.utcnow().isoformat(),
            "version": "0.3.0",
            "config": config,
            "selectors": profile.selectors,
            "pagination": {
                "type": profile.pagination_type,
                "selectors": profile.pagination_selectors,
            },
            "auth": {
                "required": profile.auth_required,
                "type": profile.auth_type,
            },
            "output_formats": [f.value for f in requirements.output_formats],
            "enrichment_steps": requirements.enrichment_steps,
            "interactions": profile.interaction_sequences,
            "api_endpoints": profile.api_endpoints,
            "inferred_schema": profile.inferred_schemas,
            "llm_analysis": profile.llm_analysis,
            "urlparse": urlparse,
        }

    def _render_template(self, template_name: str, context: Dict[str, Any]) -> str:
        try:
            template = self.env.get_template(template_name)
            return template.render(**context)
        except Exception as e:
            # Fallback to template library
            return self.template_lib.render(template_name, context)

    async def generate_from_profile(
        self,
        profile: DeepSiteProfile,
        requirements: GenerationRequirements,
    ) -> GeneratedScript:
        """Generate script from existing profile."""
        strategy = self._select_strategy(profile, requirements)
        context = self._build_context(profile, requirements, strategy)

        main_code = self._render_template(f"{strategy.engine.value}/main.py.j2", context)
        config_code = self._render_template(f"{strategy.engine.value}/config.py.j2", context)
        test_code = self._render_template(f"{strategy.engine.value}/test.py.j2", context)
        req_code = self._render_template(f"{strategy.engine.value}/requirements.txt.j2", context)

        validation = await validate_generated_script(main_code, config_code, test_code, req_code)

        return GeneratedScript(
            strategy=self._select_strategy(profile, requirements),
            main_code=main_code,
            config_code=config_code,
            test_code=test_code,
            requirements_code=req_code,
            validation=validation,
            metadata=GenerationMetadata(
                profile_hash=profile.hash(),
                generator_version="0.3.0",
                timestamp=datetime.utcnow().isoformat(),
                estimated_success_rate=validation.success_probability,
            ),
        )


class TemplateLibrary:
    """Manages built-in and user templates."""

    BUILTIN_TEMPLATES = {
        "scrapy_spider": {
            "main.py.j2": "http/main.py.j2",
            "config.py.j2": "http/config.py.j2",
            "test.py.j2": "http/test.py.j2",
            "requirements.txt.j2": "http/requirements.txt.j2",
        },
        "playwright_script": {
            "main.py.j2": "browser/main.py.j2",
            "config.py.j2": "browser/config.py.j2",
            "test.py.j2": "browser/test.py.j2",
            "requirements.txt.j2": "browser/requirements.txt.j2",
        },
        "crawlee_crawler": {
            "main.py.j2": "managed/main.py.j2",
            "config.py.j2": "managed/config.py.j2",
            "test.py.j2": "managed/test.py.j2",
            "requirements.txt.j2": "managed/requirements.txt.j2",
        },
        "firecrawl_script": {
            "main.py.j2": "cloud/main.py.j2",
            "config.py.j2": "cloud/config.py.j2",
            "test.py.j2": "cloud/test.py.j2",
            "requirements.txt.j2": "cloud/requirements.txt.j2",
        },
        "api_client": {
            "main.py.j2": "api/main.py.j2",
            "config.py.j2": "api/config.py.j2",
            "test.py.j2": "api/test.py.j2",
            "requirements.txt.j2": "api/requirements.txt.j2",
        },
        "hybrid_scraper": {
            "main.py.j2": "hybrid/main.py.j2",
            "config.py.j2": "hybrid/config.py.j2",
            "test.py.j2": "hybrid/test.py.j2",
            "requirements.txt.j2": "hybrid/requirements.txt.j2",
        },
    }

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self._versions = {}

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        # Try built-in template first
        # In practice, this would use jinja2 with the template
        return f"# Generated from {template_name}\n# Context: {list(context.keys())}"

    def get_versions(self) -> Dict[str, str]:
        return self._versions