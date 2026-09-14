from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import yaml
from pydantic import ValidationError

from .schemas import (
    UniversalConfig,
    UniversalRequest,
    EngineType,
    OutputFormat,
    StateBackend,
    ExecutionMode,
    ProfileDepth,
    ValidationMode,
    AntiBotLevel,
    ProxyType,
    BrowserType,
    LogLevel,
    BrowserEngineConfig,
    ManagedEngineConfig,
    ConcurrencyConfig,
    RateLimit,
    StorageConfig,
    StateBackend,
)


class ConfigLoader:
    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        engines_path: Optional[Union[str, Path]] = None,
        env_prefix: str = "SCRAPER_",
    ):
        # Get project root (parent of scraper directory)
        project_root = Path(__file__).parent.parent.parent
        
        if config_path is None:
            config_path = project_root / "config.yaml"
        if engines_path is None:
            engines_path = project_root / "config" / "engines.yaml"
        
        self.config_path = Path(config_path) if config_path else None
        self.engines_path = Path(engines_path) if engines_path else None
        self.env_prefix = env_prefix

    def load(self, cli_args: Optional[argparse.Namespace] = None) -> UniversalConfig:
        config_data = {}

        if self.config_path and self.config_path.exists():
            config_data = self._load_yaml(self.config_path)

        if self.engines_path and self.engines_path.exists():
            engines_data = self._load_yaml(self.engines_path)
            config_data = self._deep_merge(config_data, engines_data)

        env_data = self._load_from_env()
        config_data = self._deep_merge(config_data, env_data)

        if cli_args:
            cli_data = self._load_from_cli(cli_args)
            config_data = self._deep_merge(config_data, cli_data)

        try:
            return UniversalConfig(**config_data)
        except ValidationError as e:
            raise ValueError(f"Configuration validation failed: {e}")

    def load_request(
        self,
        url: str,
        goal: str = "",
        schema: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> UniversalRequest:
        return UniversalRequest(
            url=url,
            goal=goal,
            schema=schema,
            **kwargs
        )

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data

    def _load_from_env(self) -> Dict[str, Any]:
        config = {}
        prefix_len = len(self.env_prefix)

        for key, value in os.environ.items():
            if key.startswith(self.env_prefix):
                config_key = key[prefix_len:].lower()
                self._set_nested(config, config_key.split("__"), self._parse_value(value))

        return config

    def _load_from_cli(self, args: argparse.Namespace) -> Dict[str, Any]:
        config = {}

        cli_mapping = {
            "url": "target_urls",
            "urls": "target_urls",
            "output_format": "output_format",
            "output_dir": "output_dir",
            "user_agent": "user_agent",
            "proxy": "proxy_config.proxy_url",
            "proxy_type": "proxy_config.proxy_type",
            "timeout": "request_timeout.total",
            "concurrency": "concurrency.max_concurrent_requests",
            "max_pages": "http_engine.max_pages",
            "headless": "browser_engine.headless",
            "stealth": "browser_engine.stealth_mode",
            "log_level": "observability.log_level",
            "cache_dir": "script_generation.cache.cache_dir",
            "fallback_threshold": "fallback.quality_threshold",
        }

        for arg_name, config_path in cli_mapping.items():
            if hasattr(args, arg_name) and getattr(args, arg_name) is not None:
                value = getattr(args, arg_name)
                self._set_nested(config, config_path.split("."), value)

        # Handle depth separately - only map to domain_rules.max_depth if it's an integer
        # (for scrape command). For generate/profile commands, depth is a ProfileDepth enum string.
        if hasattr(args, 'depth') and getattr(args, 'depth') is not None:
            depth_value = getattr(args, 'depth')
            # Check if it's an integer (crawl depth) or ProfileDepth enum string
            if isinstance(depth_value, int) or (isinstance(depth_value, str) and depth_value.isdigit()):
                self._set_nested(config, "domain_rules.max_depth", int(depth_value))

        return config

    def _set_nested(self, d: Dict[str, Any], keys: List[str], value: Any):
        for key in keys[:-1]:
            if key not in d:
                d[key] = {}
            d = d[key]
        d[keys[-1]] = value

    def _parse_value(self, value: str) -> Any:
        if value.lower() in ("true", "false"):
            return value.lower() == "true"
        if value.lower() in ("none", "null"):
            return None
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            return value

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
        return result


def create_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Hybrid Universal Scraper",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "-c", "--config",
        type=str,
        help="Path to config YAML file"
    )
    parser.add_argument(
        "-e", "--engines-config",
        type=str,
        help="Path to engines YAML file"
    )
    parser.add_argument(
        "-u", "--url",
        action="append",
        dest="urls",
        help="Target URL(s) to scrape (can be used multiple times)"
    )
    parser.add_argument(
        "--output-format",
        type=str,
        choices=[f.value for f in OutputFormat],
        help="Output format"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        help="Output directory"
    )
    parser.add_argument(
        "--user-agent",
        type=str,
        help="Custom user agent string"
    )
    parser.add_argument(
        "--proxy",
        type=str,
        help="Proxy URL"
    )
    parser.add_argument(
        "--proxy-type",
        type=str,
        choices=[p.value for p in ProxyType],
        help="Proxy type"
    )
    parser.add_argument(
        "--timeout",
        type=int,
        help="Request timeout in seconds"
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        help="Max concurrent requests"
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        help="Max pages to scrape"
    )
    parser.add_argument(
        "--depth",
        type=int,
        help="Max crawl depth"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run browser in headless mode"
    )
    parser.add_argument(
        "--no-headless",
        action="store_false",
        dest="headless",
        help="Run browser in headed mode"
    )
    parser.add_argument(
        "--stealth",
        action="store_true",
        help="Enable stealth mode"
    )
    parser.add_argument(
        "--log-level",
        type=str,
        choices=[l.value for l in LogLevel],
        help="Log level"
    )
    parser.add_argument(
        "--cache-dir",
        type=str,
        help="Script cache directory"
    )
    parser.add_argument(
        "--fallback-threshold",
        type=float,
        help="Quality threshold for fallback (0-1)"
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["auto", "runner_only", "generate_only"],
        default="auto",
        help="Execution mode"
    )
    parser.add_argument(
        "--engine",
        type=str,
        choices=[e.value for e in EngineType],
        help="Force specific engine"
    )
    parser.add_argument(
        "--goal",
        type=str,
        help="Extraction goal/instruction"
    )
    parser.add_argument(
        "--schema",
        type=str,
        help="JSON schema for extraction"
    )
    parser.add_argument(
        "--schema-file",
        type=str,
        help="Path to JSON schema file"
    )

    return parser


def load_config(
    config_path: Optional[Union[str, Path]] = None,
    engines_path: Optional[Union[str, Path]] = None,
    cli_args: Optional[argparse.Namespace] = None,
) -> UniversalConfig:
    if config_path is None:
        config_path = Path(__file__).parent.parent.parent / "config.yaml"
    if engines_path is None:
        engines_path = Path(__file__).parent.parent.parent / "config" / "engines.yaml"
    
    loader = ConfigLoader(config_path, engines_path)
    return loader.load(cli_args)


def load_config_from_file(path: Union[str, Path]) -> UniversalConfig:
    loader = ConfigLoader(config_path=path)
    return loader.load()


def merge_configs(base: UniversalConfig, override: Dict[str, Any]) -> UniversalConfig:
    base_dict = base.model_dump()
    loader = ConfigLoader()
    merged = loader._deep_merge(base_dict, override)
    return UniversalConfig(**merged)


def get_default_config() -> UniversalConfig:
    return UniversalConfig()


def get_low_memory_config() -> UniversalConfig:
    """Optimized configuration for 8GB RAM systems with 6GB Docker allocation.
    
    This preset configures the scraper to run within ~500MB for browser pool,
    leaving headroom for OS, Python runtime, and other components.
    """
    return UniversalConfig(
        browser_engine=BrowserEngineConfig(
            pool_min=1,
            pool_max=3,
            pool_max_memory_mb=512,
            adaptive_pool=True,
            pool_idle_timeout_ms=30000,
            pool_recycle_after_pages=20,
            min_idle_timeout_ms=60000,
            max_idle_timeout_ms=300000,
            recycle_after_memory_mb=150,
            recycle_after_pages=20,
            recycle_on_error_rate=0.1,
            resource_blocking={
                "images": True,
                "fonts": True,
                "css": False,
                "media": True,
                "websocket": True,
                "xhr": False,
                "fetch": False,
            },
        ),
        managed_engine=ManagedEngineConfig(
            max_concurrency=3,
            max_requests_per_crawl=50,
            session_pool_size=20,
        ),
        concurrency=ConcurrencyConfig(
            max_concurrent_requests=5,
            max_concurrent_browsers=3,
            max_concurrent_per_domain=2,
        ),
        rate_limit=RateLimit(
            requests_per_second=1.0,
            per_domain=True,
            adaptive=True,
        ),
        storage=StorageConfig(
            backend=StateBackend.SQLITE,
        ),
    )


def validate_config(config: UniversalConfig) -> List[str]:
    errors = []
    warnings = []

    if not config.target_urls:
        warnings.append("No target URLs specified")

    if config.concurrency.max_concurrent_requests > 100:
        warnings.append("High concurrency may cause resource issues")

    if config.rate_limit.requests_per_second > 100:
        warnings.append("High rate limit may trigger blocking")

    if config.browser_engine.pool_max > 50:
        warnings.append("Large browser pool may exceed memory limits")

    if config.cloud_engine.enabled and not config.cloud_engine.api_url:
        errors.append("Cloud engine enabled but no API URL provided")

    return errors + warnings