from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..config.schemas import EngineType, EngineCapability, UniversalRequest, UniversalResult
from .interfaces import EngineConfig, EngineMetadata
from .tinyfish import TinyFishSearchEngine, TinyFishSearchResult
from .serpapi import SerpAPISearchEngine, SerpAPISearchResult
from .playwright_search import PlaywrightSearchEngine
from .query_expander import QueryExpanderEngine
from .relevance_ranker import RelevanceRankerEngine
from .goal_parser import GoalParser, ParsedGoal
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class SearchPipelineConfig:
    """Configuration for the search pipeline."""
    max_queries_per_goal: int = 5
    max_results_per_query: int = 10
    max_total_results: int = 50
    max_results_after_ranking: int = 20
    enable_query_expansion: bool = True
    enable_relevance_ranking: bool = True
    delay_between_queries: float = 1.0
    dedupe_results: bool = True
    min_relevance_score: float = 0.0
    engine_order: List[str] = field(default_factory=lambda: ["tinyfish", "serpapi"])


@dataclass
class PipelineResult:
    """Final pipeline output."""
    goal: str
    expanded_queries: List[str]
    raw_results_count: int
    deduped_results_count: int
    ranked_results: List[Dict[str, Any]]
    execution_time: float
    queries_used: List[str]
    tokens_used: int = 0
    cost_estimate: float = 0.0


@dataclass
class UnifiedSearchResult:
    """Unified search result from any engine."""
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0
    source: str = ""
    site_name: str = ""
    query: str = ""


class SearchPipelineEngine:
    """
    Complete search pipeline with multi-engine fallback support.
    
    Pipeline: Goal → Groq Query Expansion → Search Engines (TinyFish → SerpAPI) → Relevance Ranking → Final Results
    
    Engine Priority: tinyfish (primary) → serpapi (fallback)
    """
    
    metadata = EngineMetadata(
        name="search_pipeline",
        engine_type=EngineType.SEARCH,
        capabilities={
            EngineCapability.SEARCH,
            EngineCapability.REST_API,
            EngineCapability.LLM_EXTRACTION,
        },
        max_concurrent=2,
        avg_latency_ms=15000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,
    )

    def __init__(self):
        self.config = SearchPipelineConfig()
        self._tinyfish: Optional[TinyFishSearchEngine] = None
        self._serpapi: Optional[SerpAPISearchEngine] = None
        self._playwright_search: Optional[PlaywrightSearchEngine] = None
        self._query_expander: Optional[QueryExpanderEngine] = None
        self._relevance_ranker: Optional[RelevanceRankerEngine] = None

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize all sub-engines."""
        pipeline_config = config.config.get("search_pipeline", {})
        LOG.info(f"SearchPipelineEngine pipeline_config keys: {list(pipeline_config.keys())}")
        
        # Initialize query expander
        self._query_expander = QueryExpanderEngine()
        await self._query_expander.initialize(EngineConfig(
            name="query_expander",
            config={"query_expander": pipeline_config.get("query_expander", {})}
        ))
        
        # Initialize TinyFish (Primary) - only if API key provided
        tinyfish_config = pipeline_config.get("tinyfish_search", {})
        LOG.info(f"TinyFish config keys: {list(tinyfish_config.keys())}")
        if tinyfish_config.get("api_key"):
            self._tinyfish = TinyFishSearchEngine()
            await self._tinyfish.initialize(EngineConfig(
                name="tinyfish",
                config={"tinyfish_search": tinyfish_config}
            ))
            LOG.info("TinyFish initialized as primary search engine")
        else:
            LOG.warning("TinyFish API key not provided, skipping TinyFish initialization")
        
        # Initialize SerpAPI as fallback (only if enabled and API key present)
        serpapi_config = pipeline_config.get("serpapi_search", {})
        LOG.info(f"SerpAPI config keys: {list(serpapi_config.keys())}, enabled: {serpapi_config.get('enabled', False)}")
        if serpapi_config.get("enabled", False) and serpapi_config.get("api_key"):
            self._serpapi = SerpAPISearchEngine()
            await self._serpapi.initialize(EngineConfig(
                name="serpapi",
                config={"serpapi_search": serpapi_config}
            ))
            LOG.info("SerpAPI initialized as fallback")
        else:
            LOG.info("SerpAPI not enabled or no API key, skipping fallback")
        
        # Initialize relevance ranker
        self._relevance_ranker = RelevanceRankerEngine()
        await self._relevance_ranker.initialize(EngineConfig(
            name="relevance_ranker",
            config={"relevance_ranker": pipeline_config.get("relevance_ranker", {})}
        ))
        
        # Initialize PlaywrightSearchEngine as last-resort fallback (for tests without API keys)
        self._playwright_search = PlaywrightSearchEngine()
        playwright_config = pipeline_config.get("playwright_search", {})
        if playwright_config:
            await self._playwright_search.initialize(EngineConfig(
                name="playwright_search",
                config={"playwright_search": playwright_config}
            ))
            LOG.info("PlaywrightSearchEngine initialized as last-resort fallback")
        
        LOG.info("Search pipeline initialized (TinyFish primary, SerpAPI fallback, Playwright last-resort)")

    async def shutdown(self) -> None:
        if self._tinyfish:
            await self._tinyfish.shutdown()
        if self._serpapi:
            await self._serpapi.shutdown()
        if self._playwright_search:
            await self._playwright_search.shutdown()
        if self._query_expander:
            await self._query_expander.shutdown()
        if self._relevance_ranker:
            await self._relevance_ranker.shutdown()

    def health_check(self) -> bool:
        return True

    async def search(
        self,
        goal: str,
        max_results: int = 20,
        schema: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Complete search pipeline: Goal → Queries → Search Engines (fallback) → Rank → Results.
        
        Args:
            goal: Research goal (e.g., "Find AI papers on transformers")
            max_results: Maximum final results to return
            schema: Optional extraction schema (for later extraction phase)
            
        Returns:
            List of ranked, deduplicated search results
        """
        start_time = time.time()
        
        LOG.info(f"Starting search pipeline for goal: {goal}")
        
        # Step 1: Query Expansion (Groq)
        expanded_queries = []
        if self._query_expander:
            try:
                expanded_queries = await self._query_expander.expand(goal)
                LOG.info(f"Expanded into {len(expanded_queries)} queries: {expanded_queries}")
            except Exception as e:
                LOG.warning(f"Query expansion failed, using original goal: {e}")
                expanded_queries = [goal]
        else:
            expanded_queries = [goal]
        
        # Limit queries
        expanded_queries = expanded_queries[:self.config.max_queries_per_goal]
        
        # Step 2: Search with fallback across engines
        all_results = []
        seen_urls = set()
        
        # Engine priority order: tinyfish -> serpapi -> playwright_search
        search_engines = []
        if self._tinyfish:
            search_engines.append(("tinyfish", self._tinyfish))
        if self._serpapi:
            search_engines.append(("serpapi", self._serpapi))
        if self._playwright_search:
            search_engines.append(("playwright_search", self._playwright_search))
        
        for engine_name, engine in search_engines:
            if engine is None:
                continue
                
            try:
                LOG.info(f"Searching with engine: {engine_name}")
                engine_results = []
                
                for i, query in enumerate(expanded_queries):
                    try:
                        LOG.info(f"Searching ({i+1}/{len(expanded_queries)}) with {engine_name}: {query}")
                        results = await engine.search(query, max_results=self.config.max_results_per_query)
                        
                        # Deduplicate
                        for result in results:
                            if result.url not in seen_urls:
                                seen_urls.add(result.url)
                                engine_results.append({
                                    "url": result.url,
                                    "title": result.title,
                                    "snippet": result.snippet,
                                    "source": engine.metadata.name,
                                    "query": query,
                                    "position": result.position,
                                })
                        
                        if i < len(expanded_queries) - 1:
                            await asyncio.sleep(self.config.delay_between_queries)
                            
                    except Exception as e:
                        LOG.warning(f"Search failed for query '{query}' with {engine_name}: {e}")
                        continue
                
                all_results.extend(engine_results)
                LOG.info(f"Engine {engine_name} returned {len(engine_results)} unique results")
                
                # If we got results, don't try fallback engines
                if engine_results:
                    break
                    
            except Exception as e:
                LOG.warning(f"Engine {engine_name} failed: {e}")
                continue
        
        LOG.info(f"Found {len(all_results)} raw results, deduplicated to {len(seen_urls)}")
        
        # Step 3: Relevance Ranking
        ranked_results = all_results
        if self._relevance_ranker and all_results:
            try:
                ranked = await self._relevance_ranker.rank(goal, all_results)
                ranked_results = ranked
                LOG.info(f"Re-ranked {len(ranked_results)} results")
            except Exception as e:
                LOG.warning(f"Relevance ranking failed: {e}")
                ranked_results = all_results
        
        # Limit final results
        final_results = ranked_results[:self.config.max_results_after_ranking]
        
        execution_time = time.time() - start_time
        LOG.info(f"Pipeline completed in {execution_time:.2f}s, returned {len(final_results)} results")
        
        return final_results

    async def scrape(self, request: UniversalRequest) -> UniversalResult:
        """
        Scrape method compatible with UniversalRunner fallback chain.
        Uses the search pipeline to find results for the given goal.
        
        Args:
            request: UniversalRequest with goal and optional schema
            
        Returns:
            UniversalResult with search results
        """
        import time
        start_time = time.time()
        
        goal = request.goal or ""
        if not goal:
            return UniversalResult(
                success=False,
                url=request.url,
                error="No goal provided for search",
                engine_used=self.metadata.name,
                latency_ms=int((time.time() - start_time) * 1000),
            )
        
        max_results = request.max_pages or 20
        schema = request.extract_schema
        
        try:
            results = await self.search(goal, max_results=max_results, schema=schema)
            
            execution_time = int((time.time() - start_time) * 1000)
            
            return UniversalResult(
                success=True,
                url=request.url or "search",
                data={"results": results},
                engine_used=self.metadata.name,
                latency_ms=execution_time,
                quality_score=0.8 if results else 0.0,
            )
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            LOG.error(f"Search pipeline scrape failed: {e}")
            return UniversalResult(
                success=False,
                url=request.url or "search",
                error=str(e),
                engine_used=self.metadata.name,
                latency_ms=execution_time,
            )

    async def discover_urls(
        self,
        goal: str,
        max_urls: int = 10,
        depth: str = "quick",
    ) -> List[str]:
        """
        Discover URLs from a natural language goal.
        
        This is the main entry point for autonomous URL discovery.
        It parses the goal, generates optimized search queries,
        and returns a list of relevant URLs.
        
        Args:
            goal: Natural language goal (e.g., "phones 20000-25000")
            max_urls: Maximum number of URLs to return
            depth: Profiling depth ("quick", "standard", "deep")
            
        Returns:
            List of discovered URLs
        """
        LOG.info(f"Discovering URLs for goal: {goal}, max_urls: {max_urls}")
        
        # Step 1: Parse the goal using GoalParser
        goal_parser = GoalParser()
        parsed_goal = await goal_parser.parse(goal)
        
        LOG.info(f"Parsed goal - Category: {parsed_goal.category}, "
                 f"Price: {parsed_goal.price_min}-{parsed_goal.price_max}, "
                 f"Brand: {parsed_goal.brand}, Location: {parsed_goal.location}, "
                 f"Intent: {parsed_goal.intent}, Confidence: {parsed_goal.confidence:.2f}")
        
        # Step 2: Generate optimized search queries from parsed goal
        search_queries = parsed_goal.to_search_queries()
        LOG.info(f"Generated {len(search_queries)} search queries: {search_queries}")
        
        # Step 3: Use existing search pipeline to find results
        # Limit queries to max_queries_per_goal
        search_queries = search_queries[:self.config.max_queries_per_goal]
        
        all_results = []
        seen_urls = set()
        
        # Engine priority order: tinyfish -> serpapi -> playwright_search
        search_engines = []
        if self._tinyfish:
            search_engines.append(("tinyfish", self._tinyfish))
        if self._serpapi:
            search_engines.append(("serpapi", self._serpapi))
        if self._playwright_search:
            search_engines.append(("playwright_search", self._playwright_search))
        
        for engine_name, engine in search_engines:
            if engine is None:
                continue
                
            try:
                LOG.info(f"Discovering URLs with engine: {engine_name}")
                engine_results = []
                
                for i, query in enumerate(search_queries):
                    try:
                        LOG.info(f"Searching ({i+1}/{len(search_queries)}) with {engine_name}: {query}")
                        results = await engine.search(query, max_results=self.config.max_results_per_query)
                        
                        # Deduplicate
                        for result in results:
                            if result.url not in seen_urls:
                                seen_urls.add(result.url)
                                engine_results.append({
                                    "url": result.url,
                                    "title": result.title,
                                    "snippet": result.snippet,
                                    "source": engine.metadata.name,
                                    "query": query,
                                    "position": result.position,
                                })
                        
                        if i < len(search_queries) - 1:
                            await asyncio.sleep(self.config.delay_between_queries)
                            
                    except Exception as e:
                        LOG.warning(f"Search failed for query '{query}' with {engine_name}: {e}")
                        continue
                
                all_results.extend(engine_results)
                LOG.info(f"Engine {engine_name} returned {len(engine_results)} unique results")
                
                # If we got enough results, don't try fallback engines
                if len(all_results) >= max_urls:
                    break
                    
            except Exception as e:
                LOG.warning(f"Engine {engine_name} failed: {e}")
                continue
        
        # Limit final results
        final_results = all_results[:max_urls]
        
        # Extract URLs
        urls = [r["url"] for r in final_results]
        
        LOG.info(f"URL discovery completed, found {len(urls)} URLs")
        
        return urls


async def create_search_pipeline_engine(config: EngineConfig) -> SearchPipelineEngine:
    """Factory function to create SearchPipelineEngine instance."""
    engine = SearchPipelineEngine()
    await engine.initialize(config)
    return engine