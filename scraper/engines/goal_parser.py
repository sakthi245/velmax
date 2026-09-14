from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any

from groq import Groq
from scraper.utils.llm_cache import LLMResponseCache

logger = logging.getLogger(__name__)


@dataclass
class ParsedGoal:
    """Parsed goal with extracted entities and constraints."""
    category: str = "general"
    price_min: Optional[int] = None
    price_max: Optional[int] = None
    brand: Optional[str] = None
    intent: str = "product_search"
    keywords: List[str] = field(default_factory=list)
    technical_specs: List[str] = field(default_factory=list)
    location: Optional[str] = None
    raw_goal: str = ""
    confidence: float = 0.0

    def to_search_queries(self) -> List[str]:
        """Generate optimized search queries for search engines."""
        queries = []
        
        # Base query with category
        base = self.category
        if self.brand:
            base += f" {self.brand}"
        
        # Add technical specs to base
        if self.technical_specs:
            base += f" {' '.join(self.technical_specs)}"
        
        # Add price range
        if self.price_min is not None or self.price_max is not None:
            price_parts = []
            if self.price_min is not None:
                price_parts.append(f"above Rs.{self.price_min}")
            if self.price_max is not None:
                price_parts.append(f"under Rs.{self.price_max}")
            if self.price_min is not None and self.price_max is not None:
                price_parts = [f"Rs.{self.price_min}-{self.price_max}"]
            base += f" {' '.join(price_parts)}"
        
        # Add location
        if self.location:
            base += f" in {self.location}"
        
        # Generate query variations
        queries.append(base)
        queries.append(f"{base} buy online")
        queries.append(f"{base} best price")
        queries.append(f"{base} deals")
        
        # Add keyword-based queries
        for keyword in self.keywords[:3]:
            queries.append(f"{keyword} {base}")
        
        return list(dict.fromkeys(queries))  # Deduplicate preserving order


class GroqEntityExtractor:
    """Universal entity extraction using Groq LLM for ANY category."""
    
    EXTRACTION_PROMPT = """Extract ALL technical specifications, product attributes, and constraints from this goal.

Goal: {goal}

Return JSON with:
- category: detected product category (phones, laptops, commodities, books, services, industrial, chemicals, etc.)
- technical_specs: list of ALL technical tokens (model numbers, generations, capacities, versions, part numbers, chemical formulas, grades, standards, certifications, dimensions, etc.)
- brand: detected brand if any
- price_min, price_max: numeric if mentioned
- attributes: dict of other specs (color, size, material, grade, certification, region, etc.)
- intent: product_search, comparison, review, price_check, research, sourcing, etc.
- confidence: 0.0-1.0

Examples:
"i5 13th gen laptop" → technical_specs: ["i5", "13th gen", "laptop"], category: "laptops"
"RTX 4090 graphics card" → technical_specs: ["RTX 4090", "graphics card"], category: "components"
"99.9% pure silver bullion 1oz" → technical_specs: ["99.9%", "pure silver", "1oz", "bullion"], category: "commodities"
"ISO 9001 certified steel grade 304" → technical_specs: ["ISO 9001", "steel grade 304"], category: "industrial"
"iPhone 15 Pro Max 256GB" → technical_specs: ["iPhone 15 Pro Max", "256GB"], category: "phones"
"wireless headphones noise cancelling 30h battery" → technical_specs: ["wireless", "noise cancelling", "30h battery"], category: "audio"

Return ONLY valid JSON."""

    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        cache: Optional[LLMResponseCache] = None,
        openrouter_api_key: Optional[str] = None,
    ):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")
        self.cache = cache
        self.openrouter_api_key = openrouter_api_key or os.getenv("OPENROUTER_API_KEY", "")
        
        # Groq model fallback chain
        self.groq_models = [
            "groq/compound",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]
        
        self._groq_client = None
        self._openrouter_session = None
        self._initialized = False

    async def _ensure_initialized(self):
        """Lazy initialization of clients."""
        if self._initialized:
            return
        
        if self.groq_api_key:
            self._groq_client = Groq(api_key=self.groq_api_key)
        
        if self.openrouter_api_key:
            import aiohttp
            self._openrouter_session = aiohttp.ClientSession(
                headers={
                    "Authorization": f"Bearer {self.openrouter_api_key}",
                    "Content-Type": "application/json",
                }
            )
        
        self._initialized = True

    async def _call_groq(self, prompt: str, model: str) -> Optional[Dict]:
        """Call Groq API with given model."""
        if not self._groq_client:
            return None
        
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self._groq_client.chat.completions.create(
                    model=model,
                    messages=[
                        {"role": "system", "content": "You are an expert entity extractor. Return ONLY valid JSON."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.1,
                    max_tokens=1000,
                    response_format={"type": "json_object"},
                )
            )
            content = response.choices[0].message.content
            if content:
                return json.loads(content)
        except Exception as e:
            logger.debug(f"Groq model {model} failed: {e}")
            raise
        return None

    async def _call_openrouter(self, prompt: str) -> Optional[Dict]:
        """Call OpenRouter API with auto model selection."""
        if not self.openrouter_api_key or not self._openrouter_session:
            return None
        
        try:
            import aiohttp
            payload = {
                "model": "auto",
                "messages": [
                    {"role": "system", "content": "You are an expert entity extractor. Return ONLY valid JSON."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 2000,
                "response_format": {"type": "json_object"},
            }
            
            async with self._openrouter_session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    if content:
                        return json.loads(content)
        except Exception as e:
            logger.debug(f"OpenRouter call failed: {e}")
            raise
        return None

    def _parse_groq_response(self, goal: str, result: Dict) -> 'ParsedGoal':
        """Parse Groq response into ParsedGoal."""
        parsed = ParsedGoal(raw_goal=goal)
        
        parsed.category = result.get("category", "general")
        parsed.technical_specs = result.get("technical_specs", [])
        parsed.brand = result.get("brand")
        parsed.price_min = result.get("price_min")
        parsed.price_max = result.get("price_max")
        parsed.intent = result.get("intent", "product_search")
        parsed.confidence = result.get("confidence", 0.7)
        
        # Extract attributes as keywords
        attrs = result.get("attributes", {})
        if attrs:
            parsed.keywords = list(attrs.keys())
        
        return parsed

    async def extract(self, goal: str) -> ParsedGoal:
        """Extract entities from goal using Groq with fallback chain."""
        await self._ensure_initialized()
        
        prompt = self.EXTRACTION_PROMPT.format(goal=goal)
        cache_key = f"llm:goal:{hashlib.sha256(goal.encode()).hexdigest()[:16]}"
        
        # Check cache
        if self.cache:
            cached = await self.cache.get(cache_key)
            if cached:
                return ParsedGoal(**cached)
        
        # Try Groq models in order
        for model in [
            "groq/compound",
            "llama-3.1-70b-versatile",
            "llama-3.1-8b-instant",
            "mixtral-8x7b-32768",
            "gemma2-9b-it",
        ]:
            try:
                result = await self._call_groq(self.EXTRACTION_PROMPT.format(goal=goal), model)
                if result:
                    parsed = self._parse_groq_response(goal, result)
                    # Cache result
                    if self.cache:
                        await self.cache.set(f"llm:goal:{hashlib.sha256(goal.encode()).hexdigest()[:16]}", 
                                            parsed.__dict__, ttl=86400)  # 24h
                    return parsed
            except Exception as e:
                logger.debug(f"Groq model {model} failed: {e}")
                continue
        
        # Try OpenRouter as final fallback
        if self.openrouter_api_key:
            try:
                result = await self._call_openrouter(self.EXTRACTION_PROMPT.format(goal=goal))
                if result:
                    parsed = self._parse_groq_response(goal, result)
                    if self.cache:
                        await self.cache.set(f"llm:goal:{hashlib.sha256(goal.encode()).hexdigest()[:16]}", 
                                            parsed.__dict__, ttl=86400)
                    return parsed
            except Exception as e:
                logger.debug(f"OpenRouter extraction failed: {e}")
        
        # Final fallback: regex method
        return self._regex_fallback(goal)

    def _regex_fallback(self, goal: str) -> ParsedGoal:
        """Fallback to regex-based parsing."""
        parser = GoalParser()
        return parser.parse(goal)


class GoalParser:
    """Parses natural language goals into structured entities."""
    
    # Category keywords for classification
    CATEGORY_KEYWORDS = {
        "phones": ["phone", "mobile", "smartphone", "iphone", "android", "cell phone"],
        "laptops": ["laptop", "notebook", "macbook", "ultrabook", "gaming laptop"],
        "tablets": ["tablet", "ipad", "android tablet"],
        "headphones": ["headphone", "headset", "earphone", "earbud", "airpod"],
        "watches": ["watch", "smartwatch", "fitbit", "apple watch"],
        "tv": ["tv", "television", "smart tv", "oled", "qled", "4k tv"],
        "cameras": ["camera", "dslr", "mirrorless", "action camera", "gopro"],
        "gaming": ["gaming", "console", "ps5", "xbox", "nintendo switch", "gaming pc"],
        "audio": ["speaker", "soundbar", "home theater", "audio system"],
        "appliances": ["refrigerator", "washing machine", "microwave", "ac", "air conditioner"],
        "fashion": ["shirt", "jeans", "dress", "shoes", "sneakers", "bag", "watch"],
        "books": ["book", "novel", "textbook", "ebook", "kindle"],
        "toys": ["toy", "lego", "action figure", "board game", "puzzle"],
    }
    
    # Brand keywords
    BRAND_KEYWORDS = {
        "apple": ["iphone", "macbook", "ipad", "airpod", "apple watch", "apple"],
        "samsung": ["samsung", "galaxy"],
        "google": ["pixel", "google"],
        "oneplus": ["oneplus"],
        "xiaomi": ["xiaomi", "mi ", "redmi", "poco"],
        "realme": ["realme"],
        "vivo": ["vivo"],
        "oppo": ["oppo"],
        "motorola": ["motorola", "moto"],
        "sony": ["sony"],
        "lg": ["lg "],
        "dell": ["dell"],
        "hp": ["hp "],
        "lenovo": ["lenovo", "thinkpad", "ideapad"],
        "asus": ["asus", "rog "],
        "acer": ["acer"],
        "msi": ["msi "],
        "razer": ["razer"],
        "logitech": ["logitech"],
        "bose": ["bose"],
        "jbl": ["jbl "],
        "sennheiser": ["sennheiser"],
    }
    
    # Intent patterns
    INTENT_PATTERNS = {
        "product_search": [r"find", r"search", r"look for", r"buy", r"purchase", r"get"],
        "comparison": [r"compare", r"vs", r"versus", r"better", r"best"],
        "review": [r"review", r"rating", r"feedback", r"opinion"],
        "price_check": [r"price", r"cost", r"cheap", r"deal", r"discount", r"offer"],
    }
    
    def __init__(
        self,
        groq_api_key: Optional[str] = None,
        cache: Optional[LLMResponseCache] = None,
        openrouter_api_key: Optional[str] = None,
    ):
        self._compile_patterns()
        self.groq_extractor = GroqEntityExtractor(groq_api_key, cache, openrouter_api_key)
    
    def _compile_patterns(self):
        """Compile regex patterns for extraction."""
        # Price patterns
        self.price_range_pattern = re.compile(
            r'(?:₹|rs\.?|inr)?\s*(\d[\d,]*)\s*[-–to]\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_under_pattern = re.compile(
            r'(?:under|below|less than|upto|up to)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_above_pattern = re.compile(
            r'(?:above|over|more than|starting from|from)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_exact_pattern = re.compile(
            r'(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        
        # Location patterns
        self.location_pattern = re.compile(
            r'\b(?:in|at|near|around)\s+([A-Za-z\s]+?)(?:\s|$|,|\.)',
            re.IGNORECASE
        )
    
    def _compile_patterns(self):
        """Compile regex patterns for extraction."""
        # Price patterns
        self.price_range_pattern = re.compile(
            r'(?:₹|rs\.?|inr)?\s*(\d[\d,]*)\s*[-–to]\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_under_pattern = re.compile(
            r'(?:under|below|less than|upto|up to)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_above_pattern = re.compile(
            r'(?:above|over|more than|starting from|from)\s*(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        self.price_exact_pattern = re.compile(
            r'(?:₹|rs\.?|inr)?\s*(\d[\d,]*)',
            re.IGNORECASE
        )
        
        # Location patterns
        self.location_pattern = re.compile(
            r'\b(?:in|at|near|around)\s+([A-Za-z\s]+?)(?:\s|$|,|\.)',
            re.IGNORECASE
        )
    
    async def parse(self, goal: str) -> ParsedGoal:
        """Parse a natural language goal into structured entities using Groq first, then regex fallback."""
        # Try Groq extraction first
        if self.groq_extractor:
            try:
                parsed = await self.groq_extractor.extract(goal)
                # Enhance with regex-based fields if missing
                goal_lower = goal.lower().strip()
                if not parsed.location:
                    parsed.location = self._extract_location(goal)
                if not parsed.price_min and not parsed.price_max:
                    parsed.price_min, parsed.price_max = self._extract_price_range(goal_lower)
                if not parsed.keywords:
                    parsed.keywords = self._extract_keywords(goal_lower)
                # Calculate confidence if not set
                if not parsed.confidence:
                    parsed.confidence = self._calculate_confidence(parsed, goal_lower)
                return parsed
            except Exception as e:
                logger.warning(f"Groq extraction failed, using regex fallback: {e}")
        
        # Fallback to regex method
        return self._regex_parse(goal)

    def _regex_parse(self, goal: str) -> ParsedGoal:
        """Original regex-based parsing as fallback."""
        goal_lower = goal.lower().strip()
        
        parsed = ParsedGoal(raw_goal=goal)
        
        # Extract category
        parsed.category = self._extract_category(goal_lower)
        
        # Extract brand
        parsed.brand = self._extract_brand(goal_lower)
        
        # Extract price range
        parsed.price_min, parsed.price_max = self._extract_price_range(goal_lower)
        
        # Extract location
        parsed.location = self._extract_location(goal)
        
        # Extract intent
        parsed.intent = self._extract_intent(goal_lower)
        
        # Extract keywords
        parsed.keywords = self._extract_keywords(goal_lower)
        
        # Calculate confidence
        parsed.confidence = self._calculate_confidence(parsed, goal_lower)
        
        return parsed
    
    def _extract_category(self, goal: str) -> str:
        """Extract product category from goal."""
        scores = {}
        for category, keywords in self.CATEGORY_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in goal)
            if score > 0:
                scores[category] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "general"
    
    def _extract_brand(self, goal: str) -> Optional[str]:
        """Extract brand from goal."""
        for brand, keywords in self.BRAND_KEYWORDS.items():
            for kw in keywords:
                if kw in goal:
                    return brand
        return None
    
    def _extract_price_range(self, goal: str) -> tuple:
        """Extract price range from goal."""
        price_min = None
        price_max = None
        
        # Check for range pattern (e.g., "20000-25000", "20000 to 25000")
        range_match = self.price_range_pattern.search(goal)
        if range_match:
            price_min = int(range_match.group(1).replace(',', ''))
            price_max = int(range_match.group(2).replace(',', ''))
            return price_min, price_max
        
        # Check for "under/below" pattern
        under_match = self.price_under_pattern.search(goal)
        if under_match:
            price_max = int(under_match.group(1).replace(',', ''))
            return price_min, price_max
        
        # Check for "above/over" pattern
        above_match = self.price_above_pattern.search(goal)
        if above_match:
            price_min = int(above_match.group(1).replace(',', ''))
            return price_min, price_max
        
        return price_min, price_max
    
    def _extract_location(self, goal: str) -> Optional[str]:
        """Extract location from goal."""
        match = self.location_pattern.search(goal)
        if match:
            location = match.group(1).strip()
            # Filter out common false positives
            if location.lower() not in ['india', 'online', 'store', 'shop', 'market', 'amazon', 'flipkart']:
                return location
        return None
    
    def _extract_intent(self, goal: str) -> str:
        """Extract user intent from goal."""
        for intent, patterns in self.INTENT_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, goal, re.IGNORECASE):
                    return intent
        return "product_search"
    
    def _extract_keywords(self, goal: str) -> List[str]:
        """Extract meaningful keywords from goal."""
        # Remove common stop words
        stop_words = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by', 'from', 'up', 'down', 'out', 'off', 'over', 'under', 'again', 'further', 'then', 'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all', 'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor', 'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'can', 'will', 'just', 'should', 'now'}
        
        words = re.findall(r'\b\w+\b', goal.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 2 and not w.isdigit()]
        
        return list(dict.fromkeys(keywords))[:10]  # Limit to 10 unique keywords
    
    def _calculate_confidence(self, parsed: ParsedGoal, goal: str) -> float:
        """Calculate confidence score for the parsed goal."""
        score = 0.0
        
        if parsed.category != "general":
            score += 0.3
        
        if parsed.brand:
            score += 0.2
        
        if parsed.price_min is not None or parsed.price_max is not None:
            score += 0.2
        
        if parsed.location:
            score += 0.1
        
        if parsed.keywords:
            score += min(0.2, len(parsed.keywords) * 0.02)
        
        return min(score, 1.0)


# Convenience function
async def parse_goal(goal: str) -> ParsedGoal:
    """Parse a goal string into structured entities."""
    parser = GoalParser()
    return await parser.parse(goal)


if __name__ == "__main__":
    # Test the parser
    test_goals = [
        "phones 20000-25000",
        "iphone under 50000",
        "samsung galaxy phones above 30000",
        "laptops 50000-80000 in bangalore",
        "best gaming laptop under 100000",
        "sony headphones review",
        "compare iphone 15 vs samsung s24",
    ]
    
    parser = GoalParser()
    for goal in test_goals:
        parsed = parser.parse(goal)
        print(f"\nGoal: {goal}")
        print(f"  Category: {parsed.category}")
        print(f"  Brand: {parsed.brand}")
        print(f"  Price: Rs.{parsed.price_min} - Rs.{parsed.price_max}")
        print(f"  Location: {parsed.location}")
        print(f"  Intent: {parsed.intent}")
        print(f"  Keywords: {parsed.keywords}")
        print(f"  Queries: {parsed.to_search_queries()}")
        print(f"  Confidence: {parsed.confidence:.2f}")