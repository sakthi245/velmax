"""Groq LLM Engine for structured extraction and content generation."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .interfaces import APIEngine, EngineConfig, EngineMetadata
from ..config.schemas import EngineCapability, EngineType
from ..utils.observability import get_logger

logger = logging.getLogger(__name__)


@dataclass
class GroqLLMEngineConfig:
    """Configuration for Groq LLM Engine."""
    api_key: str = ""
    model: str = "openai/gpt-oss-20b"
    temperature: float = 0.1
    max_tokens: int = 4000
    timeout: float = 60.0
    max_retries: int = 3
    base_url: str = "https://api.groq.com/openai/v1"


class GroqLLMEngine(APIEngine):
    """Groq LLM Engine for content generation and structured extraction."""

    metadata = EngineMetadata(
        name="groq_llm",
        engine_type=EngineType.API,
        capabilities={
            EngineCapability.LLM_EXTRACTION,
            EngineCapability.REST_API,
        },
        max_concurrent=5,
        avg_latency_ms=2000,
        requires_external_service=True,
        cost_per_1k_pages=0.001,
    )

    def __init__(self, config: Optional[GroqLLMEngineConfig] = None):
        super().__init__()
        self.config = config or GroqLLMEngineConfig()
        self.client = None

    async def initialize(self, config: EngineConfig) -> None:
        """Initialize the engine with configuration."""
        if config.config:
            self.config = GroqLLMEngineConfig(**config.config)
        elif config.credentials:
            self.config.api_key = config.credentials.get("api_key", "")

        # Initialize Groq client
        from groq import AsyncGroq
        self.client = AsyncGroq(
            api_key=self.config.api_key or os.environ.get("GROQ_API_KEY", ""),
            base_url=self.config.base_url,
            timeout=self.config.timeout,
        )
        logger.info(f"GroqLLMEngine initialized with model: {self.config.model}")

    async def shutdown(self) -> None:
        """Shutdown the engine."""
        if self.client:
            await self.client.close()

    async def health_check(self) -> bool:
        """Check if engine is healthy."""
        if not self.client:
            return False
        try:
            # Simple API call to check connectivity
            await self.client.models.list()
            return True
        except Exception:
            return False

    async def generate(self, prompt: str, **kwargs) -> str:
        """Generate text using Groq LLM."""
        if not self.client:
            raise RuntimeError("Engine not initialized")

        model = kwargs.get("model", self.config.model)
        temperature = kwargs.get("temperature", self.config.temperature)
        max_tokens = kwargs.get("max_tokens", self.config.max_tokens)

        try:
            response = await self.client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Groq generation failed: {e}")
            raise

    async def extract_structured(self, html: str, schema: Dict, goal: str = "") -> Dict:
        """Extract structured data from HTML using schema."""
        prompt = f"""
Extract structured data from the following HTML content based on the provided schema.

Goal: {goal}

Schema:
{json.dumps(schema, indent=2)}

HTML Content:
{html[:15000]}

Return ONLY valid JSON matching the schema.
"""
        result = await self.generate(prompt)
        try:
            return json.loads(result)
        except json.JSONDecodeError:
            # Try to extract JSON from response
            import re
            match = re.search(r'\{.*\}', result, re.DOTALL)
            if match:
                return json.loads(match.group())
            return {"error": "Failed to parse JSON", "raw": result}

    async def scrape(self, request) -> Dict:
        """Scrape using the engine (not applicable for LLM engine)."""
        raise NotImplementedError("GroqLLMEngine is for LLM tasks, not direct scraping")


async def create_groq_llm_engine(config: EngineConfig) -> GroqLLMEngine:
    """Factory function to create GroqLLMEngine instance."""
    engine = GroqLLMEngine()
    await engine.initialize(config)
    return engine


async def demo():
    """Demo the Groq + Crawlee integration"""
    GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
    
    crawler = CrawleeLLMCrawler(GROQ_API_KEY, model="groq/compound")
    await crawler.initialize({"use_browser": True, "headless": True})
    
    # Example 1: Scrape with structured extraction
    print("=== Scrape with Structured Extraction ===")
    schema = {
        "type": "object",
        "properties": {
            "institute_name": {"type": "string"},
            "location": {"type": "string"},
            "courses": {"type": "array", "items": {"type": "string"}},
            "contact": {"type": "object", "properties": {"email": {"type": "string"}, "phone": {"type": "string"}}}
        }
    }
    
    result = await crawler.scrape("https://example.com", schema=schema)
    print(json.dumps(result, indent=2))
    
    await crawler.shutdown()


if __name__ == "__main__":
    asyncio.run(demo())