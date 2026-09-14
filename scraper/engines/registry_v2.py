from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set, Type

from .interfaces import (
    BaseEngine,
    EngineConfig,
    EngineMetadata,
    EngineCapability,
    HTTPEngine,
    BrowserEngine,
    ManagedEngine,
    CloudEngine,
    APIEngine,
    HybridEngine,
)
from .search_pipeline import SearchPipelineEngine
from ..config.schemas import EngineType

LOG = logging.getLogger(__name__)


@dataclass
class EngineRegistration:
    engine_type: EngineType
    factory: Callable[[EngineConfig], Any]
    metadata: EngineMetadata
    config_class: Optional[type] = None
    default_config: Dict[str, Any] = field(default_factory=dict)
    health_check_interval: int = 30
    enabled: bool = True


class EngineRegistryV2:
    """Enhanced engine registry with health monitoring and capability-based selection."""

    _registrations: Dict[EngineType, EngineRegistration] = {}
    _instances: Dict[EngineType, BaseEngine] = {}
    _health_status: Dict[EngineType, bool] = {}
    _last_health_check: Dict[EngineType, float] = {}
    _initialization_times: Dict[EngineType, float] = {}
    _error_counts: Dict[EngineType, int] = {}
    _lock = asyncio.Lock()

    @classmethod
    def clear(cls):
        """Clear all registry state for test isolation."""
        cls._registrations.clear()
        cls._instances.clear()
        cls._health_status.clear()
        cls._last_health_check.clear()
        cls._initialization_times.clear()
        cls._error_counts.clear()

    @classmethod
    def register(
        cls,
        engine_type: EngineType,
        factory: Callable[[EngineConfig], Any],
        metadata: EngineMetadata,
        config_class: Optional[type] = None,
        default_config: Optional[Dict[str, Any]] = None,
        health_check_interval: int = 30,
    ):
        """Register an engine factory."""
        registration = EngineRegistration(
            engine_type=engine_type,
            factory=factory,
            metadata=metadata,
            config_class=config_class,
            default_config=default_config or {},
            health_check_interval=health_check_interval,
        )
        cls._registrations[engine_type] = registration
        cls._health_status[engine_type] = True
        cls._error_counts[engine_type] = 0
        LOG.info(f"Registered engine: {engine_type.value}")

    @classmethod
    def unregister(cls, engine_type: EngineType):
        """Unregister an engine."""
        if engine_type in cls._registrations:
            del cls._registrations[engine_type]
            if engine_type in cls._instances:
                del cls._instances[engine_type]
            if engine_type in cls._health_status:
                del cls._health_status[engine_type]
            LOG.info(f"Unregistered engine: {engine_type.value}")

    @classmethod
    async def get(cls, engine_type: EngineType, config: EngineConfig) -> BaseEngine:
        """Get or create engine instance."""
        async with cls._lock:
            if engine_type not in cls._registrations:
                available = [e.value for e in cls._registrations.keys()]
                raise ValueError(f"Engine '{engine_type.value}' not registered. Available: {available}")

            if engine_type not in cls._instances:
                registration = cls._registrations[engine_type]
                if not registration.enabled:
                    raise RuntimeError(f"Engine {engine_type.value} is disabled")

                start_time = time.time()
                try:
                    engine_or_coro = registration.factory(config)
                    if asyncio.iscoroutine(engine_or_coro):
                        engine = await engine_or_coro
                    else:
                        engine = engine_or_coro
                    await engine.initialize(config)
                    cls._instances[engine_type] = engine
                    cls._initialization_times[engine_type] = time.time() - start_time
                    LOG.info(f"Initialized engine: {engine_type.value} in {cls._initialization_times[engine_type]:.2f}s")
                except Exception as e:
                    cls._error_counts[engine_type] = cls._error_counts.get(engine_type, 0) + 1
                    LOG.error(f"Failed to initialize engine {engine_type.value}: {e}")
                    raise

            return cls._instances[engine_type]

    @classmethod
    async def get_or_create(
        cls,
        engine_type: EngineType,
        config: Optional[EngineConfig] = None,
    ) -> BaseEngine:
        """Get existing instance or create with default config."""
        if engine_type in cls._instances:
            return cls._instances[engine_type]

        if config is None:
            config = EngineConfig(name=engine_type.value, config={})

        return await cls.get(engine_type, config)

    @classmethod
    def select_best(
        cls,
        required_capabilities: List[EngineCapability],
        exclude: List[EngineType] = None,
        prefer_local: bool = True,
        max_cost: float = float('inf'),
    ) -> Optional[EngineType]:
        """Select best engine based on capabilities and constraints."""
        exclude = exclude or []
        candidates = []

        for engine_type, registration in cls._registrations.items():
            if engine_type in exclude:
                continue
            if not registration.enabled:
                continue
            if not cls._health_status.get(engine_type, True):
                continue
            if registration.metadata.cost_per_1k_pages > max_cost:
                continue
            if not all(c in registration.metadata.capabilities for c in required_capabilities):
                continue

            score = cls._calculate_engine_score(
                registration,
                required_capabilities,
                prefer_local,
            )
            candidates.append((score, engine_type))

        if not candidates:
            return None

        candidates.sort(reverse=True)
        return candidates[0][1]

    @classmethod
    def _calculate_engine_score(
        cls,
        registration: EngineRegistration,
        required: List[EngineCapability],
        prefer_local: bool,
    ) -> float:
        """Calculate engine suitability score."""
        score = 0.0

        # Capability match
        capability_match = len([c for c in required if c in registration.metadata.capabilities])
        score += capability_match * 10.0

        # Health
        if cls._health_status.get(registration.engine_type, True):
            score += 5.0

        # Cost efficiency (lower cost = higher score)
        cost = registration.metadata.cost_per_1k_pages
        if cost > 0:
            score += 10.0 / (1.0 + cost)

        # Latency (lower = better)
        latency = registration.metadata.avg_latency_ms
        score += max(0, 10.0 - latency / 1000)

        # Concurrency
        score += min(registration.metadata.max_concurrent / 10.0, 5.0)

        # Prefer local engines
        if prefer_local and not registration.metadata.requires_external_service:
            score += 5.0

        # Error penalty
        errors = cls._error_counts.get(registration.engine_type, 0)
        score -= errors * 2.0

        return score

    @classmethod
    async def health_check_all(cls) -> Dict[EngineType, bool]:
        """Run health checks on all registered engines."""
        results = {}
        for engine_type, engine in cls._instances.items():
            try:
                healthy = engine.health_check()
                results[engine_type] = healthy
                cls._health_status[engine_type] = healthy
                if not healthy:
                    LOG.warning(f"Engine {engine_type.value} health check failed")
            except Exception as e:
                LOG.error(f"Health check failed for {engine_type.value}: {e}")
                results[engine_type] = False
                cls._health_status[engine_type] = False
        return results

    @classmethod
    async def health_check(cls, engine_type: EngineType) -> bool:
        """Run health check on specific engine."""
        if engine_type not in cls._instances:
            return False

        engine = cls._instances[engine_type]
        try:
            healthy = engine.health_check()
            cls._health_status[engine_type] = healthy
            return healthy
        except Exception as e:
            LOG.error(f"Health check failed for {engine_type.value}: {e}")
            cls._health_status[engine_type] = False
            return False

    @classmethod
    def get_available(cls) -> List[EngineType]:
        """Get list of available (healthy) engine types."""
        return [
            et for et, reg in cls._registrations.items()
            if reg.enabled and cls._health_status.get(et, True)
        ]

    @classmethod
    def get_metadata(cls, engine_type: EngineType) -> Optional[EngineMetadata]:
        """Get engine metadata."""
        if engine_type in cls._registrations:
            return cls._registrations[engine_type].metadata
        return None

    @classmethod
    def get_stats(cls) -> Dict[str, Any]:
        """Get registry statistics."""
        return {
            "registered": len(cls._registrations),
            "initialized": len(cls._instances),
            "healthy": sum(1 for h in cls._health_status.values() if h),
            "engines": {
                et.value: {
                    "initialized": et in cls._instances,
                    "healthy": cls._health_status.get(et, True),
                    "init_time": cls._initialization_times.get(et, 0),
                    "errors": cls._error_counts.get(et, 0),
                }
                for et in cls._registrations
            }
        }

    @classmethod
    async def shutdown_all(cls):
        """Shutdown all engine instances."""
        async with cls._lock:
            for engine_type, engine in cls._instances.items():
                try:
                    await engine.shutdown()
                    LOG.info(f"Shutdown engine: {engine_type.value}")
                except Exception as e:
                    LOG.error(f"Error shutting down {engine_type.value}: {e}")
            cls._instances.clear()
            cls._health_status.clear()
            cls._initialization_times.clear()
            cls._error_counts.clear()

    @classmethod
    def is_registered(cls, engine_type: EngineType) -> bool:
        return engine_type in cls._registrations

    @classmethod
    def get_engine_instance(cls, engine_type: EngineType) -> Optional[BaseEngine]:
        return cls._instances.get(engine_type)


def register_default_engines():
    """Register all default engines."""
    from .http_engine import create_http_engine, HTTPEngine
    from .browser_engine import create_browser_engine, BrowserEngine
    from .crawlee_engine_v2 import create_crawlee_engine_v2, CrawleeEngineV2
    from .cloud_engine import create_cloud_engine, CloudEngine
    from .api_engine import create_api_engine, APIEngine
    from .search_pipeline import SearchPipelineEngine, create_search_pipeline_engine
    from ..config.schemas import EngineType

    EngineRegistryV2.register(
        EngineType.HTTP,
        create_http_engine,
        HTTPEngine.metadata,
        default_config={"enabled": True},
    )

    EngineRegistryV2.register(
        EngineType.BROWSER,
        create_browser_engine,
        BrowserEngine.metadata,
        default_config={"enabled": True},
    )

    EngineRegistryV2.register(
        EngineType.MANAGED,
        create_crawlee_engine_v2,
        CrawleeEngineV2.metadata,
        default_config={"enabled": True},
    )

    EngineRegistryV2.register(
        EngineType.CLOUD,
        create_cloud_engine,
        CloudEngine.metadata,
        default_config={"enabled": True},
    )

    EngineRegistryV2.register(
        EngineType.API,
        create_api_engine,
        APIEngine.metadata,
        default_config={"enabled": True},
    )

    EngineRegistryV2.register(
        EngineType.SEARCH,
        create_search_pipeline_engine,
        SearchPipelineEngine.metadata,
        default_config={"enabled": True},
    )


# Auto-register on import
register_default_engines()


async def create_search_pipeline_engine(config: EngineConfig) -> SearchPipelineEngine:
    engine = SearchPipelineEngine()
    await engine.initialize(config)
    return engine

# Search pipeline engine
EngineRegistryV2.register(
    EngineType.SEARCH,
    create_search_pipeline_engine,
    SearchPipelineEngine.metadata,
    default_config={"enabled": True},
)