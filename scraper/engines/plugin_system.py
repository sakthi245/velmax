from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Type, Union

from .interfaces import EngineConfig, EngineMetadata, EngineType, EngineCapability
from ..universal_runner import UniversalRunner, UniversalConfig
from ..config.schemas import UniversalRequest, UniversalResult


logger = logging.getLogger("plugin_system")


class PluginType(Enum):
    ENGINE = "engine"
    EXTRACTOR = "extractor"
    TRANSFORMER = "transformer"
    MIDDLEWARE = "middleware"
    HOOK = "hook"
    VALIDATOR = "validator"
    EXPORTER = "exporter"


@dataclass
class PluginMetadata:
    name: str
    version: str
    description: str
    author: str = ""
    license: str = "MIT"
    dependencies: List[str] = field(default_factory=list)
    plugin_type: PluginType = PluginType.ENGINE
    entry_point: str = ""
    config_schema: Dict[str, Any] = field(default_factory=dict)
    tags: List[str] = field(default_factory=list)
    min_scraper_version: str = "0.3.0"
    max_scraper_version: Optional[str] = None


class Plugin(ABC):
    """Base class for all plugins."""
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.metadata = self.get_metadata()
        self.logger = logging.getLogger(f"plugin.{self.metadata.name}")
        self._initialized = False
    
    @classmethod
    @abstractmethod
    def get_metadata(cls) -> PluginMetadata:
        """Return plugin metadata."""
        pass
    
    @abstractmethod
    async def initialize(self) -> bool:
        """Initialize the plugin. Return True if successful."""
        pass
    
    @abstractmethod
    async def shutdown(self) -> bool:
        """Shutdown the plugin. Return True if successful."""
        pass
    
    def is_initialized(self) -> bool:
        return self._initialized
    
    def get_config(self, key: str, default: Any = None) -> Any:
        return self.config.get(key, default)
    
    def set_config(self, key: str, value: Any):
        self.config[key] = value


class EnginePlugin(Plugin):
    """Base class for engine plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base engine plugin",
            plugin_type=PluginType.ENGINE,
        )
    
    @abstractmethod
    async def scrape(self, request) -> Any:
        """Execute scraping with this engine."""
        pass
    
    @abstractmethod
    async def health_check(self) -> bool:
        """Check if engine is healthy."""
        pass


class ExtractorPlugin(Plugin):
    """Base class for extractor plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base extractor plugin",
            plugin_type=PluginType.EXTRACTOR,
        )
    
    @abstractmethod
    async def extract(self, html: str, schema: Any, context: Optional[Dict] = None) -> Any:
        """Extract structured data from HTML."""
        pass


class TransformerPlugin(Plugin):
    """Base class for data transformer plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base transformer plugin",
            plugin_type=PluginType.TRANSFORMER,
        )
    
    @abstractmethod
    async def transform(self, data: Any, context: Optional[Dict] = None) -> Any:
        """Transform data."""
        pass


class MiddlewarePlugin(Plugin):
    """Base class for middleware plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base middleware plugin",
            plugin_type=PluginType.MIDDLEWARE,
        )
    
    @abstractmethod
    async def before_request(self, request: Any) -> Any:
        """Process request before scraping."""
        pass
    
    @abstractmethod
    async def after_response(self, response: Any) -> Any:
        """Process response after scraping."""
        pass


class HookPlugin(Plugin):
    """Base class for hook plugins (event-based)."""
    
    HOOK_TYPES = [
        "before_scrape",
        "after_scrape",
        "before_extract",
        "after_extract",
        "before_transform",
        "after_transform",
        "on_error",
        "on_retry",
        "on_rate_limit",
        "on_captcha",
    ]
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base hook plugin",
            plugin_type=PluginType.HOOK,
        )
    
    async def execute_hook(self, hook_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute a specific hook."""
        method_name = f"on_{hook_type}"
        if hasattr(self, method_name):
            method = getattr(self, method_name)
            if asyncio.iscoroutinefunction(method):
                return await method(context)
            return method(context)
        return context


class ValidatorPlugin(Plugin):
    """Base class for validator plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base validator plugin",
            plugin_type=PluginType.VALIDATOR,
        )
    
    @abstractmethod
    async def validate(self, data: Any, schema: Optional[Dict] = None) -> Dict[str, Any]:
        """Validate data against schema. Return validation result."""
        pass


class ExporterPlugin(Plugin):
    """Base class for exporter plugins."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name=cls.__name__,
            version="1.0.0",
            description="Base exporter plugin",
            plugin_type=PluginType.EXPORTER,
        )
    
    @abstractmethod
    async def export(self, data: Any, output_path: str, options: Dict[str, Any]) -> bool:
        """Export data to specified format."""
        pass


@dataclass
class PluginInstance:
    plugin: Plugin
    metadata: PluginMetadata
    enabled: bool = True
    loaded_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    config: Dict[str, Any] = field(default_factory=dict)


class PluginManager:
    """Manages plugin lifecycle: loading, initialization, execution."""
    
    def __init__(self, plugin_dirs: Optional[List[str]] = None):
        self.plugin_dirs = plugin_dirs or []
        self.plugins: Dict[str, PluginInstance] = {}
        self.hooks: Dict[str, List[Plugin]] = {hook: [] for hook in HookPlugin.HOOK_TYPES}
        self.logger = logging.getLogger("plugin_manager")
        self._initialized = False
    
    def add_plugin_dir(self, dir_path: str):
        """Add a directory to search for plugins."""
        path = Path(dir_path)
        if path.exists() and path.is_dir():
            self.plugin_dirs.append(str(path))
            self.logger.info(f"Added plugin directory: {dir_path}")
    
    def discover_plugins(self) -> List[Type[Plugin]]:
        """Discover all plugin classes in plugin directories."""
        discovered = []
        
        for plugin_dir in self.plugin_dirs:
            dir_path = Path(plugin_dir)
            if not path.exists():
                continue
            
            # Add to sys.path if not already
            if str(path) not in sys.path:
                sys.path.insert(0, str(path))
            
            # Find all .py files
            for py_file in path.glob("*.py"):
                if py_file.name.startswith("_"):
                    continue
                
                module_name = py_file.stem
                try:
                    module = importlib.import_module(module_name)
                    
                    # Find all Plugin subclasses
                    for name, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, Plugin) and obj != Plugin:
                            discovered.append(obj)
                            self.logger.debug(f"Discovered plugin: {name} from {module_name}")
                except Exception as e:
                    self.logger.warning(f"Failed to import {module_name}: {e}")
        
        return discovered
    
    def load_plugin(self, plugin_class: Type[Plugin], config: Optional[Dict[str, Any]] = None) -> bool:
        """Load and initialize a plugin."""
        try:
            metadata = plugin_class.get_metadata()
            
            # Check version compatibility
            if not self._check_version_compatibility(metadata):
                self.logger.warning(f"Plugin {metadata.name} version incompatible, skipping")
                return False
            
            # Check dependencies
            if not self._check_dependencies(metadata):
                self.logger.warning(f"Plugin {metadata.name} dependencies not met, skipping")
                return False
            
            # Create instance
            plugin = plugin_class(config)
            
            # Initialize
            init_result = asyncio.run(plugin.initialize())
            if not init_result:
                self.logger.error(f"Plugin {metadata.name} initialization failed")
                return False
            
            # Register hooks if it's a hook plugin
            if isinstance(plugin, HookPlugin):
                for hook_type in HookPlugin.HOOK_TYPES:
                    if hasattr(plugin, f"on_{hook_type}"):
                        self.hooks[hook_type].append(plugin)
            
            # Store instance
            instance = PluginInstance(
                plugin=plugin,
                metadata=metadata,
                enabled=True,
                config=config or {},
            )
            self.plugins[metadata.name] = instance
            
            self.logger.info(f"Loaded plugin: {metadata.name} v{metadata.version}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to load plugin {plugin_class.__name__}: {e}")
            return False
    
    def _check_version_compatibility(self, metadata: PluginMetadata) -> bool:
        from packaging import version
        
        current_version = "0.3.0"
        
        if metadata.min_scraper_version:
            if version.parse(current_version) < version.parse(metadata.min_scraper_version):
                return False
        
        if metadata.max_scraper_version:
            if version.parse(current_version) > version.parse(metadata.max_scraper_version):
                return False
        
        return True
    
    def _check_dependencies(self, metadata: PluginMetadata) -> bool:
        for dep in metadata.dependencies:
            try:
                importlib.import_module(dep)
            except ImportError:
                self.logger.warning(f"Missing dependency: {dep}")
                return False
        return True
    
    def unload_plugin(self, name: str) -> bool:
        """Unload a plugin."""
        if name in self.plugins:
            instance = self.plugins[name]
            try:
                asyncio.run(instance.plugin.shutdown())
                del self.plugins[name]
                self.logger.info(f"Unloaded plugin: {name}")
                return True
            except Exception as e:
                self.logger.error(f"Error unloading plugin {name}: {e}")
                return False
        return False
    
    def get_plugin(self, name: str) -> Optional[Plugin]:
        instance = self.plugins.get(name)
        return instance.plugin if instance else None
    
    def get_plugins_by_type(self, plugin_type: PluginType) -> List[Plugin]:
        return [
            instance.plugin 
            for instance in self.plugins.values() 
            if instance.enabled and instance.metadata.plugin_type == plugin_type
        ]
    
    def get_all_plugins(self) -> List[PluginInstance]:
        return list(self.plugins.values())
    
    async def execute_hooks(self, hook_type: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute all hooks of a given type."""
        if hook_type not in self.hooks:
            return context
        
        for plugin in self.hooks[hook_type]:
            if not self.plugins[plugin.metadata.name].enabled:
                continue
            try:
                context = await plugin.execute_hook(hook_type, context)
            except Exception as e:
                self.logger.error(f"Hook {hook_type} failed for {plugin.metadata.name}: {e}")
        return context
    
    async def initialize_all(self):
        """Initialize all loaded plugins."""
        for name, instance in self.plugins.items():
            if not instance.enabled:
                continue
            try:
                if not instance.plugin.is_initialized():
                    await instance.plugin.initialize()
            except Exception as e:
                self.logger.error(f"Failed to initialize plugin {name}: {e}")
    
    async def shutdown_all(self):
        """Shutdown all plugins."""
        for name, instance in list(self.plugins.items()):
            if instance.enabled:
                try:
                    await instance.plugin.shutdown()
                except Exception as e:
                    self.logger.error(f"Error shutting down plugin {name}: {e}")


class PluginRegistry:
    """Registry for managing plugin discovery and loading."""
    
    BUILTIN_PLUGINS = {
        "stealth": "scraper.engines.stealth.StealthManager",
        "interactions": "scraper.engines.interactions.InteractionExecutor",
        "session": "scraper.engines.session_manager.SessionManager",
        "rate_limiter": "scraper.utils.rate_limiter.RateLimiter",
        "cache": "scraper.utils.http_cache.HTTPCache",
        "dedup": "scraper.utils.dedup.DeduplicationManager",
        "validator": "scraper.validator.ResultValidator",
        "output": "scraper.output_pipeline.OutputPipeline",
        "sitemap": "scraper.utils.sitemap.SitemapParser",
    }
    
    def __init__(self, plugin_manager: PluginManager):
        self.plugin_manager = plugin_manager
        self.logger = logging.getLogger("plugin_registry")
    
    def load_builtin_plugins(self, config: Optional[Dict[str, Any]] = None):
        """Load all builtin plugins."""
        plugin_configs = config or {}
        
        for name, class_path in self.BUILTIN_PLUGINS.items():
            if name in plugin_configs and not plugin_configs[name].get("enabled", True):
                self.logger.info(f"Skipping disabled builtin plugin: {name}")
                continue
            
            try:
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
                
                plugin_config = plugin_configs.get(name, {})
                self.plugin_manager.load_plugin(plugin_class, plugin_config)
                
            except Exception as e:
                self.logger.error(f"Failed to load builtin plugin {name}: {e}")
    
    def load_plugins_from_config(self, config: Dict[str, Any]):
        """Load plugins from configuration."""
        plugins_config = config.get("plugins", {})
        
        for name, plugin_config in plugins_config.items():
            if not plugin_config.get("enabled", True):
                continue
            
            class_path = plugin_config.get("class")
            if not class_path:
                self.logger.warning(f"Plugin {name} missing class path")
                continue
            
            try:
                module_path, class_name = class_path.rsplit(".", 1)
                module = importlib.import_module(module_path)
                plugin_class = getattr(module, class_name)
                
                self.plugin_manager.load_plugin(plugin_class, plugin_config.get("config", {}))
                
            except Exception as e:
                self.logger.error(f"Failed to load plugin {name}: {e}")
    
    def register_custom_plugin(self, plugin_class: Type[Plugin], config: Optional[Dict[str, Any]] = None):
        """Register a custom plugin class directly."""
        self.plugin_manager.load_plugin(plugin_class, config)


# Example plugin implementations
class ExampleStealthPlugin(EnginePlugin):
    """Example custom stealth plugin."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="custom_stealth",
            version="1.0.0",
            description="Custom stealth engine with advanced fingerprinting",
            plugin_type=PluginType.ENGINE,
            entry_point="scraper.engines.stealth.StealthManager",
        )
    
    async def initialize(self) -> bool:
        self.logger.info("Initializing custom stealth plugin")
        return True
    
    async def shutdown(self) -> bool:
        return True
    
    async def scrape(self, request) -> Any:
        # Custom scraping logic
        pass
    
    async def health_check(self) -> bool:
        return True


class DataCleaningTransformer(TransformerPlugin):
    """Plugin for cleaning and normalizing scraped data."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="data_cleaner",
            version="1.0.0",
            description="Cleans and normalizes scraped data",
            plugin_type=PluginType.TRANSFORMER,
        )
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True
    
    async def transform(self, data: Any, context: Optional[Dict] = None) -> Any:
        if isinstance(data, dict):
            cleaned = {}
            for key, value in data.items():
                # Clean key
                clean_key = key.strip().lower().replace(" ", "_")
                
                # Clean value
                if isinstance(value, str):
                    clean_value = value.strip()
                    # Remove extra whitespace
                    clean_value = " ".join(clean_value.split())
                elif isinstance(value, list):
                    clean_value = [self.transform(v) for v in value]
                elif isinstance(value, dict):
                    clean_value = await self.transform(value)
                else:
                    clean_value = value
                
                cleaned[clean_key] = clean_value
            
            return cleaned
        
        return data
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True


class RateLimitMiddleware(MiddlewarePlugin):
    """Middleware for rate limiting requests."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="rate_limiter",
            version="1.0.0",
            description="Rate limiting middleware",
            plugin_type=PluginType.MIDDLEWARE,
        )
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        super().__init__(config)
        self.requests_per_second = config.get("requests_per_second", 2.0) if config else 2.0
        self._last_request = {}
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True
    
    async def before_request(self, request: Any) -> Any:
        # Implement rate limiting logic
        domain = getattr(request, "url", "").split("/")[2] if hasattr(request, "url") else "default"
        
        now = time.time()
        if domain in self._last_request:
            elapsed = now - self._last_request[domain]
            min_interval = 1.0 / self.requests_per_second
            if elapsed < min_interval:
                await asyncio.sleep(min_interval - elapsed)
        
        self._last_request[domain] = time.time()
        return request
    
    async def after_response(self, response: Any) -> Any:
        return response
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True


class ErrorHandlingHook(HookPlugin):
    """Hook for handling errors and retries."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="error_handler",
            version="1.0.0",
            description="Handles errors and implements retry logic",
            plugin_type=PluginType.HOOK,
        )
    
    async def on_error(self, context: Dict[str, Any]) -> Dict[str, Any]:
        error = context.get("error")
        attempt = context.get("attempt", 0)
        max_retries = context.get("max_retries", 3)
        
        if attempt >= max_retries:
            context["should_retry"] = False
            return context
        
        # Determine if error is retryable
        retryable_errors = [
            "timeout",
            "connection",
            "503",
            "429",
            "rate limit",
            "temporary",
        ]
        
        error_str = str(error).lower()
        if any(err in error_str for err in retryable_errors):
            context["should_retry"] = True
            context["retry_delay"] = min(2 ** attempt, 60)  # Exponential backoff
        else:
            context["should_retry"] = False
        
        return context
    
    async def on_retry(self, context: Dict[str, Any]) -> Dict[str, Any]:
        delay = context.get("retry_delay", 1)
        await asyncio.sleep(delay)
        context["attempt"] = context.get("attempt", 0) + 1
        return context
    
    async def on_rate_limit(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Handle rate limiting
        retry_after = context.get("retry_after", 60)
        await asyncio.sleep(retry_after)
        return context
    
    async def on_captcha(self, context: Dict[str, Any]) -> Dict[str, Any]:
        # Handle CAPTCHA
        context["needs_captcha_solve"] = True
        return context
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True


class JSONExporter(ExporterPlugin):
    """Export data to JSON format."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="json_exporter",
            version="1.0.0",
            description="Exports data to JSON format",
            plugin_type=PluginType.EXPORTER,
        )
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True
    
    async def export(self, data: Any, output_path: str, options: Dict[str, Any]) -> bool:
        import json
        
        try:
            indent = options.get("indent", 2)
            ensure_ascii = options.get("ensure_ascii", False)
            
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii, default=str)
            
            return True
        except Exception as e:
            return False
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True


class CSVExporter(ExporterPlugin):
    """Export data to CSV format."""
    
    @classmethod
    def get_metadata(cls) -> PluginMetadata:
        return PluginMetadata(
            name="csv_exporter",
            version="1.0.0",
            description="Exports data to CSV format",
            plugin_type=PluginType.EXPORTER,
        )
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True
    
    async def export(self, data: Any, output_path: str, options: Dict[str, Any]) -> bool:
        import csv
        
        try:
            if not isinstance(data, list):
                data = [data]
            
            if not data:
                return False
            
            # Flatten nested objects
            flat_data = []
            for item in data:
                flat = self._flatten_dict(item)
                flat_data.append(flat)
            
            fieldnames = set()
            for row in flat_data:
                fieldnames.update(row.keys())
            
            with open(output_path, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=sorted(fieldnames))
                writer.writeheader()
                writer.writerows(flat_data)
            
            return True
        except Exception as e:
            return False
    
    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                items.append((new_key, json.dumps(v)))
            else:
                items.append((new_key, v))
        return dict(items)
    
    async def initialize(self) -> bool:
        return True
    
    async def shutdown(self) -> bool:
        return True


# Plugin discovery and auto-loading
async def create_plugin_manager(config: Optional[Dict[str, Any]] = None) -> PluginManager:
    """Create and initialize plugin manager with configuration."""
    manager = PluginManager()
    
    # Add default plugin directories
    manager.add_plugin_dir("plugins")
    manager.add_plugin_dir("custom_plugins")
    
    # Load builtin plugins
    registry = PluginRegistry(manager)
    registry.load_builtin_plugins(config)
    
    # Load custom plugins from config
    if config:
        registry.load_plugins_from_config(config)
    
    # Initialize all plugins
    await manager.initialize_all()
    
    return manager


def get_plugin_manager() -> PluginManager:
    """Get or create global plugin manager."""
    if not hasattr(get_plugin_manager, "_instance"):
        get_plugin_manager._instance = asyncio.run(create_plugin_manager())
    return get_plugin_manager._instance


# Export all plugin-related classes
__all__ = [
    "PluginType",
    "PluginMetadata",
    "Plugin",
    "EnginePlugin",
    "ExtractorPlugin",
    "TransformerPlugin",
    "MiddlewarePlugin",
    "HookPlugin",
    "ValidatorPlugin",
    "ExporterPlugin",
    "PluginInstance",
    "PluginManager",
    "PluginRegistry",
    "ExampleStealthPlugin",
    "DataCleaningTransformer",
    "RateLimitMiddleware",
    "ErrorHandlingHook",
    "JSONExporter",
    "CSVExporter",
    "create_plugin_manager",
    "get_plugin_manager",
]