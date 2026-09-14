from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Optional

@dataclass
class ScrapeResult:
    items: list[dict[str, Any]]
    engine: str
    attempts: list[dict[str, Any]] = field(default_factory=list)
    limits_hit: list[str] = field(default_factory=list)

@dataclass
class CrawlResult:
    pages: list[dict[str, Any]]
    engine: str
    total_pages: int = 0
    failed_pages: int = 0

@dataclass
class ExtractResult:
    data: dict[str, Any]
    schema: dict[str, Any]
    engine: str
    confidence: Optional[float] = None