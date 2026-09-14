from __future__ import annotations

import json
import logging
import asyncio
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from groq import Groq
from ..config.schemas import EngineType, EngineCapability
from .interfaces import EngineConfig, EngineMetadata, BaseEngine
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class RelevanceRankerConfig:
    """Configuration for relevance ranker."""
    enabled: bool = True
    model: str = "openai/gpt-oss-20b"
    api_key: str = ""
    temperature: float = 0.1
    max_tokens: int = 200
    max_results_to_rank: int = 20


@dataclass
class RankedResult:
    """Search result with relevance score."""
    url: str
    title: str
    snippet: str
    original_score: float = 0.0
    relevance_score: float = 0.0
    reasoning: str = ""
    source: str = ""


class RelevanceRankerEngine(BaseEngine):
    """Groq-powered relevance re-ranking engine (ultra-low token usage)."""
    
    metadata = EngineMetadata(
        name="relevance_ranker",
        engine_type=EngineType.API,
        capabilities={
            EngineCapability.REST_API,
            EngineCapability.LLM_EXTRACTION,
        },
        max_concurrent=3,
        avg_latency_ms=1500,
        requires_external_service=True,
        cost_per_1k_pages=0.0,  # Minimal token usage
    )

    def __init__(self):
        self.config = RelevanceRankerConfig()
        self._client: Optional[Any] = None

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize Groq client."""
        ranker_config = config.config.get("relevance_ranker", {})
        self.config = RelevanceRankerConfig(**ranker_config)
        
        # Check config first, then environment variable
        if not self.config.api_key:
            import os
            self.config.api_key = os.getenv("GROQ_API_KEY", "")
        
        if not self.config.api_key:
            raise ValueError("Groq API key is required for relevance ranking. Set GROQ_API_KEY environment variable or provide in config.")
        
        from groq import Groq
        self._client = Groq(api_key=self.config.api_key)
        LOG.info("Relevance ranker initialized with Groq")

    async def shutdown(self) -> None:
        pass

    def health_check(self) -> bool:
        return self._client is not None

    async def rank(
        self,
        goal: str,
        results: List[Dict[str, Any]],
        max_results: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """
        Re-rank search results by relevance to the research goal.
        
        Args:
            goal: The research goal
            results: List of search results (each with url, title, snippet)
            max_results: Maximum number of results to return
            
        Returns:
            Re-ranked list with relevance scores
        """
        if not results:
            return []
        
        # Limit input results
        results = results[:self.config.max_results_to_rank]
        
        # Build compact prompt for ranking
        prompt = self._build_ranking_prompt(goal, results)
        
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a relevance ranker. Score each result 0-100 for relevance to the research goal. Return ONLY valid JSON with a 'rankings' array. NO explanations, NO markdown."
                        },
                        {
                            "role": "user",
                            "content": self._build_ranking_prompt(goal, results[:20])
                        }
                    ],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    response_format={"type": "json_object"},
                )
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response")
            
            # Extract JSON from response (may contain reasoning text before JSON)
            import re
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                content = json_match.group(0)
            
            result = json.loads(content)
            rankings = result.get("rankings", [])
            
            # Merge scores back to original results
            ranked_map = {r["url"]: r for r in rankings}
            
            ranked_results = []
            for result in results:
                url = result.get("url", "")
                rank_info = ranked_map.get(url, {})
                result = result.copy()
                result["relevance_score"] = rank_info.get("score", 0)
                result["relevance_reason"] = rank_info.get("reason", "")
                ranked_results.append(result)
            
            # Sort by relevance score descending
            ranked_results.sort(key=lambda x: x.get("relevance_score", 0), reverse=True)
            
            return ranked_results
            
        except Exception as e:
            logging.warning(f"Relevance ranking failed: {e}")
            return results  # Return original order on failure

    def _build_ranking_prompt(self, goal: str, results: List[Dict]) -> str:
        """Build compact ranking prompt."""
        items = []
        for i, r in enumerate(results[:15]):  # Limit to 15 for token efficiency
            title = (r.get("title", "") or "")[:80]
            snippet = (r.get("snippet", "") or "")[:120]
            url = r.get("url", "")[:100]
            items.append(f"{i+1}. [{url}] {title} | {snippet}")
        
        return f"""Goal: {goal}

Rank these results 0-100 for relevance:
{chr(10).join(f'{i+1}. {item}' for i, item in enumerate(items))}

Return JSON: {{"rankings": [{{"url": "...", "score": 85, "reason": "directly answers goal"}}, ...]}}"""