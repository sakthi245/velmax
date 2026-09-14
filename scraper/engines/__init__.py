from __future__ import annotations

from .interfaces import (
    EngineCapability,
    EngineMetadata,
    EngineConfig,
    HTTPRequest,
    HTTPResponse,
    BrowserRequest,
    BrowserResponse,
    InteractionStep,
    InteractionSequence,
    InteractionResult,
    APIEndpoint,
    CrawlStrategy,
    PageResult,
    HTTPEngine,
    BrowserEngine,
    BrowserContext,
    ManagedEngine,
    CloudEngine,
    APIEngine,
    HybridEngine,
    BaseEngine,
    EngineFactory,
)

from .registry import EngineRegistry
from .registry_v2 import EngineRegistryV2
from .selector import EngineSelector

from .base_v2 import (
    BaseEngineV2,
    BaseHTTPEngineV2,
    BaseBrowserEngineV2,
    BrowserContextWrapper,
    BaseManagedEngineV2,
    BaseCloudEngineV2,
    BaseAPIEngineV2,
    BaseHybridEngineV2,
    EngineMetrics,
    CircuitBreaker,
)

from .session_manager import (
    SessionManager,
    SessionConfig,
    Session,
    Cookie,
    AuthToken,
    ProxySessionManager,
    SessionContext,
    create_session_manager,
)

from .browser_pool import AdaptiveBrowserPool, create_adaptive_pool

from .selectors import (
    SelectorEngine,
    SelectorConfig,
    SelectorResult,
    SelectorType,
    create_selector_engine,
)

from .interactions import (
    InteractionExecutor,
    InteractionConfig,
    ActionType,
    InteractionStep as InteractionStepV2,
    InteractionSequence as InteractionSequenceV2,
)

from .stealth import (
    StealthManager,
    StealthConfig,
    FingerprintGenerator,
    apply_stealth,
)

# Register V2 engines (replacing legacy engines)
from .http_engine import HTTPEngine as HTTPEngineV2
from .browser_engine import BrowserEngine as BrowserEngineV2
from .managed_engine import ManagedEngine as ManagedEngineV2
from .cloud_engine import CloudEngine as CloudEngineV2
from .api_engine import APIEngine as APIEngineV2
from .scrapy_engine_v2 import ScrapyEngineV2
from .playwright_engine_v2 import PlaywrightEngineV2
from .firecrawl_engine_v2 import FirecrawlEngineV2
from .crawlee_engine_v2 import CrawleeEngineV2

# New search pipeline engines
from .playwright_search import PlaywrightSearchEngine
from .duckduckgo_search import DuckDuckGoSearchEngine
from .query_expander import QueryExpanderEngine
from .relevance_ranker import RelevanceRankerEngine
from .search_pipeline import SearchPipelineEngine
from .tinyfish import TinyFishSearchEngine
from .serpapi import SerpAPISearchEngine
from .goal_parser import GoalParser, ParsedGoal

# Register with legacy string names for backward compatibility
EngineRegistry.register("scrapy", ScrapyEngineV2, ScrapyEngineV2.metadata)
EngineRegistry.register("playwright", PlaywrightEngineV2, PlaywrightEngineV2.metadata)
EngineRegistry.register("firecrawl", FirecrawlEngineV2, FirecrawlEngineV2.metadata)
EngineRegistry.register("crawlee", CrawleeEngineV2, CrawleeEngineV2.metadata)
EngineRegistry.register("http", HTTPEngineV2, HTTPEngineV2.metadata)
EngineRegistry.register("browser", BrowserEngineV2, BrowserEngineV2.metadata)
EngineRegistry.register("managed", ManagedEngineV2, ManagedEngineV2.metadata)
EngineRegistry.register("cloud", CloudEngineV2, CloudEngineV2.metadata)
EngineRegistry.register("api", APIEngineV2, APIEngineV2.metadata)

# New search pipeline engines
EngineRegistry.register("playwright_search", PlaywrightSearchEngine, PlaywrightSearchEngine.metadata)
EngineRegistry.register("duckduckgo_search", DuckDuckGoSearchEngine, DuckDuckGoSearchEngine.metadata)
EngineRegistry.register("query_expander", QueryExpanderEngine, QueryExpanderEngine.metadata)
EngineRegistry.register("relevance_ranker", RelevanceRankerEngine, RelevanceRankerEngine.metadata)
EngineRegistry.register("search_pipeline", SearchPipelineEngine, SearchPipelineEngine.metadata)
EngineRegistry.register("tinyfish", TinyFishSearchEngine, TinyFishSearchEngine.metadata)
EngineRegistry.register("serpapi", SerpAPISearchEngine, SerpAPISearchEngine.metadata)

__all__ = [
    "EngineCapability",
    "EngineMetadata",
    "EngineConfig",
    "HTTPRequest",
    "HTTPResponse",
    "BrowserRequest",
    "BrowserResponse",
    "InteractionStep",
    "InteractionSequence",
    "InteractionResult",
    "APIEndpoint",
    "CrawlStrategy",
    "PageResult",
    "HTTPEngine",
    "BrowserEngine",
    "BrowserContext",
    "ManagedEngine",
    "CloudEngine",
    "APIEngine",
    "HybridEngine",
    "BaseEngine",
    "EngineFactory",
    "EngineRegistry",
    "EngineSelector",
    "BaseEngineV2",
    "BaseHTTPEngineV2",
    "BaseBrowserEngineV2",
    "BrowserContextWrapper",
    "BaseManagedEngineV2",
    "BaseCloudEngineV2",
    "BaseAPIEngineV2",
    "BaseHybridEngineV2",
    "EngineMetrics",
    "CircuitBreaker",
    "EngineRegistryV2",
    "SessionManager",
    "SessionConfig",
    "Session",
    "Cookie",
    "AuthToken",
    "ProxySessionManager",
    "SessionContext",
    "create_session_manager",
    "SelectorEngine",
    "SelectorConfig",
    "SelectorResult",
    "SelectorType",
    "create_selector_engine",
    "InteractionExecutor",
    "InteractionConfig",
    "ActionType",
    "InteractionStepV2",
    "InteractionSequenceV2",
    "AdaptiveBrowserPool",
    "create_adaptive_pool",
    "StealthManager",
    "StealthConfig",
    "FingerprintGenerator",
    "apply_stealth",
    # New search pipeline engines
    "PlaywrightSearchEngine",
    "DuckDuckGoSearchEngine",
    "QueryExpanderEngine",
    "RelevanceRankerEngine",
    "SearchPipelineEngine",
    "TinyFishSearchEngine",
    "SerpAPISearchEngine",
    "GoalParser",
    "ParsedGoal",
]