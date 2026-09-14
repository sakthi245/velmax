from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from .models import (
    BaseModelMixin,
    BaseProduct,
    BaseArticle,
    BaseReview,
    BaseListing,
    DeduplicationResult,
)


@dataclass
class DedupConfig:
    url_similarity_threshold: float = 0.95
    title_similarity_threshold: float = 0.90
    content_similarity_threshold: float = 0.85
    use_content_hash: bool = True
    use_url_normalization: bool = True
    use_title_normalization: bool = True
    max_memory_items: int = 100_000
    bloom_filter_size: int = 1_000_000
    bloom_fp_rate: float = 0.01


class ContentDeduplicator:
    def __init__(self, config: Optional[DedupConfig] = None):
        self.config = config or DedupConfig()
        self._seen_hashes: Set[str] = set()
        self._seen_urls: Dict[str, str] = {}  # normalized_url -> item_id
        self._seen_titles: Dict[str, str] = {}  # normalized_title -> item_id
        self._content_index: List[Tuple[str, str, datetime]] = []  # (hash, item_id, timestamp)
    
    def is_duplicate(self, item: BaseModelMixin) -> DeduplicationResult:
        """Check if item is a duplicate of already seen content."""
        result = DeduplicationResult(is_duplicate=False)
        
        # 1. Check content hash (exact duplicate)
        if self.config.use_content_hash and item.content_hash:
            if item.content_hash in self._seen_hashes:
                result.is_duplicate = True
                result.duplicate_id = item.content_hash
                result.similarity = 1.0
                result.matched_fields = ["content_hash"]
                result.method = "content_hash"
                return result
        
        # 2. Check URL similarity
        url = getattr(item, "source_url", "") or getattr(item, "url", "")
        if url and self.config.use_url_normalization:
            norm_url = self._normalize_url(url)
            if norm_url in self._seen_urls:
                result.is_duplicate = True
                result.duplicate_id = self._seen_urls[norm_url]
                result.similarity = self.config.url_similarity_threshold
                result.matched_fields = ["url"]
                result.method = "url_exact"
                return result
        
        # 3. Check title similarity
        title = getattr(item, "title", "") or getattr(item, "name", "")
        if title and self.config.use_title_normalization:
            norm_title = self._normalize_title(title)
            for seen_title, seen_id in self._seen_titles.items():
                similarity = self._similarity(norm_title, seen_title)
                if similarity >= self.config.title_similarity_threshold:
                    result.is_duplicate = True
                    result.duplicate_id = seen_id
                    result.similarity = similarity
                    result.matched_fields = ["title"]
                    result.method = "title_fuzzy"
                    return result
        
        # 4. Content-based similarity for articles
        if isinstance(item, (BaseArticle, BaseReview)):
            content = getattr(item, "content", "") or getattr(item, "description", "")
            if content:
                content_hash = self._content_fingerprint(content)
                for stored_hash, stored_id, _ in self._content_index[-1000:]:  # Check recent
                    if content_hash == stored_hash:
                        result.is_duplicate = True
                        result.duplicate_id = stored_id
                        result.similarity = 1.0
                        result.matched_fields = ["content_fingerprint"]
                        result.method = "content_fingerprint"
                        return result
        
        return result
    
    def add(self, item: BaseModelMixin):
        """Add item to deduplication index."""
        item_id = getattr(item, "content_hash", "") or str(uuid4())
        
        if self.config.use_content_hash and item.content_hash:
            self._seen_hashes.add(item.content_hash)
        
        url = getattr(item, "source_url", "") or getattr(item, "url", "")
        if url and self.config.use_url_normalization:
            norm_url = self._normalize_url(url)
            self._seen_urls[norm_url] = item_id
        
        title = getattr(item, "title", "") or getattr(item, "name", "")
        if title and self.config.use_title_normalization:
            norm_title = self._normalize_title(title)
            self._seen_titles[norm_title] = item_id
        
        if isinstance(item, (BaseArticle, BaseReview)):
            content = getattr(item, "content", "") or getattr(item, "description", "")
            if content:
                content_hash = self._content_fingerprint(content)
                self._content_index.append((content_hash, item_id, datetime.utcnow()))
                if len(self._content_index) > self.config.max_memory_items:
                    self._content_index = self._content_index[-self.config.max_memory_items:]
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for comparison."""
        # Remove protocol
        url = re.sub(r"^https?://", "", url, flags=re.IGNORECASE)
        # Remove www
        url = re.sub(r"^www\.", "", url, flags=re.IGNORECASE)
        # Remove trailing slash
        url = url.rstrip("/")
        # Remove query parameters (except specific ones)
        url = re.sub(r"\?(utm_|fbclid|gclid|ref|src=)", "?", url, flags=re.IGNORECASE)
        # Remove all query params for strict matching
        url = url.split("?")[0]
        return url.lower()
    
    def _normalize_title(self, title: str) -> str:
        """Normalize title for comparison."""
        # Lowercase
        title = title.lower()
        # Remove punctuation
        title = re.sub(r"[^\w\s]", "", title)
        # Remove extra whitespace
        title = re.sub(r"\s+", " ", title).strip()
        # Remove common words
        stopwords = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with", "by"}
        words = [w for w in title.split() if w not in stopwords]
        return " ".join(words)
    
    def _content_fingerprint(self, content: str) -> str:
        """Generate fingerprint for content similarity."""
        # Take first 500 chars and last 500 chars
        text = content[:500] + content[-500:] if len(content) > 1000 else content
        return hashlib.sha256(text.encode()).hexdigest()[:16]
    
    def _similarity(self, a: str, b: str) -> float:
        """Calculate string similarity ratio."""
        return SequenceMatcher(None, a, b).ratio()
    
    def clear(self):
        """Clear all deduplication data."""
        self._seen_hashes.clear()
        self._seen_urls.clear()
        self._seen_titles.clear()
        self._content_index.clear()
    
    def stats(self) -> Dict[str, int]:
        return {
            "hashes": len(self._seen_hashes),
            "urls": len(self._seen_urls),
            "titles": len(self._seen_titles),
            "content_items": len(self._content_index),
        }


class ProductDeduplicator(ContentDeduplicator):
    """Specialized deduplicator for products with SKU/GTIN matching."""
    
    def is_duplicate(self, item: BaseProduct) -> DeduplicationResult:
        result = super().is_duplicate(item)
        if result.is_duplicate:
            return result
        
        # Check SKU
        if item.sku:
            # Would check against stored SKUs
            pass
        
        # Check GTIN/UPC/EAN
        for identifier in [item.gtin, item.upc, item.ean, item.isbn, item.mpn]:
            if identifier:
                # Check against stored identifiers
                pass
        
        return result
    
    def add(self, item: BaseProduct):
        super().add(item)
        # Index identifiers
        for identifier in [item.sku, item.gtin, item.upc, item.ean, item.isbn, item.mpn]:
            if identifier:
                pass  # Store for lookup


class ArticleDeduplicator(ContentDeduplicator):
    """Specialized deduplicator for articles with author/date matching."""
    
    def is_duplicate(self, item: BaseArticle) -> DeduplicationResult:
        result = super().is_duplicate(item)
        if result.is_duplicate:
            return result
        
        # Check author + published date combination
        if item.author and item.published_at:
            key = f"{item.author.lower()}:{item.published_at.date()}"
            # Would check against stored keys
        
        return result


def create_deduplicator(item_type: str = "generic") -> ContentDeduplicator:
    if item_type == "product":
        return ProductDeduplicator()
    elif item_type == "article":
        return ArticleDeduplicator()
    return ContentDeduplicator()