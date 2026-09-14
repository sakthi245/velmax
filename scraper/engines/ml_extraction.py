from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from uuid import uuid4

from .stealth import BrowserFingerprint

logger = logging.getLogger(__name__)


class ExtractionMethod(Enum):
    LLM = "llm"
    REGEX = "regex"
    CSS_SELECTOR = "css_selector"
    XPATH = "xpath"
    STRUCTURED_DATA = "structured_data"
    ML_INFERENCE = "ml_inference"


@dataclass
class ExtractionField:
    name: str
    type: str = "string"
    description: str = ""
    required: bool = False
    selector: Optional[str] = None
    regex: Optional[str] = None
    xpath: Optional[str] = None
    transform: Optional[str] = None
    default: Any = None
    enum: List[str] = field(default_factory=list)
    nested_schema: Optional["ExtractionSchema"] = None
    is_list: bool = False
    list_selector: Optional[str] = None
    item_schema: Optional["ExtractionSchema"] = None


@dataclass
class ExtractionSchema:
    name: str
    description: str = ""
    fields: List[ExtractionField] = field(default_factory=list)
    source_url_pattern: Optional[str] = None
    page_type: Optional[str] = None
    version: str = "1.0"
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    
    def to_json_schema(self) -> Dict[str, Any]:
        properties = {}
        required = []
        
        for field in self.fields:
            prop = {"type": field.type}
            if field.description:
                prop["description"] = field.description
            if field.enum:
                prop["enum"] = field.enum
            if field.nested_schema:
                prop["type"] = "object"
                prop["properties"] = field.nested_schema.to_json_schema()["properties"]
                if field.nested_schema.fields:
                    required_nested = [f.name for f in field.nested_schema.fields if f.required]
                    if required_nested:
                        prop["required"] = required_nested
            
            properties[field.name] = prop
            if field.required:
                required.append(field.name)
        
        schema = {
            "type": "object",
            "properties": properties,
        }
        if required:
            schema["required"] = required
        return schema


@dataclass
class ExtractionResult:
    success: bool
    data: Dict[str, Any] = field(default_factory=dict)
    schema: Optional[ExtractionSchema] = None
    method: ExtractionMethod = ExtractionMethod.LLM
    confidence: float = 0.0
    raw_html: str = ""
    extracted_elements: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    processing_time_ms: int = 0
    tokens_used: int = 0
    cost_estimate: float = 0.0


class SchemaInferenceEngine:
    """Infers extraction schemas from HTML content using ML/heuristics."""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self._common_patterns = self._load_common_patterns()
    
    def _load_common_patterns(self) -> Dict[str, Dict[str, Any]]:
        return {
            "product": {
                "indicators": ["price", "add to cart", "buy now", "sku", "product", "rating", "review"],
                "fields": ["name", "price", "original_price", "currency", "description", "images", "rating", "review_count", "availability", "brand", "model", "sku", "specifications"],
                "selectors": {
                    "name": ["h1.product-title", ".product-name", "[data-testid='product-title']", ".title"],
                    "price": [".price", ".product-price", "[data-price]", ".amount"],
                    "images": [".product-image img", ".gallery img", "[data-src]", ".thumbnails img"],
                    "rating": [".rating", ".stars", "[data-rating]", ".review-score"],
                }
            },
            "article": {
                "indicators": ["article", "blog", "post", "published", "author", "read time"],
                "fields": ["title", "author", "published_at", "updated_at", "content", "excerpt", "tags", "category", "word_count", "reading_time"],
                "selectors": {
                    "title": ["h1", ".post-title", ".article-title", ".entry-title"],
                    "author": [".author", ".byline", "[rel='author']", ".writer"],
                    "published_at": [".date", ".published", "[datetime]", "time"],
                    "content": [".content", ".post-body", ".article-body", ".entry-content"],
                }
            },
            "review": {
                "indicators": ["review", "rating", "stars", "verified purchase", "pros", "cons"],
                "fields": ["product_name", "rating", "title", "content", "author", "verified_purchase", "pros", "cons", "helpful_votes", "posted_at"],
                "selectors": {
                    "rating": [".rating", ".stars", "[data-rating]"],
                    "content": [".review-text", ".review-body", ".content"],
                    "pros": [".pros", ".advantages"],
                    "cons": [".cons", ".disadvantages"],
                }
            },
            "listing": {
                "indicators": ["listing", "for sale", "rent", "price", "location", "bedrooms", "bathrooms"],
                "fields": ["title", "price", "currency", "location", "description", "features", "contact", "posted_date", "condition"],
                "selectors": {
                    "price": [".price", ".amount", "[data-price]"],
                    "location": [".location", ".address", ".neighborhood"],
                    "features": [".features", ".amenities", ".specs"],
                }
            },
            "job": {
                "indicators": ["job", "career", "position", "salary", "apply", "requirements"],
                "fields": ["title", "company", "location", "salary", "description", "requirements", "benefits", "posted_date", "employment_type"],
                "selectors": {
                    "title": [".job-title", "h1", ".position-title"],
                    "company": [".company", ".employer", ".organization"],
                    "salary": [".salary", ".compensation", ".pay"],
                }
            },
            "event": {
                "indicators": ["event", "conference", "meetup", "webinar", "date", "venue", "ticket"],
                "fields": ["title", "date", "time", "venue", "location", "description", "speakers", "price", "registration_url"],
                "selectors": {
                    "date": [".date", ".event-date", "[datetime]"],
                    "venue": [".venue", ".location", ".place"],
                }
            },
        }
    
    def infer_schema_from_html(self, html: str, url: str = "") -> ExtractionSchema:
        """Infer extraction schema from HTML content."""
        page_type = self._detect_page_type(html, url)
        pattern = self._common_patterns.get(page_type, {})
        
        fields = []
        for field_name in pattern.get("fields", []):
            field = ExtractionField(
                name=field_name,
                type=self._infer_field_type(field_name),
                description=f"Extracted {field_name} from {page_type}",
                selector=pattern.get("selectors", {}).get(field_name, [None])[0],
            )
            fields.append(field)
        
        return ExtractionSchema(
            name=f"{page_type}_schema",
            description=f"Auto-inferred schema for {page_type} pages",
            fields=fields,
            source_url_pattern=url,
            page_type=page_type,
        )
    
    def _detect_page_type(self, html: str, url: str) -> str:
        html_lower = html.lower()
        url_lower = url.lower()
        
        scores = {}
        for page_type, pattern in self._common_patterns.items():
            score = 0
            for indicator in pattern.get("indicators", []):
                score += html_lower.count(indicator.lower()) * 2
                score += url_lower.count(indicator.lower()) * 3
            scores[page_type] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "generic"
    
    def _infer_field_type(self, field_name: str) -> str:
        type_map = {
            "price": "number",
            "rating": "number",
            "review_count": "integer",
            "word_count": "integer",
            "reading_time": "integer",
            "helpful_votes": "integer",
            "total_votes": "integer",
            "stock_quantity": "integer",
            "year": "integer",
            "published_at": "string",
            "updated_at": "string",
            "posted_at": "string",
            "date": "string",
            "time": "string",
            "datetime": "string",
            "email": "string",
            "phone": "string",
            "url": "string",
            "website": "string",
            "image": "string",
            "images": "array",
            "photos": "array",
            "tags": "array",
            "keywords": "array",
            "tags": "array",
            "categories": "array",
            "features": "array",
            "pros": "array",
            "cons": "array",
            "specifications": "object",
            "dimensions": "object",
            "metadata": "object",
        }
        return type_map.get(field_name.lower(), "string")
    
    async def refine_schema_with_llm(
        self, 
        schema: ExtractionSchema, 
        html: str, 
        url: str
    ) -> ExtractionSchema:
        """Use LLM to refine inferred schema."""
        if not self.llm_client:
            return schema
        
        prompt = f"""
        Analyze this HTML page and refine the extraction schema.
        URL: {url}
        
        Current schema:
        {json.dumps([f.to_dict() for f in schema.fields], indent=2)}
        
        HTML snippet (first 5000 chars):
        {html[:5000]}
        
        Improve the schema by:
        1. Adding missing important fields
        2. Correcting field types
        2. Adding appropriate selectors (CSS/XPath)
        4. Setting required/optional appropriately
        5. Adding descriptions
        
        Return the improved schema as JSON.
        """
        
        try:
            response = await self.llm_client.chat.completions.create(
                model="llama-3.1-70b-versatile",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.1,
                max_tokens=4000,
            )
            
            improved = json.loads(response.choices[0].message.content)
            # Merge with existing schema
            # ... implementation details
            return schema
        except Exception:
            return schema


class LLMExtractor:
    """LLM-based content extraction with structured output."""
    
    def __init__(
        self, 
        llm_client,
        model: str = "openai/gpt-oss-20b",
        temperature: float = 0.1,
        max_tokens: int = 4000,
    ):
        self.llm_client = llm_client
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
    
    def _build_extraction_prompt(
        self, 
        html: str, 
        schema: ExtractionSchema, 
        url: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> str:
        schema_json = schema.to_json_schema()
        schema_type = schema_json.get('type', 'object')
        schema_json = schema.to_json_schema()
        schema_type = schema_json.get('type', 'object')
        
        prompt_parts = [
            "Extract structured data from the following HTML page.",
            "",
            f"URL: {url}",
            f"Page Type: {schema.page_type or 'unknown'}",
            "",
            f"Extraction Schema:\n{json.dumps(schema_json, indent=2)}",
            "",
            f"Field Descriptions:\n{self._format_field_descriptions(schema)}",
            "",
            f"HTML Content (truncated to 15000 chars):\n{html[:15000]}",
            "",
            "Instructions:",
            "1. Extract data matching the schema exactly",
            "2. Use null for missing optional fields",
            "3. For arrays, return empty array if no items found",
            "4. For nested objects, extract all defined fields",
            "5. If a field cannot be found, use null",
            "6. Return valid JSON matching the schema exactly",
            "7. Do not include any explanatory text",
            f"8. IMPORTANT: The schema type is '{schema_type}'. "
            "If it's an array, you MUST return a JSON array (e.g., [{...}, {...}]). "
            "If it's an object, return a single object."
        ]
        
        prompt = "\n".join(prompt_parts)
        
        if context:
            prompt += f"\nAdditional Context: {json.dumps(context)}"
        
        logger.info(f"Prompt sent to model (first 500 chars): {prompt[:500]}")
        
        return prompt
    
    def _format_field_descriptions(self, schema: ExtractionSchema) -> str:
        lines = []
        for field in schema.fields:
            req = "REQUIRED" if field.required else "optional"
            lines.append(f"- {field.name} ({field.type}, {req}): {field.description or 'No description'}")
            if field.selector:
                lines.append(f"  Suggested selector: {field.selector}")
            if field.enum:
                lines.append(f"  Allowed values: {field.enum}")
        return "\n".join(lines)
    
    async def extract(
        self, 
        html: str, 
        schema: ExtractionSchema,
        url: str = "",
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """Extract structured data using LLM."""
        start_time = time.time()
        
        prompt = self._build_extraction_prompt(html, schema, url, context)
        
        try:
            # Groq client is synchronous, run in executor
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.llm_client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=self.temperature,
                    max_tokens=self.max_tokens,
                    response_format={"type": "json_object"},
                )
            )
            
            content = response.choices[0].message.content
            logger.info(f"Raw model response: {content[:500]}")
            data = json.loads(content)
            logger.info(f"Parsed data: {data}, type: {type(data)}")
            
            # Validate against schema
            validated = self._validate_against_schema(data, schema)
            logger.info(f"Validated data: {validated}, type: {type(validated)}")
            
            processing_time = int((time.time() - start_time) * 1000)
            
            return ExtractionResult(
                success=True,
                data=validated,
                schema=schema,
                method=ExtractionMethod.LLM,
                confidence=0.9,
                raw_html=html,
                processing_time_ms=processing_time,
                tokens_used=response.usage.total_tokens if hasattr(response, 'usage') else 0,
                cost_estimate=self._estimate_cost(response.usage.total_tokens if hasattr(response, 'usage') else 0),
            )
            
        except Exception as e:
            error_msg = str(e)
            # Try to get more details from the exception
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    error_msg = f"{error_msg}: {error_detail}"
                except:
                    pass
            logger.error(f"Groq API error: {error_msg}")
            return ExtractionResult(
                success=False,
                data={},
                schema=schema,
                method=ExtractionMethod.LLM,
                confidence=0.0,
                errors=[error_msg],
                processing_time_ms=int((time.time() - start_time) * 1000),
            )
        
        schema_type = schema_json.get('type', 'object')
        prompt_parts = [
            "Extract structured data from the following HTML page.",
            "",
            f"URL: {url}",
            f"Page Type: {schema.page_type or 'unknown'}",
            "",
            f"Extraction Schema:\n{json.dumps(schema_json, indent=2)}",
            "",
            f"Field Descriptions:\n{self._format_field_descriptions(schema)}",
            "",
            f"HTML Content (truncated to 15000 chars):\n{html[:15000]}",
            "",
            "Instructions:",
            "1. Extract data matching the schema exactly",
            "2. Use null for missing optional fields",
            "3. For arrays, return empty array if no items found",
            "4. For nested objects, extract all defined fields",
            "5. If a field cannot be found, use null",
            "6. Return valid JSON matching the schema exactly",
            "7. Do not include any explanatory text",
            f"8. IMPORTANT: The schema type is '{schema_type}'. "
            "If it's an array, you MUST return a JSON array (e.g., [{...}, {...}]). "
            "If it's an object, return a single object."
        ]
        
        prompt = "\n".join(prompt_parts)
        
        if context:
            prompt += f"\nAdditional Context: {json.dumps(context)}"
        
        logger.info(f"Prompt sent to model (first 500 chars): {prompt[:500]}")
        
        return prompt
    
    def _format_field_descriptions(self, schema: ExtractionSchema) -> str:
        lines = []
        for field in schema.fields:
            req = "REQUIRED" if field.required else "optional"
            lines.append(f"- {field.name} ({field.type}, {req}): {field.description or 'No description'}")
            if field.selector:
                lines.append(f"  Suggested selector: {field.selector}")
            if field.enum:
                lines.append(f"  Allowed values: {field.enum}")
        return "\n".join(lines)
    
    def _validate_against_schema(
        self, 
        data: Any, 
        schema: ExtractionSchema
    ) -> Any:
        """Validate and coerce extracted data against schema."""
        schema_dict = schema.to_json_schema()
        
        # If schema type is array, validate each item
        if schema_dict.get("type") == "array":
            # Handle case where model returns a single object instead of array
            items = data if isinstance(data, list) else [data] if isinstance(data, dict) else []
            
            validated_items = []
            for item in items:
                if isinstance(item, dict):
                    validated_item = {}
                    # Validate each field in the item
                    for field in schema.fields:
                        value = item.get(field.name)
                        
                        if value is None:
                            if field.required:
                                validated_item[field.name] = field.default
                            else:
                                validated_item[field.name] = None
                            continue
                        
                        # Type coercion
                        coerced = self._coerce_value(value, field.type)
                        
                        # Enum validation
                        if field.enum and coerced not in field.enum:
                            coerced = field.default
                        
                        validated_item[field.name] = coerced
                    
                    validated_items.append(validated_item)
            
            return validated_items
        
        # Original logic for object type
        result = {}
        schema_dict = schema.to_json_schema()
        
        for field in schema.fields:
            value = data.get(field.name)
            
            if value is None:
                if field.required:
                    result[field.name] = field.default
                else:
                    result[field.name] = None
                continue
            
            # Type coercion
            coerced = self._coerce_value(value, field.type)
            
            # Enum validation
            if field.enum and coerced not in field.enum:
                coerced = field.default
            
            result[field.name] = coerced
        
        return result
    
    def _coerce_value(self, value: Any, target_type: str) -> Any:
        if target_type == "string":
            return str(value)
        elif target_type == "number":
            if isinstance(value, str):
                try:
                    return float(value.replace(",", "").replace("$", "").replace("€", "").replace("£", ""))
                except:
                    return 0.0
            return float(value) if value is not None else 0.0
        elif target_type == "integer":
            try:
                return int(float(str(value).replace(",", "")))
            except:
                return 0
        elif target_type == "boolean":
            if isinstance(value, str):
                return value.lower() in ("true", "yes", "1", "on")
            return bool(value)
        elif target_type == "array":
            if isinstance(value, list):
                return value
            elif value is None:
                return []
            return [value]
        elif target_type == "object":
            if isinstance(value, dict):
                return value
            return {}
        return value
    
    def _estimate_cost(self, tokens: int) -> float:
        # Rough estimate for llama-3.1-70b
        return tokens * 0.0000001


class StructuredDataExtractor:
    """Extract structured data from HTML (JSON-LD, Microdata, RDFa)."""
    
    def __init__(self):
        self.logger = logging.getLogger("structured_data")
    
    async def extract(self, html: str, url: str = "") -> Dict[str, Any]:
        """Extract all structured data from HTML."""
        results = {
            "json_ld": [],
            "microdata": [],
            "rdfa": [],
            "opengraph": {},
            "twitter_card": {},
        }
        
        # Extract JSON-LD
        results["json_ld"] = self._extract_json_ld(html)
        
        # Extract Open Graph
        results["opengraph"] = self._extract_opengraph(html)
        
        # Extract Twitter Card
        results["twitter_card"] = self._extract_twitter_card(html)
        
        # Extract Microdata
        results["microdata"] = self._extract_microdata(html)
        
        return results
    
    def _extract_json_ld(self, html: str) -> List[Dict[str, Any]]:
        results = []
        pattern = r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>'
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        
        for match in matches:
            try:
                data = json.loads(match.strip())
                if isinstance(data, list):
                    results.extend(data)
                else:
                    results.append(data)
            except json.JSONDecodeError:
                # Try to extract JSON from within
                try:
                    inner = re.search(r'\{.*\}', match, re.DOTALL)
                    if inner:
                        data = json.loads(inner.group())
                        if isinstance(data, list):
                            results.extend(data)
                        else:
                            results.append(data)
                except:
                    pass
        return results
    
    def _extract_opengraph(self, html: str) -> Dict[str, str]:
        results = {}
        pattern = r'<meta\s+property=["\']og:([^"\']+)["\']\s+content=["\']([^"\']*)["\']'
        matches = re.findall(pattern, html, re.IGNORECASE)
        for prop, value in matches:
            results[prop] = value
        return results
    
    def _extract_twitter_card(self, html: str) -> Dict[str, str]:
        results = {}
        pattern = r'<meta\s+name=["\']twitter:([^"\']+)["\']\s+content=["\']([^"\']*)["\']'
        matches = re.findall(pattern, html, re.IGNORECASE)
        for prop, value in matches:
            results[prop] = value
        return results
    
    def _extract_microdata(self, html: str) -> List[Dict[str, Any]]:
        # Simplified microdata extraction
        results = []
        # Full implementation would parse itemscope/itemprop
        return results


class HybridExtractor:
    """Combines multiple extraction methods for best results."""
    
    def __init__(
        self, 
        llm_client=None,
        model: str = "openai/gpt-oss-20b",
        schema_inference: Optional[SchemaInferenceEngine] = None,
        structured_extractor: Optional[StructuredDataExtractor] = None,
    ):
        self.llm_extractor = LLMExtractor(llm_client, model=model) if llm_client else None
        self.schema_inference = schema_inference or SchemaInferenceEngine()
        self.structured_extractor = structured_extractor or StructuredDataExtractor()
    
    async def extract(
        self,
        html: str,
        url: str = "",
        schema: Optional[ExtractionSchema] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ExtractionResult:
        """Extract using best available method."""
        # Try structured data first (fast, reliable)
        structured = await self.structured_extractor.extract(html, url)
        
        # Infer schema if not provided
        if schema is None:
            schema = self.schema_inference.infer_schema_from_html(html, url)
        
        # Try LLM extraction if available
        if self.llm_extractor:
            llm_result = await self.llm_extractor.extract(html, schema, url, context)
            if llm_result.success:
                return llm_result
        
        # Fallback: merge structured data with schema
        return self._merge_structured_data(structured, schema)
    
    def _merge_structured_data(
        self, 
        structured: Dict[str, Any], 
        schema: ExtractionSchema
    ) -> ExtractionResult:
        """Merge structured data into schema."""
        data = {}
        
        # Map JSON-LD to schema fields
        json_ld = structured.get("json_ld", [])
        for item in json_ld:
            self._map_json_ld_to_schema(item, schema, data)
        
        # Map OpenGraph
        og = structured.get("opengraph", {})
        self._map_opengraph_to_schema(og, schema, data)
        
        return ExtractionResult(
            success=True,
            data=data,
            schema=schema,
            method=ExtractionMethod.STRUCTURED_DATA,
            confidence=0.7,
            raw_html="",
        )
    
    def _map_json_ld_to_schema(
        self, 
        json_ld: Dict[str, Any], 
        schema: ExtractionSchema, 
        data: Dict[str, Any]
    ):
        type_mapping = {
            "Product": ["name", "price", "description", "image", "brand", "sku", "rating", "review"],
            "Article": ["title", "author", "datePublished", "dateModified", "articleBody", "keywords"],
            "Review": ["itemReviewed", "reviewRating", "author", "reviewBody", "pros", "cons"],
            "Event": ["name", "startDate", "endDate", "location", "description"],
            "JobPosting": ["title", "hiringOrganization", "baseSalary", "description", "datePosted"],
        }
        
        item_type = json_ld.get("@type", "")
        if isinstance(item_type, list):
            item_type = item_type[0]
        
        fields = type_mapping.get(item_type, [])
        for field in fields:
            if field in json_ld and field not in data:
                data[field] = json_ld[field]
    
    def _map_opengraph_to_schema(self, og: Dict[str, str], schema: ExtractionSchema, data: Dict[str, Any]):
        og_mapping = {
            "title": "name",
            "description": "description",
            "image": "image",
            "url": "url",
            "type": "category",
            "site_name": "source",
        }
        
        for og_key, schema_key in og_mapping.items():
            if og_key in og and schema_key not in data:
                data[schema_key] = og[og_key]


async def extract_with_schema(
    html: str,
    url: str,
    schema: Optional[ExtractionSchema] = None,
    llm_client=None,
    context: Optional[Dict[str, Any]] = None,
) -> ExtractionResult:
    """Convenience function for extraction."""
    extractor = HybridExtractor(llm_client=llm_client)
    return await extractor.extract(html, url, schema, context)


async def infer_and_extract(
    html: str,
    url: str,
    llm_client=None,
    context: Optional[Dict[str, Any]] = None,
) -> ExtractionResult:
    """Infer schema and extract in one call."""
    inference = SchemaInferenceEngine()
    schema = inference.infer_schema_from_html(html, url)
    return await extract_with_schema(html, url, schema, llm_client, context)