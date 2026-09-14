from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Union
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator, model_validator


class Currency(str, Enum):
    USD = "USD"
    EUR = "EUR"
    GBP = "GBP"
    JPY = "JPY"
    CAD = "CAD"
    AUD = "AUD"
    CHF = "CHF"
    CNY = "CNY"
    INR = "INR"
    BRL = "BRL"
    KRW = "KRW"
    RUB = "RUB"
    TRY = "TRY"
    UNKNOWN = "UNKNOWN"


class ProductCategory(str, Enum):
    ELECTRONICS = "electronics"
    COMPUTERS = "computers"
    PHONES = "phones"
    AUDIO = "audio"
    CAMERAS = "cameras"
    HOME_APPLIANCES = "home_appliances"
    KITCHEN = "kitchen"
    FURNITURE = "furniture"
    CLOTHING = "clothing"
    SHOES = "shoes"
    ACCESSORIES = "accessories"
    BEAUTY = "beauty"
    HEALTH = "health"
    SPORTS = "sports"
    OUTDOORS = "outdoors"
    TOYS = "toys"
    GAMES = "games"
    BOOKS = "books"
    AUTOMOTIVE = "automotive"
    INDUSTRIAL = "industrial"
    OTHER = "other"


@dataclass
class QualityConfig:
    completeness_weights: Dict[str, float] = field(default_factory=lambda: {
        "required_fields": 0.3,
        "optional_fields": 0.2,
        "content_length": 0.2,
        "media": 0.15,
        "metadata": 0.15,
    })
    accuracy_weights: Dict[str, float] = field(default_factory=lambda: {
        "price_valid": 0.25,
        "date_valid": 0.25,
        "url_valid": 0.25,
        "format_valid": 0.25,
    })
    consistency_weights: Dict[str, float] = field(default_factory=lambda: {
        "internal": 0.5,
        "cross_field": 0.5,
    })
    freshness_weights: Dict[str, float] = field(default_factory=lambda: {
        "recency": 0.6,
        "update_frequency": 0.4,
    })
    richness_weights: Dict[str, float] = field(default_factory=lambda: {
        "detail_level": 0.4,
        "media_count": 0.3,
        "structured_data": 0.3,
    })
    overall_weights: Dict[str, float] = field(default_factory=lambda: {
        "completeness": 0.25,
        "accuracy": 0.25,
        "consistency": 0.20,
        "freshness": 0.15,
        "richness": 0.15,
    })
    min_quality_threshold: float = 0.5


class ValidationError(BaseModel):
    field: str
    message: str
    value: Any = None
    code: str = "validation_error"


class ValidationResult(BaseModel):
    valid: bool
    errors: List[ValidationError] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    score: float = 1.0

    def add_error(self, field: str, message: str, value: Any = None, code: str = "validation_error"):
        self.errors.append(ValidationError(field=field, message=message, value=value, code=code))
        self.valid = False
        self.score = max(0.0, self.score - 0.1)

    def add_warning(self, message: str):
        self.warnings.append(message)
        self.score = max(0.0, self.score - 0.02)


class BaseModelMixin(BaseModel):
    source_url: str = ""
    source_domain: str = ""
    scraped_at: datetime = Field(default_factory=datetime.utcnow)
    raw_data: Dict[str, Any] = Field(default_factory=dict)
    content_hash: str = ""
    
    @model_validator(mode="after")
    def compute_hash(self) -> "BaseModelMixin":
        import hashlib
        content = str(self.model_dump(exclude={"content_hash", "raw_data", "scraped_at"}))
        self.content_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
        return self


class BaseProduct(BaseModelMixin):
    name: str = ""
    brand: str = ""
    model: str = ""
    sku: str = ""
    mpn: str = ""
    gtin: str = ""
    upc: str = ""
    ean: str = ""
    isbn: str = ""
    
    price: Optional[Decimal] = None
    original_price: Optional[Decimal] = None
    currency: Currency = Currency.USD
    sale_price: Optional[Decimal] = None
    discount_pct: Optional[float] = None
    
    category: ProductCategory = ProductCategory.OTHER
    subcategory: str = ""
    tags: List[str] = Field(default_factory=list)
    
    description: str = ""
    short_description: str = ""
    specifications: Dict[str, Any] = Field(default_factory=dict)
    
    images: List[str] = Field(default_factory=list)
    thumbnail: str = ""
    
    availability: str = ""
    in_stock: bool = True
    stock_quantity: Optional[int] = None
    condition: str = "new"
    
    rating: Optional[float] = None
    review_count: int = 0
    
    seller: str = ""
    seller_rating: Optional[float] = None
    shipping_info: str = ""
    
    dimensions: Dict[str, float] = Field(default_factory=dict)
    weight: Optional[float] = None
    weight_unit: str = "kg"
    
    color: str = ""
    size: str = ""
    material: str = ""
    
    warranty: str = ""
    release_date: Optional[datetime] = None
    
    @field_validator("price", "original_price", "sale_price", mode="before")
    @classmethod
    def parse_price(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        if isinstance(v, str):
            import re
            cleaned = re.sub(r"[^\d.,\-]", "", v)
            cleaned = cleaned.replace(",", "")
            try:
                return Decimal(cleaned)
            except:
                return None
        return None
    
    @field_validator("rating", mode="before")
    @classmethod
    def parse_rating(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except:
                return None
        return None
    
    @field_validator("discount_pct", mode="before")
    @classmethod
    def parse_discount(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            import re
            match = re.search(r"(\d+(?:\.\d+)?)", v)
            if match:
                return float(match.group(1))
        return None


class BaseArticle(BaseModelMixin):
    title: str = ""
    subtitle: str = ""
    author: str = ""
    author_url: str = ""
    
    published_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    
    category: str = ""
    tags: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    
    content: str = ""
    excerpt: str = ""
    word_count: int = 0
    reading_time_min: int = 0
    
    images: List[str] = Field(default_factory=list)
    videos: List[str] = Field(default_factory=list)
    
    language: str = "en"
    
    @field_validator("published_at", "updated_at", mode="before")
    @classmethod
    def parse_datetime(cls, v):
        if v is None:
            return None
        if isinstance(v, datetime):
            return v
        if isinstance(v, str):
            formats = [
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
                "%d/%m/%Y",
                "%m/%d/%Y",
                "%B %d, %Y",
                "%b %d, %Y",
            ]
            for fmt in formats:
                try:
                    return datetime.strptime(v, fmt)
                except:
                    continue
        return None


class BaseReview(BaseModelMixin):
    product_id: str = ""
    product_name: str = ""
    
    reviewer_name: str = ""
    reviewer_id: str = ""
    reviewer_verified: bool = False
    
    rating: float = 0.0
    max_rating: float = 5.0
    
    title: str = ""
    content: str = ""
    
    pros: List[str] = Field(default_factory=list)
    cons: List[str] = Field(default_factory=list)
    
    helpful_votes: int = 0
    total_votes: int = 0
    
    verified_purchase: bool = False
    posted_at: Optional[datetime] = None
    
    @field_validator("rating", mode="before")
    @classmethod
    def parse_rating(cls, v):
        if v is None:
            return 0.0
        if isinstance(v, (int, float)):
            return float(v)
        if isinstance(v, str):
            try:
                return float(v)
            except:
                return 0.0
        return 0.0


class BaseListing(BaseModelMixin):
    title: str = ""
    description: str = ""
    
    category: str = ""
    subcategory: str = ""
    
    price: Optional[Decimal] = None
    currency: Currency = Currency.USD
    price_type: str = "fixed"
    
    location: str = ""
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    
    condition: str = "used"
    posting_date: Optional[datetime] = None
    expiry_date: Optional[datetime] = None
    
    images: List[str] = Field(default_factory=list)
    
    seller_name: str = ""
    seller_type: str = "individual"
    seller_rating: Optional[float] = None
    seller_verified: bool = False
    
    features: Dict[str, Any] = Field(default_factory=dict)


class DeduplicationResult(BaseModel):
    is_duplicate: bool
    duplicate_id: str = ""
    similarity: float = 0.0
    matched_fields: List[str] = Field(default_factory=list)
    method: str = ""


class NormalizedPrice(BaseModel):
    original_value: str = ""
    normalized_value: Decimal = Decimal("0")
    currency: Currency = Currency.USD
    original_currency: str = ""
    exchange_rate: float = 1.0
    is_sale: bool = False
    discount_pct: Optional[float] = None


class NormalizedDate(BaseModel):
    original_value: str = ""
    normalized_value: datetime = Field(default_factory=datetime.utcnow)
    timezone: str = "UTC"
    is_relative: bool = False
    relative_days: Optional[int] = None


class MappedCategory(BaseModel):
    original: str = ""
    mapped: ProductCategory = ProductCategory.OTHER
    confidence: float = 0.0
    matched_keywords: List[str] = Field(default_factory=list)
    taxonomy_path: List[str] = Field(default_factory=list)


class QualityScore(BaseModel):
    overall: float = 0.0
    completeness: float = 0.0
    accuracy: float = 0.0
    consistency: float = 0.0
    freshness: float = 0.0
    richness: float = 0.0
    
    details: Dict[str, Any] = Field(default_factory=dict)
    issues: List[str] = Field(default_factory=list)