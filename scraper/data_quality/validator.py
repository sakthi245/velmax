from __future__ import annotations

import re
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
    ValidationError,
    ProductCategory,
    Currency,
)


@dataclass
class ValidationConfig:
    required_fields: Dict[str, List[str]] = field(default_factory=lambda: {
        "product": ["name", "price", "currency"],
        "article": ["title", "content"],
        "review": ["rating", "content"],
        "listing": ["title", "price"],
    })
    min_content_length: int = 10
    max_content_length: int = 1_000_000
    validate_urls: bool = True
    validate_emails: bool = True
    validate_prices: bool = True
    validate_dates: bool = True
    strict_mode: bool = False
    custom_validators: Dict[str, List[callable]] = field(default_factory=dict)


class DataValidator:
    def __init__(self, config: Optional[ValidationConfig] = None):
        self.config = config or ValidationConfig()
        self._url_pattern = re.compile(
            r"^https?://[^\s/$.?#].[^\s]*$", re.IGNORECASE
        )
        self._email_pattern = re.compile(
            r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        )
    
    def validate(self, item: BaseModelMixin, item_type: str = "auto") -> ValidationResult:
        if item_type == "auto":
            item_type = self._detect_type(item)
        
        result = ValidationResult(valid=True)
        
        # Required fields
        required = self.config.required_fields.get(item_type, [])
        for field_name in required:
            value = getattr(item, field_name, None)
            if not value or (isinstance(value, str) and not value.strip()):
                result.add_error(field_name, f"Required field '{field_name}' is missing or empty")
        
        # Content length
        content_fields = ["content", "description", "body"]
        for field_name in content_fields:
            value = getattr(item, field_name, None)
            if value and isinstance(value, str):
                if len(value) < self.config.min_content_length:
                    result.add_warning(f"Content in '{field_name}' is very short ({len(value)} chars)")
                if len(value) > self.config.max_content_length:
                    result.add_warning(f"Content in '{field_name}' is very long ({len(value)} chars)")
        
        # URL validation
        if self.config.validate_urls:
            url_fields = ["source_url", "url", "link", "image", "thumbnail", "author_url"]
            for field_name in url_fields:
                value = getattr(item, field_name, None)
                if value and isinstance(value, str) and value:
                    if not self._url_pattern.match(value):
                        result.add_error(field_name, f"Invalid URL format: {value}")
        
        # Email validation
        if self.config.validate_emails:
            email_fields = ["email", "author_email", "contact_email"]
            for field_name in email_fields:
                value = getattr(item, field_name, None)
                if value and isinstance(value, str) and value:
                    if not self._email_pattern.match(value):
                        result.add_error(field_name, f"Invalid email format: {value}")
        
        # Price validation
        if self.config.validate_prices:
            self._validate_prices(item, result)
        
        # Date validation
        if self.config.validate_dates:
            self._validate_dates(item, result)
        
        # Type-specific validation
        if isinstance(item, BaseProduct):
            self._validate_product(item, result)
        elif isinstance(item, BaseArticle):
            self._validate_article(item, result)
        elif isinstance(item, BaseReview):
            self._validate_review(item, result)
        elif isinstance(item, BaseListing):
            self._validate_listing(item, result)
        
        # Custom validators
        for validator in self.config.custom_validators.get(item_type, []):
            try:
                validator(item, result)
            except Exception as e:
                result.add_error("custom", f"Custom validator failed: {e}")
        
        return result
    
    def _detect_type(self, item: BaseModelMixin) -> str:
        if isinstance(item, BaseProduct):
            return "product"
        elif isinstance(item, BaseArticle):
            return "article"
        elif isinstance(item, BaseReview):
            return "review"
        elif isinstance(item, BaseListing):
            return "listing"
        return "generic"
    
    def _validate_prices(self, item: BaseModelMixin, result: ValidationResult):
        price_fields = ["price", "original_price", "sale_price", "discount_pct"]
        for field_name in price_fields:
            value = getattr(item, field_name, None)
            if value is not None:
                if isinstance(value, Decimal):
                    if value < 0:
                        result.add_error(field_name, f"Price cannot be negative: {value}")
                    if value > Decimal("1000000"):
                        result.add_warning(f"Price seems unusually high: {value}")
                elif isinstance(value, float):
                    if value < 0:
                        result.add_error(field_name, f"Price cannot be negative: {value}")
        # Check discount consistency
        if isinstance(item, BaseProduct):
            if item.price and item.original_price and item.original_price > item.price:
                expected_discount = float((item.original_price - item.price) / item.original_price * 100)
                if item.discount_pct and abs(item.discount_pct - expected_discount) > 1.0:
                    result.add_warning(
                        f"Discount percentage mismatch: stated {item.discount_pct}%, "
                        f"calculated {expected_discount:.1f}%"
                    )
    
    def _validate_dates(self, item: BaseModelMixin, result: ValidationResult):
        date_fields = ["scraped_at", "published_at", "updated_at", "posted_at", "release_date"]
        for field_name in date_fields:
            value = getattr(item, field_name, None)
            if value and isinstance(value, datetime):
                if value > datetime.utcnow():
                    result.add_error(field_name, f"Date is in the future: {value}")
                if value.year < 2000:
                    result.add_warning(f"Date seems very old: {value}")
        # Check logical ordering
        if hasattr(item, "published_at") and hasattr(item, "updated_at"):
            pub = getattr(item, "published_at", None)
            upd = getattr(item, "updated_at", None)
            if pub and upd and upd < pub:
                result.add_error("updated_at", "Updated date is before published date")
    
    def _validate_product(self, item: BaseProduct, result: ValidationResult):
        if item.price and item.price <= 0:
            result.add_error("price", "Product price must be positive")
        if item.rating is not None and (item.rating < 0 or item.rating > 5):
            result.add_error("rating", "Rating must be between 0 and 5")
        if item.images:
            for img in item.images:
                if img and not self._url_pattern.match(img):
                    result.add_error("images", f"Invalid image URL: {img}")
    
    def _validate_article(self, item: BaseArticle, result: ValidationResult):
        if item.word_count and item.word_count < 50:
            result.add_warning("Article word count is very low")
        if item.reading_time_min and item.reading_time_min < 1:
            result.add_warning("Reading time seems too short")
    
    def _validate_review(self, item: BaseReview, result: ValidationResult):
        if item.rating < 0 or item.rating > item.max_rating:
            result.add_error("rating", f"Rating must be between 0 and {item.max_rating}")
        if item.helpful_votes > item.total_votes:
            result.add_error("votes", "Helpful votes cannot exceed total votes")
    
    def _validate_listing(self, item: BaseListing, result: ValidationResult):
        if item.price and item.price <= 0:
            result.add_error("price", "Listing price must be positive")
        if item.latitude is not None and (item.latitude < -90 or item.latitude > 90):
            result.add_error("latitude", "Invalid latitude")
        if item.longitude is not None and (item.longitude < -180 or item.longitude > 180):
            result.add_error("longitude", "Invalid longitude")


def validate_item(item: BaseModelMixin, config: Optional[ValidationConfig] = None) -> ValidationResult:
    validator = DataValidator(config)
    return validator.validate(item)