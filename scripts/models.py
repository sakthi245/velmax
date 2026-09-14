from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from scraper.config.schemas import (
    OutputFormat,
    EngineType,
    StateBackend,
    ExecutionMode,
    ProfileDepth,
    ValidationMode,
    AntiBotLevel,
)


class GenerationRequirements:
    def __init__(
        self,
        engine_preference: Optional[EngineType] = None,
        output_formats: List[OutputFormat] = None,
        enrichment_steps: List[str] = None,
        compliance_flags: List[str] = None,
        incremental: bool = True,
        resume_support: bool = True,
        test_generation: bool = True,
        documentation: bool = True,
    ):
        self.engine_preference = engine_preference
        self.output_formats = output_formats or [OutputFormat.JSONL]
        self.enrichment_steps = enrichment_steps or []
        self.compliance_flags = compliance_flags or []
        self.incremental = incremental
        self.resume_support = resume_support
        self.test_generation = test_generation
        self.documentation = documentation


class ValidationResult:
    def __init__(
        self,
        passed: bool = True,
        lint_errors: List[str] = None,
        type_errors: List[str] = None,
        test_errors: List[str] = None,
        success_probability: float = 1.0,
        warnings: List[str] = None,
    ):
        self.passed = passed
        self.lint_errors = lint_errors or []
        self.type_errors = type_errors or []
        self.test_errors = test_errors or []
        self.success_probability = success_probability
        self.warnings = warnings or []