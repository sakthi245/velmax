from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Set, Tuple

from .models import (
    QualityScore,
    QualityConfig,
    BaseProduct,
    BaseArticle,
    BaseReview,
    BaseListing,
    BaseModelMixin,
    Currency,
)


class QualityScorer:
    def __init__(self, config: Optional[QualityConfig] = None):
        self.config = config or QualityConfig()
    
    def score(self, item: BaseModelMixin) -> QualityScore:
        """Calculate quality score for an item."""
        score = QualityScore()
        
        # Calculate individual dimensions
        score.completeness = self._score_completeness(item)
        score.accuracy = self._score_accuracy(item)
        score.consistency = self._score_consistency(item)
        score.freshness = self._score_freshness(item)
        score.richness = self._score_richness(item)
        
        # Calculate overall weighted score
        score.overall = (
            score.completeness * self.config.overall_weights["completeness"] +
            score.accuracy * self.config.overall_weights["accuracy"] +
            score.consistency * self.config.overall_weights["consistency"] +
            score.freshness * self.config.overall_weights["freshness"] +
            score.richness * self.config.overall_weights["richness"]
        )
        
        # Generate details and issues
        self._generate_details(item, score)
        
        return score
    
    def _score_completeness(self, item: BaseModelMixin) -> float:
        """Score based on field completeness."""
        weights = self.config.completeness_weights
        score = 0.0
        
        # Required fields
        required_score = self._check_required_fields(item)
        score += required_score * weights["required_fields"]
        
        # Optional fields
        optional_score = self._check_optional_fields(item)
        score += optional_score * weights["optional_fields"]
        
        # Content length
        content_score = self._check_content_length(item)
        score += content_score * weights["content_length"]
        
        # Media
        media_score = self._check_media(item)
        score += media_score * weights["media"]
        
        # Metadata
        meta_score = self._check_metadata(item)
        score += meta_score * weights["metadata"]
        
        return min(score, 1.0)
    
    def _check_required_fields(self, item: BaseModelMixin) -> float:
        """Check if required fields are present."""
        required_map = {
            BaseProduct: ["name", "price", "currency"],
            BaseArticle: ["title", "content"],
            BaseReview: ["rating", "content"],
            BaseListing: ["title", "price"],
        }
        
        required = required_map.get(type(item), [])
        if not required:
            return 0.5
        
        present = sum(1 for field in required if getattr(item, field, None))
        return present / len(required) if required else 0.0
    
    def _check_optional_fields(self, item: BaseModelMixin) -> float:
        """Check optional field coverage."""
        optional_map = {
            BaseProduct: [
                "brand", "model", "sku", "description", "images",
                "availability", "rating", "review_count", "specifications",
                "dimensions", "weight", "color", "size"
            ],
            BaseArticle: [
                "author", "subtitle", "tags", "keywords", "images",
                "published_at", "updated_at", "word_count"
            ],
            BaseReview: [
                "reviewer_name", "title", "pros", "cons",
                "helpful_votes", "verified_purchase", "posted_at"
            ],
            BaseListing: [
                "description", "location", "images", "condition",
                "posting_date", "features", "seller_name"
            ],
        }
        
        optional = optional_map.get(type(item), [])
        if not optional:
            return 0.5
        
        present = sum(1 for field in optional if getattr(item, field, None))
        return min(present / len(optional) * 1.5, 1.0)  # Bonus for more fields
    
    def _check_content_length(self, item: BaseModelMixin) -> float:
        """Score based on content richness."""
        content_fields = ["content", "description", "body"]
        total_length = 0
        count = 0
        
        for field in content_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, str):
                total_length += len(value)
                count += 1
        
        if count == 0:
            return 0.0
        
        avg_length = total_length / count
        # Score based on length: 500+ chars = 1.0, 100 chars = 0.2
        if avg_length >= 500:
            return 1.0
        elif avg_length >= 200:
            return 0.7
        elif avg_length >= 100:
            return 0.4
        elif avg_length >= 50:
            return 0.2
        return 0.1
    
    def _check_media(self, item: BaseModelMixin) -> float:
        """Score based on media presence."""
        images = getattr(item, "images", [])
        videos = getattr(item, "videos", [])
        thumbnail = getattr(item, "thumbnail", "")
        
        media_count = len(images) + len(videos) + (1 if thumbnail else 0)
        
        if media_count >= 5:
            return 1.0
        elif media_count >= 3:
            return 0.8
        elif media_count >= 1:
            return 0.5
        return 0.1
    
    def _check_metadata(self, item: BaseModelMixin) -> float:
        """Score based on metadata completeness."""
        meta_fields = ["source_url", "source_domain", "scraped_at", "content_hash"]
        present = sum(1 for field in meta_fields if getattr(item, field, None))
        return present / len(meta_fields)
    
    def _score_accuracy(self, item: BaseModelMixin) -> float:
        """Score based on data accuracy/validity."""
        weights = self.config.accuracy_weights
        score = 0.0
        
        # Price validation
        price_score = self._validate_prices(item)
        score += price_score * weights["price_valid"]
        
        # Date validation
        date_score = self._validate_dates(item)
        score += date_score * weights["date_valid"]
        
        # URL validation
        url_score = self._validate_urls(item)
        score += url_score * weights["url_valid"]
        
        # Format validation
        format_score = self._validate_formats(item)
        score += format_score * weights["format_valid"]
        
        return min(score, 1.0)
    
    def _validate_prices(self, item: BaseModelMixin) -> float:
        """Validate price fields."""
        price_fields = ["price", "original_price", "sale_price"]
        valid = 0
        total = 0
        
        for field in price_fields:
            value = getattr(item, field, None)
            if value is not None:
                total += 1
                if isinstance(value, Decimal):
                    if value >= 0 and value < Decimal("1000000"):
                        valid += 1
                elif isinstance(value, (int, float)):
                    if value >= 0 and value < 1000000:
                        valid += 1
        
        # Check discount consistency
        if isinstance(item, BaseProduct):
            if item.price and item.original_price and item.original_price > item.price:
                expected = float((item.original_price - item.price) / item.original_price * 100)
                if item.discount_pct and abs(item.discount_pct - expected) <= 2.0:
                    valid += 1
                total += 1
        
        return valid / total if total > 0 else 0.5
    
    def _validate_dates(self, item: BaseModelMixin) -> float:
        """Validate date fields."""
        date_fields = ["scraped_at", "published_at", "updated_at", "posted_at", "release_date"]
        valid = 0
        total = 0
        now = datetime.now(timezone.utc)
        
        for field in date_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, datetime):
                total += 1
                # Make both timezone-aware for comparison
                value_aware = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
                if value_aware <= now and value.year >= 2000:
                    valid += 1
        
        # Logical ordering
        pub = getattr(item, "published_at", None)
        upd = getattr(item, "updated_at", None)
        if pub and upd:
            total += 1
            # Make both timezone-aware for comparison
            pub_aware = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            upd_aware = upd if upd.tzinfo else upd.replace(tzinfo=timezone.utc)
            if upd_aware >= pub_aware:
                valid += 1
        
        return valid / total if total > 0 else 0.5
    
    def _validate_urls(self, item: BaseModelMixin) -> float:
        """Validate URL fields."""
        url_fields = ["source_url", "url", "link", "image", "thumbnail", "author_url"]
        valid = 0
        total = 0
        
        url_pattern = re.compile(r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE)
        
        for field in url_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, str):
                total += 1
                if url_pattern.match(value):
                    valid += 1
        
        # Check images array
        images = getattr(item, "images", [])
        if images:
            total += len(images)
            valid += sum(1 for img in images if url_pattern.match(img))
        
        return valid / total if total > 0 else 0.5
    
    def _validate_formats(self, item: BaseModelMixin) -> float:
        """Validate data formats."""
        valid = 0
        total = 0
        
        # Email validation
        email_fields = ["email", "author_email"]
        email_pattern = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
        
        for field in email_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, str):
                total += 1
                if email_pattern.match(value):
                    valid += 1
        
        # Rating validation
        if isinstance(item, (BaseProduct, BaseReview)):
            rating = getattr(item, "rating", None)
            if rating is not None:
                total += 1
                if isinstance(rating, (int, float)) and 0 <= rating <= 5:
                    valid += 1
        
        # Currency validation
        currency = getattr(item, "currency", None)
        if currency:
            total += 1
            if isinstance(currency, Currency) or (isinstance(currency, str) and currency in [c.value for c in Currency]):
                valid += 1
        
        return valid / total if total > 0 else 0.5
    
    def _score_consistency(self, item: BaseModelMixin) -> float:
        """Score based on internal consistency."""
        weights = self.config.consistency_weights
        score = 0.0
        
        # Internal consistency
        internal_score = self._check_internal_consistency(item)
        score += internal_score * weights["internal"]
        
        # Cross-field consistency
        cross_score = self._check_cross_field_consistency(item)
        score += cross_score * weights["cross_field"]
        
        return min(score, 1.0)
    
    def _check_internal_consistency(self, item: BaseModelMixin) -> float:
        """Check for internal contradictions."""
        issues = 0
        checks = 0
        
        # Price vs original price
        if isinstance(item, BaseProduct):
            if item.price and item.original_price:
                checks += 1
                if item.price > item.original_price:
                    issues += 1
            
            # Discount consistency
            if item.price and item.original_price and item.discount_pct:
                checks += 1
                expected = float((item.original_price - item.price) / item.original_price * 100)
                if abs(item.discount_pct - expected) > 5.0:
                    issues += 1
            
            # Rating vs review count
            if item.rating and item.rating > 0 and item.review_count == 0:
                checks += 1
                issues += 1
        
        # Date consistency
        pub = getattr(item, "published_at", None)
        upd = getattr(item, "updated_at", None)
        if pub and upd:
            checks += 1
            if upd < pub:
                issues += 1
        
        return max(0.0, 1.0 - (issues / checks * 0.5)) if checks > 0 else 0.8
    
    def _check_cross_field_consistency(self, item: BaseModelMixin) -> float:
        """Check consistency across related fields."""
        issues = 0
        checks = 0
        
        # Category vs tags
        if hasattr(item, "category") and hasattr(item, "tags"):
            checks += 1
            cat_str = str(item.category).lower()
            tag_str = " ".join(item.tags).lower() if item.tags else ""
            if cat_str and tag_str and cat_str not in tag_str:
                # Not necessarily an issue, just lower confidence
                pass
        
        # Brand in name
        if isinstance(item, BaseProduct):
            if item.brand and item.name:
                checks += 1
                if item.brand.lower() not in item.name.lower():
                    issues += 0.5  # Minor issue
        
        # Currency consistency
        currency = getattr(item, "currency", None)
        price = getattr(item, "price", None)
        if currency and price:
            checks += 1
            # Could check if currency matches price format
        
        return max(0.0, 1.0 - (issues / checks * 0.3)) if checks > 0 else 0.9
    
    def _score_freshness(self, item: BaseModelMixin) -> float:
        """Score based on data freshness."""
        weights = self.config.freshness_weights
        score = 0.0
        
        # Recency
        recency_score = self._check_recency(item)
        score += recency_score * weights["recency"]
        
        # Update frequency
        update_score = self._check_update_frequency(item)
        score += update_score * weights["update_frequency"]
        
        return min(score, 1.0)
    
    def _check_recency(self, item: BaseModelMixin) -> float:
        """Check how recent the data is."""
        date_fields = ["scraped_at", "published_at", "updated_at", "posted_at"]
        best_date = None
        
        for field in date_fields:
            value = getattr(item, field, None)
            if value and isinstance(value, datetime):
                if best_date is None or value > best_date:
                    best_date = value
        
        if not best_date:
            return 0.3
        
        now = datetime.now(timezone.utc)
        # Make both timezone-aware for comparison
        best_date_aware = best_date if best_date.tzinfo else best_date.replace(tzinfo=timezone.utc)
        diff = now - best_date_aware
        
        days = diff.total_seconds() / 86400
        
        if days <= 1:
            return 1.0
        elif days <= 7:
            return 0.9
        elif days <= 30:
            return 0.7
        elif days <= 90:
            return 0.5
        elif days <= 365:
            return 0.3
        else:
            return 0.1
    
    def _check_update_frequency(self, item: BaseModelMixin) -> float:
        """Check if content is regularly updated."""
        pub = getattr(item, "published_at", None)
        upd = getattr(item, "updated_at", None)
        
        if pub and upd:
            # Make both timezone-aware
            pub_aware = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            upd_aware = upd if upd.tzinfo else upd.replace(tzinfo=timezone.utc)
            diff = upd_aware - pub_aware
            days = diff.total_seconds() / 86400
            
            if days <= 1:
                return 1.0  # Updated same day
            elif days <= 7:
                return 0.8
            elif days <= 30:
                return 0.6
            else:
                return 0.4
        
        return 0.5
    
    def _score_richness(self, item: BaseModelMixin) -> float:
        """Score based on data richness/detail."""
        weights = self.config.richness_weights
        score = 0.0
        
        # Detail level
        detail_score = self._check_detail_level(item)
        score += detail_score * weights["detail_level"]
        
        # Media count
        media_score = self._check_media_count(item)
        score += media_score * weights["media_count"]
        
        # Structured data
        struct_score = self._check_structured_data(item)
        score += struct_score * weights["structured_data"]
        
        return min(score, 1.0)
    
    def _check_detail_level(self, item: BaseModelMixin) -> float:
        """Check level of detail in content."""
        detail_fields = {
            BaseProduct: ["specifications", "dimensions", "weight", "warranty", "release_date"],
            BaseArticle: ["word_count", "reading_time_min", "keywords", "author"],
            BaseReview: ["pros", "cons", "helpful_votes", "verified_purchase"],
            BaseListing: ["features", "location", "condition", "seller_rating"],
        }
        
        fields = detail_fields.get(type(item), [])
        if not fields:
            return 0.5
        
        present = sum(1 for field in fields if getattr(item, field, None))
        return min(present / len(fields) * 1.5, 1.0)
    
    def _check_media_count(self, item: BaseModelMixin) -> float:
        """Score based on media quantity and variety."""
        images = getattr(item, "images", [])
        videos = getattr(item, "videos", [])
        
        total = len(images) + len(videos) * 2  # Videos worth more
        
        if total >= 10:
            return 1.0
        elif total >= 5:
            return 0.8
        elif total >= 3:
            return 0.6
        elif total >= 1:
            return 0.4
        return 0.1
    
    def _check_structured_data(self, item: BaseModelMixin) -> float:
        """Check for structured data presence."""
        checks = 0
        passed = 0
        
        # Has specifications
        if getattr(item, "specifications", None):
            checks += 1
            if item.specifications:
                passed += 1
        
        # Has dimensions
        if getattr(item, "dimensions", None):
            checks += 1
            if item.dimensions:
                passed += 1
        
        # Has features
        if getattr(item, "features", None):
            checks += 1
            if item.features:
                passed += 1
        
        # Has metadata
        if getattr(item, "metadata", None):
            checks += 1
            if item.metadata:
                passed += 1
        
        # Has tags/keywords
        for field in ["tags", "keywords"]:
            if getattr(item, field, None):
                checks += 1
                if getattr(item, field):
                    passed += 1
        
        return passed / checks if checks > 0 else 0.3
    
    def _generate_details(self, item: BaseModelMixin, score: QualityScore):
        """Generate detailed breakdown and issues."""
        score.details = {
            "completeness_breakdown": {
                "required_fields": self._check_required_fields(item),
                "optional_fields": self._check_optional_fields(item),
                "content_length": self._check_content_length(item),
                "media": self._check_media(item),
                "metadata": self._check_metadata(item),
            },
            "accuracy_breakdown": {
                "price_valid": self._validate_prices(item),
                "date_valid": self._validate_dates(item),
                "url_valid": self._validate_urls(item),
                "format_valid": self._validate_formats(item),
            },
            "consistency_breakdown": {
                "internal": self._check_internal_consistency(item),
                "cross_field": self._check_cross_field_consistency(item),
            },
            "freshness_breakdown": {
                "recency": self._check_recency(item),
                "update_frequency": self._check_update_frequency(item),
            },
            "richness_breakdown": {
                "detail_level": self._check_detail_level(item),
                "media_count": self._check_media_count(item),
                "structured_data": self._check_structured_data(item),
            },
        }
        
        # Generate issues list
        if score.completeness < 0.5:
            score.issues.append("Low field completeness")
        if score.accuracy < 0.6:
            score.issues.append("Data accuracy issues detected")
        if score.consistency < 0.6:
            score.issues.append("Internal consistency issues")
        if score.freshness < 0.4:
            score.issues.append("Data may be stale")
        if score.richness < 0.4:
            score.issues.append("Limited detail and media")


def score_quality(item: BaseModelMixin, config: Optional[QualityConfig] = None) -> QualityScore:
    """Convenience function to score item quality."""
    scorer = QualityScorer(config)
    return scorer.score(item)