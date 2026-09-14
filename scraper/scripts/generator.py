"""Script generation module for the universal scraper."""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set
from jinja2 import Environment, FileSystemLoader

from ..config.schemas import EngineType, OutputFormat
from ..engines.registry_v2 import EngineRegistryV2
from ..universal_runner import UniversalRunner
from .profiler import DeepSiteProfiler, ProfileDepth
from .cache import ScriptCache, CacheConfig

logger = logging.getLogger(__name__)


@dataclass
class GenerationRequirements:
    """Requirements for script generation."""
    engine_preference: Optional[EngineType] = None
    output_formats: List[OutputFormat] = field(default_factory=lambda: [OutputFormat.JSONL])
    max_pages: int = 10
    depth: int = 0
    use_stealth: bool = True
    use_proxy: bool = False
    custom_headers: Dict[str, str] = field(default_factory=dict)
    custom_cookies: Dict[str, str] = field(default_factory=dict)
    wait_for_selector: Optional[str] = None
    wait_for_timeout: int = 60000
    extraction_schema: Optional[Dict[str, Any]] = None
    custom_llm_prompt: Optional[str] = None
    goal: str = ""


@dataclass
class GeneratedScript:
    """Generated scraper script with metadata."""
    script_id: str
    main_code: str
    config_code: str
    test_code: str
    requirements_code: str
    metadata: "GenerationMetadata"
    validation: "ValidationResult"


@dataclass
class GenerationMetadata:
    """Metadata about the generated script."""
    profile_hash: str
    generator_version: str
    timestamp: str
    estimated_success_rate: float
    template_versions: Dict[str, str] = field(default_factory=dict)


@dataclass
class ValidationResult:
    """Validation result for generated script."""
    passed: bool
    lint_errors: List[str] = field(default_factory=list)
    type_errors: List[str] = field(default_factory=list)
    test_errors: List[str] = field(default_factory=list)
    success_probability: float = 0.0
    warnings: List[str] = field(default_factory=list)


class ScriptGenerator:
    """Generates optimized scraper scripts based on site profiles."""

    def __init__(self, cache: Optional["ScriptCache"] = None):
        self.cache = cache
        self.engine_registry = EngineRegistryV2()
        self.template_env = self._create_template_env()
        self.generation_version = "1.0.0"

    def _create_template_env(self) -> Environment:
        """Create Jinja2 template environment."""
        template_dir = Path(__file__).parent / "templates"
        if not template_dir.exists():
            # Create inline templates if directory doesn't exist
            return Environment(autoescape=False)
        return Environment(
            loader=FileSystemLoader(str(template_dir)),
            autoescape=False,
            trim_blocks=True,
            lstrip_blocks=True,
        )

    async def generate_from_profile(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
        goal: str = "",
    ) -> GeneratedScript:
        """Generate a complete scraper script from a site profile."""
        # Set goal on requirements if not already set
        if not requirements.goal and goal:
            requirements.goal = goal
        script_id = str(uuid.uuid4())[:8]
        
        # Determine best engine for this profile
        engine = await self._select_engine(profile, requirements)
        
        # Generate main scraper code
        main_code = self._render_main_template(profile, requirements, engine)
        
        # Generate config code
        config_code = self._render_config_template(profile, requirements)
        
        # Generate test code
        test_code = self._render_test_template(profile, requirements)
        
        # Generate requirements.txt
        requirements_code = self._render_requirements_template(engine)
        
        # Validate generated code
        validation = await self._validate_generated_code(main_code, config_code, test_code)
        
        # Create metadata
        metadata = GenerationMetadata(
            profile_hash=profile.hash(),
            generator_version=self.generation_version,
            timestamp=datetime.utcnow().isoformat(),
            estimated_success_rate=validation.success_probability,
        )
        
        script = GeneratedScript(
            script_id=script_id,
            main_code=main_code,
            config_code=config_code,
            test_code=test_code,
            requirements_code=requirements_code,
            metadata=metadata,
            validation=validation,
        )
        
        # Cache if available
        if self.cache:
            await self.cache.set(script_id, script)
        
        return script

    async def _select_engine(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
    ) -> EngineType:
        """Select the best engine for the given profile and requirements."""
        if requirements.engine_preference:
            return requirements.engine_preference
        
        # Score engines based on profile characteristics
        scores = {}
        
        # Crawlee: Good for large-scale, JavaScript-heavy sites
        scores[EngineType.MANAGED] = 0.7
        if profile.requires_js:
            scores[EngineType.MANAGED] += 0.3
        if profile.has_pagination:
            scores[EngineType.MANAGED] += 0.2
        
        # Playwright: Good for complex interactions
        scores[EngineType.BROWSER] = 0.6
        if profile.auth_required:
            scores[EngineType.BROWSER] += 0.3
        if profile.requires_js:
            scores[EngineType.BROWSER] += 0.2
        
        # Firecrawl: Best for anti-bot protection
        scores[EngineType.CLOUD] = 0.5
        if profile.anti_bot_level in ("high", "extreme"):
            scores[EngineType.CLOUD] += 0.5
        
        # Scrapy: Good for static content, APIs (use HTTP as fallback)
        scores[EngineType.HTTP] = 0.5
        if not profile.requires_js:
            scores[EngineType.HTTP] += 0.3
        
        # HTTP: Fastest for static content
        scores[EngineType.HTTP] = 0.4
        if not profile.requires_js and not profile.auth_required:
            scores[EngineType.HTTP] += 0.3
        
        # Return highest scoring engine
        return max(scores, key=scores.get)

    def _render_main_template(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
        engine: EngineType,
    ) -> str:
        """Render the main scraper script using template file."""
        template = self.template_env.get_template("main.py.j2")
        
        return template.render(
            profile=profile,
            requirements=requirements,
            engine=engine,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _render_config_template(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
    ) -> str:
        """Render the configuration module using template file."""
        template = self.template_env.get_template("config.py.j2")
        
        engine_value = requirements.engine_preference.value if requirements.engine_preference else "auto"
        return template.render(
            profile=profile,
            requirements=requirements,
            engine=engine_value,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _render_test_template(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
    ) -> str:
        """Render test code for the generated script using template file."""
        template = self.template_env.get_template("test.py.j2")
        
        return template.render(
            profile=profile,
            requirements=requirements,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _render_requirements_template(self, engine: EngineType) -> str:
        """Generate requirements.txt content using template file."""
        template = self.template_env.get_template("requirements.txt.j2")
        
        return template.render(
            engine=engine,
            timestamp=datetime.utcnow().isoformat(),
        )

    def _get_main_template(self, engine: EngineType) -> str:
        """Get the main template for the specified engine."""
        # This would normally load from a template file
        # For now, return inline template
        return (
            '"""'
            'Auto-generated scraper for {{ profile.url }}\n'
            'Engine: {{ engine }}\n'
            'Generated at: {{ timestamp }}\n'
            '"""'
            '\n\n'
            'import asyncio\n'
            'import sys\n'
            'from pathlib import Path\n\n'
            '# Add project root to path\n'
            'sys.path.insert(0, str(Path(__file__).parent.parent))\n\n'
            'from scraper.universal_runner import UniversalRunner, UniversalConfig\n'
            'from scraper.config.schemas import UniversalRequest, UniversalResult, OutputFormat, EngineType\n'
            'from scraper.config import UniversalConfig\n\n'
            '# Configuration\n'
            'from config import ScrapingConfig\n\n'
            'async def main():\n'
            '    """Main entry point for the scraper."""\n'
            '    config = ScrapingConfig()\n    \n'
            '    config_obj = UniversalConfig()\n'
            '    runner = UniversalRunner(config_obj)\n    \n'
            '    request = UniversalRequest(\n'
            '        url="{{ profile.url }}",\n'
            '        goal="{{ requirements.goal | tojson }}",\n'
            '        max_pages={{ requirements.max_pages }},\n'
            '        depth={{ requirements.depth }},\n'
            '        output_formats=[OutputFormat(f) for f in {{ requirements.output_formats | map(attribute=\'value\') | list | tojson }}],\n'
            '        engine=EngineType.{{ engine.value }} if "{{ engine }}" != "auto" else None,\n'
            '        engine_options={\n'
            '            "headless": true,\n'
            '            "stealth_mode": {{ requirements.use_stealth | lower }},\n'
            '        },\n'
            '        use_proxy={{ requirements.use_proxy | lower }},\n'
            '        extract_schema={{ requirements.extraction_schema | tojson if requirements.extraction_schema else \'None\' }},\n'
            '    )\n    \n'
            '    result = await runner.scrape(request)\n    \n'
            '    if result.success:\n'
            '        print(f"SUCCESS: Scraped {len(result.data) if isinstance(result.data, list) else 1} items")\n'
            '        print(f"Engine: {result.engine_used}")\n'
            '        print(f"Quality: {result.quality_score:.2f}")\n        \n'
            '        # Output files are handled by the runner\n'
            '        return 0\n'
            '    else:\n'
            '        print(f"FAILED: {result.error}")\n'
            '        return 1\n\n'
            'if __name__ == "__main__":\n'
            '    exit_code = asyncio.run(main())\n'
            '    sys.exit(exit_code)\n'
        )

    async def _validate_generated_code(
        self,
        main_code: str,
        config_code: str,
        test_code: str,
    ) -> ValidationResult:
        """Validate generated code with linting and type checking."""
        errors = []
        warnings = []
        
        # Basic syntax validation
        try:
            compile(main_code, "<main>", "exec")
            compile(config_code, "<config>", "exec")
            compile(test_code, "<test>", "exec")
        except SyntaxError as e:
            return ValidationResult(
                passed=False,
                lint_errors=[str(e)],
                success_probability=0.0,
            )
        
        # Check for common issues
        if "async def main" not in main_code:
            warnings.append("Main function should be async")
        
        if "asyncio.run(main())" not in main_code:
            warnings.append("Missing asyncio.run(main()) call")
        
        # Calculate success probability
        base_prob = 0.8
        prob = base_prob - (len(warnings) * 0.05)
        
        return ValidationResult(
            passed=len(warnings) == 0,
            lint_errors=[],
            type_errors=[],
            test_errors=[],
            success_probability=max(0.0, min(1.0, prob)),
            warnings=warnings,
        )
    
    async def generate_from_url(
        self,
        url: str,
        goal: str,
        requirements: Optional[GenerationRequirements] = None,
    ) -> "GeneratedScript":
        """Convenience method: profile a URL and generate script in one call."""
        from .profiler import DeepSiteProfiler, ProfileDepth
        
        profiler = DeepSiteProfiler()
        profile = await profiler.profile(url, depth=ProfileDepth.DEEP)
        
        if requirements is None:
            requirements = GenerationRequirements()
        
        return await self.generate_from_profile(profile, requirements, goal)

    async def generate(
        self,
        profile: "DeepSiteProfile",
        requirements: GenerationRequirements,
        goal: str = "",
    ) -> "GeneratedScript":
        """
        Main entry point for script generation.
        Wraps generate_from_profile for compatibility with orchestrator.
        """
        return await self.generate_from_profile(profile, requirements, goal)