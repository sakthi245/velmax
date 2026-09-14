from __future__ import annotations

import json
import logging
import asyncio
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from groq import Groq
from ..config.schemas import EngineType, EngineCapability
from .interfaces import EngineConfig, EngineMetadata, BaseEngine
from ..utils.observability import get_logger

LOG = get_logger(__name__)


@dataclass
class QueryExpanderConfig:
    """Configuration for query expander."""
    enabled: bool = True
    model: str = "openai/gpt-oss-20b"
    api_key: str = ""
    max_queries_per_goal: int = 5
    temperature: float = 0.3
    max_tokens: int = 500
    timeout: float = 30.0


@dataclass
class ExpandedQueries:
    """Result of query expansion."""
    original_goal: str
    expanded_queries: List[str]
    model_used: str
    tokens_used: int = 0
    cost_estimate: float = 0.0


class QueryExpanderEngine(BaseEngine):
    """Groq-powered query expansion engine (free tier available)."""
    
    metadata = EngineMetadata(
        name="query_expander",
        engine_type=EngineType.API,
        capabilities={
            EngineCapability.REST_API,
            EngineCapability.LLM_EXTRACTION,
        },
        max_concurrent=2,
        avg_latency_ms=2000,
        requires_external_service=True,
        cost_per_1k_pages=0.0,  # Free tier available
    )

    def __init__(self):
        self.config = QueryExpanderConfig()
        self._client: Optional[Groq] = None

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize Groq client."""
        expander_config = config.config.get("query_expander", {})
        self.config = QueryExpanderConfig(**expander_config)
        
        if not self.config.api_key:
            import os
            self.config.api_key = os.getenv("GROQ_API_KEY", "")
        
        if not self.config.api_key:
            raise ValueError("Groq API key is required for query expansion. Set GROQ_API_KEY environment variable or provide in config.")
        
        self._client = Groq(api_key=self.config.api_key)
        self._initialized = True
        LOG.info("Query expander engine initialized with Groq")

    async def shutdown(self) -> None:
        pass

    def health_check(self) -> bool:
        return self._client is not None

    async def expand(
        self,
        goal: str,
        context: str = "",
        max_queries: Optional[int] = None,
    ) -> List[str]:
        """
        Expand a research goal into multiple optimized search queries.
        
        Args:
            goal: The research goal (e.g., "Find AI research papers on transformers")
            context: Optional additional context
            max_queries: Maximum number of queries to generate (overrides config)
            
        Returns:
            List of optimized search queries
        """
        if not self._initialized:
            raise RuntimeError("Query expander not initialized")
        
        max_q = max_queries or self.config.max_queries_per_goal
        
        # Build prompt
        prompt = self._build_expansion_prompt(goal, context, max_queries)
        
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._client.chat.completions.create(
                    model=self.config.model,
                    messages=[
                        {
                            "role": "system",
                            "content": self._get_system_prompt()
                        },
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ],
                    temperature=self.config.temperature,
                    max_tokens=self.config.max_tokens,
                    response_format={"type": "json_object"},
                )
            )
            
            content = response.choices[0].message.content
            if not content:
                raise ValueError("Empty response from Groq")
            
            # Parse JSON response
            result = json.loads(content)
            queries = result.get("queries", [])
            
            # Validate and clean queries
            queries = [q.strip() for q in queries if q.strip()]
            queries = queries[:max_queries]
            
            LOG.info(f"Expanded goal into {len(queries)} queries")
            return queries
            
        except json.JSONDecodeError as e:
            LOG.error(f"Failed to parse Groq response as JSON: {e}")
            return [goal]  # Fallback to original goal
        except Exception as e:
            LOG.error(f"Query expansion failed: {e}")
            return [goal]  # Fallback

    def _get_system_prompt(self) -> str:
        return """You are an expert search query optimizer. Convert research goals into optimized search queries for web search engines.

CRITICAL RULES:
1. PRESERVE ALL TECHNICAL SPECIFICATIONS from the goal (model numbers, generations, versions, part numbers, exact product names) - these MUST appear in queries
2. Generate SPECIFIC, TARGETED queries that will find relevant information
3. Use TECHNICAL TERMS and SPECIFIC PHRASES from the original goal
4. Include VARIATIONS (synonyms, related terms, alternative phrasings) while KEEPING the core specs
5. Consider DIFFERENT ANGLES (technical, business, academic, practical)
6. Return ONLY valid JSON with a "queries" array
7. NO explanations, NO markdown, ONLY JSON

EXAMPLES:
Goal: "Find AI research papers on transformer architectures"
Queries: [
  "transformer architecture attention mechanism paper 2024",
  "vision transformer ViT architecture review",
  "attention mechanism deep learning survey",
  "transformer neural network architecture improvements",
  "efficient transformer variants linear attention"
]

Goal: "laptops with i5 13th gen processor"
Queries: [
  "laptop i5 13th generation Intel Core i5-13xxx buy",
  "Intel Core i5 13th gen laptop specs price",
  "13th gen i5 laptop best buy deals 2024",
  "laptop i5-1335U i5-13500H i5-13600H comparison",
  "Intel 13th gen Core i5 laptop review benchmark"
]

Goal: "RTX 4090 graphics card price"
Queries: [
  "NVIDIA GeForce RTX 4090 price buy",
  "RTX 4090 24GB GDDR6X graphics card cost",
  "RTX 4090 Founders Edition vs ASUS ROG MSI",
  "RTX 4090 availability stock 2024",
  "RTX 4090 performance benchmarks gaming"
]"""

    def _build_expansion_prompt(self, goal: str, context: str, max_queries: int) -> str:
        context_str = f"\nAdditional Context: {context}" if context else ""
        return f"""Research Goal: {goal}{context_str}

Generate {self.config.max_queries_per_goal} optimized search queries to find the most relevant information for this goal.

IMPORTANT: You MUST preserve ALL technical specifications from the goal (model numbers like "i5 13th gen", "RTX 4090", "Ryzen 9 7950X", versions like "v2.0", "2024", part numbers, exact product names). These MUST appear in every query you generate.

Return JSON with "queries" array containing exactly {self.config.max_queries_per_goal} search query strings.""" 


async def create_query_expander_engine(config: EngineConfig) -> 'QueryExpanderEngine':
    """Factory function to create query expander engine."""
    import os
    engine = QueryExpanderEngine()
    await engine.initialize(config)
    return engine