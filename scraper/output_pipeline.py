from __future__ import annotations

import csv
import gzip
import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from .config.schemas import (
    UniversalConfig,
    UniversalRequest,
    UniversalResult,
    OutputFormat,
)
from .utils.observability import get_logger
from .enrichment import EnrichmentPipeline, EnrichmentConfig
from .engines.ml_extraction import HybridExtractor, ExtractionSchema, extract_with_schema
from groq import Groq


logger = get_logger("output_pipeline")

@dataclass
class OutputPipeline:
    """Process results through: Raw → Cleaned → Validated → Enriched → Format"""

    config: UniversalConfig

    def __post_init__(self):
        self.logger = get_logger("output_pipeline")
        self.output_dir = Path(self.config.output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Initialize enrichment pipeline
        enrichment_cfg = EnrichmentConfig(
            steps=self.config.data_validation.enrichment_steps if self.config.data_validation else [],
        )
        self.enrichment = EnrichmentPipeline(enrichment_cfg)

    async def process(
        self,
        result: "UniversalResult",
        request: "UniversalRequest",
        metadata: Optional[Dict] = None,
    ) -> "UniversalResult":
        """Process result through full pipeline: Extract → Enrich → Format."""
        logger.debug(f"Process called: success={result.success}, has_data={result.data is not None}, has_schema={request.extract_schema is not None}")
        # 1. Structured Extraction (if schema provided)
        if result.success and result.data and request.extract_schema:
            logger.info("Starting structured extraction")
            result.data = await self._extract_structured_data_async(result.data, request)
            logger.info(f"Extraction completed, data type: {type(result.data)}")

        # 2. Enrichment
        if result.data and self.config.data_validation.enrichment_steps:
            result.data = self._enrich_data(result.data)

        # 3. Write outputs
        output_files = {}
        formats = request.output_formats or [OutputFormat.JSONL]
        if OutputFormat.ALL in formats:
            formats = [f for f in OutputFormat if f != OutputFormat.ALL]
        for fmt in formats:
            filepath = self._write_output(result, request, fmt)
            output_files[fmt.value] = filepath

        result.formatted_outputs = output_files
        return result

    async def _extract_structured_data_async(self, data: Any, request: "UniversalRequest") -> Any:
        """Extract structured data from HTML using LLM and schema."""
        schema = request.extract_schema
        if not schema:
            return data

        # Get HTML content from data
        html_content = self._extract_html_content(data)
        if not html_content:
            logger.warning("No HTML content available for structured extraction")
            return data

        # Initialize Groq client for extraction
        groq_api_key = getattr(self.config.extraction.primary_llm, 'api_key', '') or os.getenv("GROQ_API_KEY", "")
        if not groq_api_key:
            logger.warning("No Groq API key available for structured extraction")
            return data

        try:
            groq_client = Groq(api_key=groq_api_key)
            
            # Convert JSON schema to ExtractionSchema
            extraction_schema = self._json_schema_to_extraction_schema(schema)
            
            # Initialize hybrid extractor
            extractor = HybridExtractor(llm_client=Groq(api_key=groq_api_key))
            
            # Get URL for context
            url = request.url or "unknown"
            
            # Perform extraction
            extraction_result = await extractor.extract(
                html=html_content,
                url=url,
                schema=extraction_schema,
                context={"goal": request.goal} if request.goal else None,
            )
            
            if extraction_result.success:
                logger.info(f"Structured extraction successful: {len(extraction_result.data)} items extracted")
                # Return extracted structured data
                return extraction_result.data
            else:
                logger.warning(f"Structured extraction failed: {extraction_result.errors}")
                return data
                
        except Exception as e:
            logger.error(f"Structured extraction failed: {e}")
            return data

    def _extract_html_content(self, data: Any) -> Optional[str]:
        """Extract HTML content from result data."""
        if isinstance(data, dict):
            # Check common HTML fields
            for key in ['html', 'markdown', 'text', 'content']:
                if key in data and data[key]:
                    return str(data[key])
            # If data is the result itself with html field
            return str(data.get('html', '')) if 'html' in data else None
        elif isinstance(data, list):
            # For list data, try to find HTML in first item
            for item in data:
                if isinstance(item, dict):
                    html = self._extract_html_content(item)
                    if html:
                        return html
        return None

    def _json_schema_to_extraction_schema(self, schema: Dict) -> "ExtractionSchema":
        """Convert JSON Schema to ExtractionSchema."""
        from .engines.ml_extraction import ExtractionSchema, ExtractionField
        
        fields = []
        
        # Handle array type schema (items contains the object schema)
        if schema.get("type") == "array" and "items" in schema:
            item_schema = schema["items"]
            properties = item_schema.get("properties", {})
            required = item_schema.get("required", [])
        else:
            properties = schema.get("properties", {})
            required = schema.get("required", [])
        
        for field_name, field_spec in properties.items():
            field_type = field_spec.get("type", "string")
            field = ExtractionField(
                name=field_name,
                type=field_type,
                description=field_spec.get("description", ""),
                required=field_name in required,
                enum=field_spec.get("enum"),
            )
            fields.append(field)
        
        return ExtractionSchema(
            name="user_schema",
            description="User-provided extraction schema",
            fields=fields,
        )

    def _enrich_data(self, data: Any) -> Any:
        """Apply enrichment steps."""
        items = data if isinstance(data, list) else [data]
        enriched = []
        for item in items:
            enriched_item = self.enrichment.enrich(item)
            enriched.append(enriched_item)
        return enriched if len(enriched) > 1 else enriched[0]

    def _write_output(
        self,
        result: "UniversalResult",
        request: "UniversalRequest",
        fmt: "OutputFormat",
    ) -> str:
        """Write result to file in specified format."""

        stem = self._generate_stem(request.url)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{stem}_{timestamp}.{fmt.value}"

        if fmt == OutputFormat.JSON:
            return self._write_json(result, filename)
        elif fmt == OutputFormat.JSONL:
            return self._write_jsonl(result, filename)
        elif fmt == OutputFormat.CSV:
            return self._write_csv(result, filename)
        elif fmt == OutputFormat.PARQUET:
            return self._write_parquet(result, filename)
        elif fmt == OutputFormat.DB:
            return self._write_db(result, filename)
        elif fmt == OutputFormat.EXCEL:
            return self._write_excel(result, filename)
        else:
            raise ValueError(f"Unsupported format: {fmt}")

    def _generate_stem(self, url: Optional[str]) -> str:
        if not url:
            return "research"
        parsed = urlparse(url)
        # Ensure netloc is a string (urlparse returns bytes for None input)
        netloc = parsed.netloc
        if isinstance(netloc, bytes):
            netloc = netloc.decode('utf-8', errors='ignore')
        stem = netloc.replace(".", "_")
        if parsed.path:
            stem += "_" + re.sub(r"[^a-zA-Z0-9]+", "_", parsed.path).strip("_")[:50]
        return stem[:100]

    def _write_json(self, result: "UniversalResult", filename: str) -> str:
        filepath = self.output_dir / filename
        data = {
            "success": result.success,
            "url": result.url,
            "engine_used": result.engine_used,
            "quality_score": result.quality_score,
            "completeness": result.completeness,
            "accuracy": result.accuracy,
            "latency_ms": result.latency_ms,
            "error": result.error,
            "data": result.data,
            "metadata": result.metadata,
            "scraped_at": datetime.utcnow().isoformat(),
        }
        filepath.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(filepath)

    def _write_jsonl(self, result: "UniversalResult", filename: str) -> str:
        filepath = self.output_dir / filename
        items = result.data if isinstance(result.data, list) else [result.data]
        with filepath.open("w", encoding="utf-8") as f:
            for item in items:
                record = {
                    **item,
                    "_meta": {
                        "engine": result.engine_used,
                        "quality": result.quality_score,
                        "scraped_at": datetime.utcnow().isoformat(),
                    }
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return str(filepath)

    def _write_csv(self, result: "UniversalResult", filename: str) -> str:
        filepath = self.output_dir / filename
        items = result.data if isinstance(result.data, list) else [result.data]
        if not items:
            filepath.write_text("")
            return str(filepath)

        # Flatten nested objects
        flattened = [self._flatten_dict(item) for item in items]
        all_keys = set()
        for item in flattened:
            all_keys.update(item.keys())

        with filepath.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=sorted(all_keys))
            writer.writeheader()
            writer.writerows(flattened)
        return str(filepath)

    def _write_parquet(self, result: "UniversalResult", filename: str) -> str:
        try:
            import polars as pl
        except ImportError:
            raise RuntimeError("polars required for Parquet output. Install: pip install polars")

        filepath = self.output_dir / filename
        items = result.data if isinstance(result.data, list) else [result.data]
        if not items:
            pl.DataFrame().write_parquet(filepath)
            return str(filepath)

        flattened = [self._flatten_dict(item) for item in items]
        df = pl.DataFrame(flattened)
        df.write_parquet(filepath, compression="zstd")
        return str(filepath)

    def _write_db(self, result: "UniversalResult", filename: str) -> str:
        filepath = self.output_dir / filename
        items = result.data if isinstance(result.data, list) else [result.data]

        conn = sqlite3.connect(str(filepath))
        if items:
            flattened = [self._flatten_dict(item) for item in items]
            all_keys = set()
            for item in flattened:
                all_keys.update(item.keys())

            columns = ", ".join(f'"{k}" TEXT' for k in sorted(all_keys))
            conn.execute(f"CREATE TABLE IF NOT EXISTS scraped_data ({columns})")

            for item in flattened:
                values = [str(item.get(k, "")) for k in sorted(all_keys)]
                placeholders = ", ".join("?" * len(values))
                conn.execute(f"INSERT INTO scraped_data VALUES ({placeholders})", values)

        conn.commit()
        conn.close()
        return str(filepath)

    def _write_excel(self, result: "UniversalResult", filename: str) -> str:
        try:
            import openpyxl
        except ImportError:
            raise RuntimeError("openpyxl required for Excel output. Install: pip install openpyxl")

        filepath = self.output_dir / filename
        items = result.data if isinstance(result.data, list) else [result.data]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Scraped Data"

        if items:
            flattened = [self._flatten_dict(item) for item in items]
            all_keys = sorted(set().union(*[item.keys() for item in flattened]))

            ws.append(all_keys)
            for item in flattened:
                ws.append([item.get(k, "") for k in all_keys])

        wb.save(filepath)
        return str(filepath)

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = "", sep: str = "_") -> Dict[str, Any]:
        items = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            elif isinstance(v, list):
                items.append((new_key, json.dumps(v, ensure_ascii=False)))
            else:
                items.append((new_key, v))
        return dict(items)


import re