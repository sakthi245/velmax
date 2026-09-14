from __future__ import annotations
from typing import Dict, Type, Optional, List
from .base import BaseEngine, EngineMetadata, EngineCapability
from .interfaces import EngineConfig
import logging

LOG = logging.getLogger(__name__)

class EngineRegistry:
    _engines: Dict[str, Type[BaseEngine]] = {}
    _instances: Dict[str, BaseEngine] = {}
    _metadata: Dict[str, EngineMetadata] = {}
    
    @classmethod
    def register(cls, name: str, engine_class: Type[BaseEngine], metadata: EngineMetadata):
        cls._engines[name] = engine_class
        cls._metadata[name] = metadata
        LOG.debug(f"Registered engine: {name}")
    
    @classmethod
    async def get(cls, name: str, config: dict) -> BaseEngine:
        if name not in cls._engines:
            available = list(cls._engines.keys())
            raise ValueError(f"Engine '{name}' not registered. Available: {available}")
        
        if name not in cls._instances:
            engine = cls._engines[name]()
            # Wrap dict in EngineConfig for V2 engines
            engine_config = EngineConfig(name=name, config=config)
            await engine.initialize(engine_config)
            cls._instances[name] = engine
            LOG.info(f"Initialized engine: {name}")
        
        return cls._instances[name]
    
    @classmethod
    def select_best(cls, required: List[EngineCapability], exclude: List[str] = None) -> Optional[str]:
        exclude = exclude or []
        candidates = [
            (name, meta) for name, meta in cls._metadata.items()
            if name not in exclude and all(c in meta.capabilities for c in required)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[1].cost_per_1k_pages, -x[1].max_concurrent, x[1].avg_latency_ms))
        return candidates[0][0]
    
    @classmethod
    def get_available(cls) -> List[str]:
        return list(cls._engines.keys())
    
    @classmethod
    def get_metadata(cls, name: str) -> Optional[EngineMetadata]:
        return cls._metadata.get(name)
    
    @classmethod
    async def shutdown_all(cls):
        for engine in cls._instances.values():
            try:
                await engine.shutdown()
            except Exception as e:
                LOG.warning(f"Error shutting down engine: {e}")
        cls._instances.clear()
    
    @classmethod
    def is_registered(cls, name: str) -> bool:
        return name in cls._engines