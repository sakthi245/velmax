from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Type, Union

from .models import (
    BaseModelMixin,
    BaseProduct,
    BaseArticle,
    BaseReview,
    BaseListing,
    ValidationResult,
    DeduplicationResult,
    NormalizedPrice,
    NormalizedDate,
    MappedCategory,
    QualityScore,
)
from .validator import DataValidator, ValidationConfig, validate_item
from .deduplicator import ContentDeduplicator, DedupConfig, create_deduplicator
from .price_normalizer import PriceNormalizer, PriceConfig, parse_price_string, extract_prices
from .date_normalizer import DateNormalizer, DateConfig, parse_date_string, extract_dates
from .category_mapper import CategoryMapper, CategoryConfig, map_category
from .quality_scorer import QualityScorer, QualityConfig, score_quality

LOG = logging.getLogger(__name__)


@dataclass
class PipelineConfig:
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    deduplication: DedupConfig = field(default_factory=DedupConfig)
    price: PriceConfig = field(default_factory=PriceConfig)
    date: DateConfig = field(default_factory=DateConfig)
    category: CategoryConfig = field(default_factory=CategoryConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)
    
    # Pipeline options
    enable_validation: bool = True
    enable_deduplication: bool = True
    enable_price_normalization: bool = True
    enable_date_normalization: bool = True
    enable_category_mapping: bool = True
    enable_quality_scoring: bool = True
    
    # Output options
    add_normalized_fields: bool = True
    add_quality_score: bool = True
    drop_invalid: bool = False
    min_quality_threshold: float = 0.3


@dataclass
class ProcessingResult:
    item: Any
    validation: Optional[ValidationResult] = None
    deduplication: Optional[DeduplicationResult] = None
    normalized_prices: List[NormalizedPrice] = field(default_factory=list)
    normalized_dates: List[NormalizedDate] = field(default_factory=list)
    category: Optional[Any] = None
    quality: Optional[QualityScore] = None
    success: bool = True
    errors: List[str] = field(default_factory=list)
    processing_time_ms: float = 0.0


class DataQualityPipeline:
    """Complete data quality processing pipeline."""
    
    def __init__(self, config: Optional[PipelineConfig] = None):
        self.config = config or PipelineConfig()
        
        self.validator = DataValidator(self.config.validation)
        self.deduplicator = ContentDeduplicator(self.config.deduplication)
        self.price_normalizer = PriceNormalizer(self.config.price)
        self.date_normalizer = DateNormalizer(self.config.date)
        self.category_mapper = CategoryMapper(self.config.category)
        self.quality_scorer = QualityScorer(self.config.quality)
        
        self._stats = {
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "duplicates": 0,
            "dropped": 0,
        }
    
    def process(self, item: Any, item_type: str = "auto") -> ProcessingResult:
        """Process a single item through the pipeline."""
        import time
        start_time = time.time()
        
        result = ProcessingResult(item=item)
        
        try:
            # Step 1: Validation
            if self.config.enable_validation:
                validation_result = self.validator.validate(item, item_type)
                result.validation = validation_result
                
                if not validation_result.valid:
                    self._stats["invalid"] += 1
                    if self.config.drop_invalid:
                        result.success = False
                        result.errors.append("Validation failed")
                        return result
                else:
                    self._stats["valid"] += 1
            
            # Step 2: Deduplication
            if self.config.enable_deduplication:
                dedup_result = self.deduplicator.is_duplicate(item)
                result.deduplication = dedup_result
                
                if dedup_result.is_duplicate:
                    self._stats["duplicates"] += 1
                    if self.config.drop_invalid:
                        result.success = False
                        result.errors.append(f"Duplicate detected: {dedup_result.method}")
                        return result
                
                # Add to deduplicator index
                self.deduplicator.add(item)
            
            # Step 3: Price normalization
            if self.config.enable_price_normalization:
                result.normalized_prices = self._normalize_prices(item)
                if self.config.add_normalized_fields:
                    self._attach_normalized_prices(item, result.normalized_prices)
            
            # Step 4: Date normalization
            if self.config.enable_date_normalization:
                result.normalized_dates = self._normalize_dates(item)
                if self.config.add_normalized_fields:
                    self._attach_normalized_dates(item, result.normalized_dates)
            
            # Step 5: Category mapping
            if self.config.enable_category_mapping:
                result.category = self._map_category(item)
                if self.config.add_normalized_fields:
                    self._attach_category(item, result.category)
            
            # Step 6: Quality scoring
            if self.config.enable_quality_scoring:
                result.quality = self.quality_scorer.score(item)
                if self.config.add_normalized_fields:
                    self._attach_quality_score(item, result.quality)
                
                # Check quality threshold
                if result.quality.overall < self.config.min_quality_threshold:
                    if self.config.drop_invalid:
                        result.success = False
                        result.errors.append(f"Quality below threshold: {result.quality.overall:.2f}")
                        self._stats["dropped"] += 1
                        return result
            
            self._stats["processed"] += 1
            
        except Exception as e:
            LOG.error(f"Pipeline error: {e}")
            result.success = False
            result.errors.append(str(e))
        
        result.processing_time_ms = (time.time() - start_time) * 1000
        return result
    
    def process_batch(self, items: List[Any], item_type: str = "auto") -> List[ProcessingResult]:
        """Process multiple items."""
        return [self.process(item, item_type) for item in items]
    
    def _normalize_prices(self, item: Any) -> List[NormalizedPrice]:
        """Extract and normalize prices from item."""
        prices = []
        
        # Direct price fields
        price_fields = ["price", "original_price", "sale_price", "discount_pct"]
        for field in price_fields:
            value = getattr(item, field, None)
            if value is not None:
                normalized = self.price_normalizer.normalize(value)
                if normalized.normalized_value > 0:
                    normalized.original_value = f"{field}:{normalized.original_value}"
                    prices.append(normalized)
        
        # Extract from text fields
        text_fields = ["content", "description", "body"]
        for field in text_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, str):
                extracted = self.price_normalizer.extract_prices_from_text(value)
                prices.extend(extracted)
        
        # Deduplicate
        seen = set()
        unique = []
        for p in prices:
            key = (p.normalized_value, p.currency)
            if key not in seen:
                seen.add(key)
                unique.append(p)
        return unique
    
    def _attach_normalized_prices(self, item: Any, prices: List[NormalizedPrice]):
        """Attach normalized prices to item."""
        if hasattr(item, "__dict__"):
            item._normalized_prices = prices
            if prices:
                best = max(prices, key=lambda p: p.normalized_value)
                item._normalized_price = best.normalized_value
                item._normalized_currency = best.currency
    
    def _normalize_dates(self, item: Any) -> List[NormalizedDate]:
        """Extract and normalize dates from item."""
        dates = []
        
        # Direct date fields
        date_fields = ["scraped_at", "published_at", "updated_at", "posted_at", "release_date"]
        for field in date_fields:
            value = getattr(item, field, None)
            if value:
                normalized = self.date_normalizer.normalize(value)
                normalized.original_value = f"{field}:{normalized.original_value}"
                dates.append(normalized)
        
        # Extract from text
        text_fields = ["content", "description", "body"]
        for field in text_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, str):
                extracted = self.date_normalizer.extract_dates_from_text(value)
                dates.extend(extracted)
        
        # Deduplicate
        seen = set()
        unique = []
        for d in dates:
            key = d.normalized_value.isoformat()
            if key not in seen:
                seen.add(key)
                unique.append(d)
        return unique
    
    def _attach_normalized_dates(self, item: Any, dates: List[NormalizedDate]):
        """Attach normalized dates to item."""
        if hasattr(item, "__dict__"):
            item._normalized_dates = dates
            if dates:
                item._normalized_date = dates[0].normalized_value
    
    def _map_category(self, item: Any) -> Optional[Any]:
        """Map item to category."""
        if isinstance(item, BaseProduct):
            return self.category_mapper.map_product(item)
        elif isinstance(item, BaseArticle):
            return self.category_mapper.map_article(item)
        elif isinstance(item, BaseListing):
            return self.category_mapper.map_listing(item)
        else:
            # Generic mapping from text
            text_parts = []
            for field in ["title", "name", "content", "description", "category"]:
                value = getattr(item, field, None)
                if value:
                    text_parts.append(str(value))
            text = " ".join(text_parts)
            return self.category_mapper.map_category(text)
    
    def _attach_category(self, item: Any, category: Any):
        """Attach category mapping to item."""
        if hasattr(item, "__dict__") and category:
            item._mapped_category = category.mapped
            item._category_confidence = category.confidence
            item._category_taxonomy = category.taxonomy_path
    
    def _attach_quality_score(self, item: Any, quality: QualityScore):
        """Attach quality score to item."""
        if hasattr(item, "__dict__"):
            item._quality_score = quality.overall
            item._quality_details = quality.details
            item._quality_issues = quality.issues
    
    def get_stats(self) -> Dict[str, int]:
        """Get processing statistics."""
        return self._stats.copy()
    
    def reset_stats(self):
        """Reset statistics."""
        self._stats = {
            "processed": 0,
            "valid": 0,
            "invalid": 0,
            "duplicates": 0,
            "dropped": 0,
        }
    
    def reset_deduplicator(self):
        """Reset deduplicator index."""
        self.deduplicator.clear()


def create_pipeline(config: Optional[PipelineConfig] = None) -> DataQualityPipeline:
    """Factory function to create pipeline."""
    return DataQualityPipeline(config)