from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional
import yaml

VALID_MODES = {"auto", "free_only", "cloud_preferred"}

@dataclass
class ScraperConfig:
    mode: str = "free_only"
    engine_priority: list[str] = field(default_factory=lambda: ["crawlee", "firecrawl", "playwright", "scrapy"])
    fallback: dict[str, Any] = field(default_factory=lambda: {"on_limit_reached": True, "log_fallbacks": True})
    robots: dict[str, Any] = field(default_factory=lambda: {"respect": True, "user_agent": "CompliantFreeFirstScraper/0.1"})
    limits: dict[str, Any] = field(default_factory=lambda: {"timeout_seconds": 60, "requests_per_second": 2, "max_redirects": 5})
    output: dict[str, Any] = field(default_factory=lambda: {"directory": "output"})
    domain_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    engines: dict[str, dict[str, Any]] = field(default_factory=dict)
    routing: dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self) -> None:
        if self.mode not in VALID_MODES:
            raise ValueError(f"mode must be one of {sorted(VALID_MODES)}")
    
    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "engine_priority": self.engine_priority,
            "fallback": self.fallback,
            "robots": self.robots,
            "limits": self.limits,
            "output": self.output,
            "domain_overrides": self.domain_overrides,
            "engines": self.engines,
            "routing": self.routing,
        }

def load_config(path: str | Path | None = None) -> ScraperConfig:
    path = Path(path or "config.yaml")
    if not path.exists():
        return ScraperConfig()
    
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    
    engines_path = Path("config/engines.yaml")
    if engines_path.exists():
        engines_data = yaml.safe_load(engines_path.read_text(encoding="utf-8")) or {}
        data.setdefault("engines", engines_data.get("engines", {}))
        data.setdefault("routing", engines_data.get("routing", {}))
    
    return ScraperConfig(**{k: v for k, v in data.items() if k in ScraperConfig.__dataclass_fields__})