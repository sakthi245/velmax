from __future__ import annotations

import hashlib
import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple, Union
from collections import defaultdict

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

try:
    from sentence_transformers import SentenceTransformer
    HAS_SENTENCE_TRANSFORMERS = True
except ImportError:
    HAS_SENTENCE_TRANSFORMERS = False


@dataclass
class DedupConfig:
    """Configuration for semantic deduplication."""
    enabled: bool = True
    strategy: str = "hybrid"  # "hash", "simhash", "embedding", "hybrid"
    url_normalize: bool = True
    content_hash_algorithm: str = "xxhash"
    
    # SimHash settings
    simhash_bits: int = 64
    simhash_threshold: int = 3  # Hamming distance threshold
    
    # Embedding settings
    embedding_model: str = "all-MiniLM-L6-v2"  # SentenceTransformer model
    embedding_threshold: float = 0.85  # Cosine similarity threshold
    embedding_batch_size: int = 32
    
    # Hybrid weights
    hash_weight: float = 0.3
    simhash_weight: float = 0.4
    embedding_weight: float = 0.3
    
    # Hybrid thresholds
    exact_match_priority: bool = True
    simhash_threshold: int = 3  # Hamming distance
    embedding_threshold: float = 0.85  # Cosine similarity
    
    # Performance
    embedding_batch_size: int = 32
    max_embeddings_cache: int = 10000
    simhash_fingerprint_size: int = 64


class SimHash:
    """SimHash implementation for near-duplicate detection."""
    
    def __init__(self, bits: int = 64):
        self.bits = bits
        self.masks = [1 << i for i in range(bits)]
    
    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into shingles."""
        # Clean text
        text = text.lower()
        text = re.sub(r'[^\w\s]', ' ', text)
        text = re.sub(r'\s+', ' ', text).strip()
        
        # Create word shingles (3-grams)
        words = text.split()
        shingles = []
        for i in range(len(words) - 2):
            shingles.append(' '.join(words[i:i+3]))
        return shingles if shingles else [text]
    
    def _hash_token(self, token: str) -> int:
        """Hash a token to integer."""
        return int(hashlib.md5(token.encode()).hexdigest(), 16)
    
    def compute(self, text: str) -> int:
        """Compute SimHash for text."""
        shingles = self._tokenize(text)
        if not shingles:
            return 0
        
        # Weight each shingle by frequency
        shingle_weights = defaultdict(int)
        for shingle in shingles:
            shingle_weights[shingle] += 1
        
        # Compute weighted hash
        vectors = [0] * self.bits
        for shingle, weight in shingle_weights.items():
            h = self._hash_token(shingle)
            for i in range(self.bits):
                if h & (1 << (self.bits - 1 - i)):
                    vectors[i] += weight
                else:
                    vectors[i] -= weight
        
        # Build fingerprint
        fingerprint = 0
        for i, v in enumerate(vectors):
            if v > 0:
                fingerprint |= (1 << (self.bits - 1 - i))
        return fingerprint
    
    def hamming_distance(self, hash1: int, hash2: int) -> int:
        """Calculate Hamming distance between two fingerprints."""
        return bin(hash1 ^ hash2).count('1')
    
    def is_similar(self, hash1: int, hash2: int, threshold: int = 3) -> bool:
        """Check if two fingerprints are similar within threshold."""
        return self.hamming_distance(hash1, hash2) <= threshold


class EmbeddingDedup:
    """Embedding-based semantic deduplication using SentenceTransformers."""
    
    def __init__(self, model_name: str = "all-MiniLM-L6-v2", threshold: float = 0.85):
        self.threshold = threshold
        self.model = None
        self.model_name = model_name
        self._embeddings_cache: Dict[str, np.ndarray] = {}
        
        if HAS_SENTENCE_TRANSFORMERS:
            try:
                self.model = SentenceTransformer(model_name)
            except Exception:
                self.model = None
    
    def _get_embedding(self, text: str) -> Optional[np.ndarray]:
        """Get embedding for text with caching."""
        if text in self._embeddings_cache:
            return self._embeddings_cache[text]
        
        if self.model is None:
            return None
        
        try:
            embedding = self.model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
            self._embeddings_cache[text] = embedding
            return embedding
        except Exception:
            return None
    
    def similarity(self, text1: str, text2: str) -> float:
        """Compute cosine similarity between two texts."""
        emb1 = self._get_embedding(text1)
        emb2 = self._get_embedding(text2)
        
        if emb1 is None or emb2 is None:
            return 0.0
        
        return float(np.dot(emb1, emb2))
    
    def is_duplicate(self, text1: str, text2: str) -> bool:
        """Check if two texts are semantic duplicates."""
        similarity = self.similarity(text1, text2)
        return similarity >= self.threshold
    
    def batch_check(self, texts: List[str], reference_texts: List[str]) -> List[List[Tuple[int, float]]]:
        """Batch check similarity against reference texts."""
        if self.model is None or not texts or not reference_texts:
            return [[] for _ in texts]
        
        try:
            # Encode all texts
            text_embeddings = self.model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
            ref_embeddings = self.model.encode(reference_texts, convert_to_numpy=True, normalize_embeddings=True)
            
            # Compute similarities
            similarities = np.dot(text_embeddings, ref_embeddings.T)
            
            results = []
            for i, sim_row in enumerate(similarities):
                matches = []
                for j, sim in enumerate(sim_row):
                    if sim >= self.threshold:
                        matches.append((j, float(sim)))
                results.append(matches)
            return results
        except Exception:
            return [[] for _ in texts]


class HybridDeduplicator:
    """Hybrid deduplicator combining Hash + SimHash + Embeddings."""
    
    def __init__(self, config: DedupConfig):
        self.config = config
        self.simhash = SimHash(config.simhash_fingerprint_size)
        self.embedding = EmbeddingDedup(config.embedding_model, config.embedding_threshold) if HAS_SENTENCE_TRANSFORMERS else None
        self.content_hasher = ContentHasher(config.content_hash_algorithm)
        self.url_normalizer = URLNormalizer(config)
        
        # Caches
        self._simhash_cache: Dict[str, int] = {}
        self._embedding_cache: Dict[str, np.ndarray] = {}
        self._content_hash_cache: Dict[str, str] = {}
        
        # Statistics
        self.stats = {
            "exact_matches": 0,
            "simhash_matches": 0,
            "embedding_matches": 0,
            "total_checked": 0,
        }
    
    def _get_content_key(self, content: str) -> str:
        """Get content hash key."""
        return self.content_hasher.hash(content)
    
    def _get_simhash(self, content: str) -> int:
        """Get SimHash for content with caching."""
        if content in self._simhash_cache:
            return self._simhash_cache[content]
        
        fp = self.simhash.compute(content)
        self._simhash_cache[content] = fp
        return fp
    
    def _get_embedding(self, content: str) -> Optional[np.ndarray]:
        """Get embedding with caching."""
        if self.embedding is None:
            return None
        
        if content in self._embedding_cache:
            return self._embedding_cache[content]
        
        emb = self.embedding._get_embedding(content)
        if emb is not None:
            self._embedding_cache[content] = emb
        return emb
    
    def is_duplicate(self, content: str, url: str = "") -> Tuple[bool, str]:
        """
        Check if content is a duplicate using hybrid approach.
        Returns (is_duplicate, match_type).
        """
        self.stats["total_checked"] += 1
        
        # 1. Exact content hash match (fastest)
        content_hash = self._get_content_key(content)
        if self._exact_match(content):
            self.stats["exact_matches"] += 1
            return True, "exact"
        
        # 2. SimHash near-duplicate detection
        if self.config.simhash_weight > 0:
            simhash_fp = self._get_simhash(content)
            if self._simhash_match(content):
                self.stats["simhash_matches"] += 1
                return True, "simhash"
        
        # 3. Embedding-based semantic similarity
        if self.config.embedding_weight > 0 and self.embedding is not None:
            if self._embedding_match(content):
                self.stats["embedding_matches"] += 1
                return True, "embedding"
        
        return False, "none"
    
    def _exact_match(self, content: str) -> bool:
        """Check exact content match."""
        content_hash = self._get_content_key(content)
        # In a real implementation, check against stored hashes
        # For now, return False to allow other methods
        return False
    
    def _simhash_match(self, content: str) -> bool:
        """Check for near-duplicate using SimHash."""
        if self.config.simhash_weight <= 0:
            return False
        
        fp = self._get_simhash(content)
        # In a real implementation, compare against stored fingerprints
        # For now, return False
        return False
    
    def _embedding_match(self, content: str) -> bool:
        """Check for semantic similarity using embeddings."""
        if self.embedding is None or self.config.embedding_weight <= 0:
            return False
        
        # In a real implementation, compare against stored embeddings
        # For now, return False
        return False
    
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        total = self.stats["total_checked"]
        if total == 0:
            return self.stats
        return {
            **self.stats,
            "exact_match_rate": self.stats["exact_matches"] / total,
            "simhash_match_rate": self.stats["simhash_matches"] / total,
            "embedding_match_rate": self.stats["embedding_matches"] / total,
        }


class SemanticDeduplicationManager:
    """High-level semantic deduplication manager."""
    
    def __init__(self, config: Optional[DedupConfig] = None):
        self.config = config or DedupConfig()
        self.deduplicator = HybridDeduplicator(self.config)
        self._url_cache: Set[str] = set()
        self._content_hashes: Set[str] = set()
        self._simhash_fingerprints: List[int] = []
        self._embeddings: List[np.ndarray] = []
        self._content_store: List[str] = []
        
        # Statistics
        self.stats = {
            "checked": 0,
            "exact_duplicates": 0,
            "near_duplicates": 0,
            "semantic_duplicates": 0,
            "added": 0,
        }
    
    def is_duplicate(self, url: str, content: str) -> Tuple[bool, str]:
        """Check if URL/content is a duplicate."""
        self.stats["checked"] += 1
        
        # Normalize URL
        normalized_url = self._normalize_url(url)
        if normalized_url in self._url_cache:
            self.stats["exact_duplicates"] += 1
            return True, "exact_url"
        
        # Check content
        is_dup, match_type = self.deduplicator.is_duplicate(content)
        if is_dup:
            if match_type == "exact":
                self.stats["exact_duplicates"] += 1
            elif match_type == "simhash":
                self.stats["near_duplicates"] += 1
            elif match_type == "embedding":
                self.stats["semantic_duplicates"] += 1
            return True, match_type
        
        # Not a duplicate - store for future checks
        self._store_content(url, content)
        self.stats["added"] += 1
        return False, "none"
    
    def _normalize_url(self, url: str) -> str:
        """Normalize URL for comparison."""
        if not url:
            return ""
        parsed = urlparse(url)
        # Remove fragment
        normalized = urlparse(url)._replace(fragment="").geturl()
        # Normalize scheme
        normalized = normalized.replace("http://", "https://")
        # Remove www
        normalized = normalized.replace("https://www.", "https://")
        # Remove trailing slash
        normalized = normalized.rstrip('/')
        return normalized
    
    def _store_content(self, url: str, content: str):
        """Store content for future duplicate checks."""
        normalized_url = self._normalize_url(url)
        self._url_cache.add(normalized_url)
        
        content_hash = hashlib.sha256(content.encode()).hexdigest()
        self._content_hashes.add(content_hash)
        
        # Store SimHash
        simhash = SimHash(64).compute(content)
        self._simhash_fingerprints.append(simhash)
        
        # Store embedding (if available)
        # In real implementation, would store embedding vector
        
        # Store content for embedding comparison
        self._content_store.append(content)
        
        # Limit cache sizes
        max_cache = 10000
        if len(self._url_cache) > max_cache:
            self._url_cache = set(list(self._url_cache)[-max_cache:])
        if len(self._content_hashes) > max_cache:
            self._content_hashes = set(list(self._content_hashes)[-max_cache:])
        if len(self._simhash_fingerprints) > max_cache:
            self._simhash_fingerprints = self._simhash_fingerprints[-max_cache:]
        if len(self._content_store) > max_cache:
            self._content_store = self._content_store[-max_cache:]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get deduplication statistics."""
        total = self.stats["checked"]
        return {
            **self.stats,
            "exact_dup_rate": self.stats["exact_duplicates"] / max(1, self.stats["checked"]),
            "near_dup_rate": self.stats["near_duplicates"] / max(1, self.stats["checked"]),
            "semantic_dup_rate": self.stats["semantic_duplicates"] / max(1, self.stats["checked"]),
            "cache_sizes": {
                "urls": len(self._url_cache),
                "content_hashes": len(self._content_hashes),
                "simhash_fingerprints": len(self._simhash_fingerprints),
                "content_store": len(self._content_store),
            }
        }
    
    def clear(self):
        """Clear all caches."""
        self._url_cache.clear()
        self._content_hashes.clear()
        self._simhash_fingerprints.clear()
        self._content_store.clear()
        self.stats = {
            "checked": 0,
            "exact_duplicates": 0,
            "near_duplicates": 0,
            "semantic_duplicates": 0,
            "added": 0,
        }


def create_dedup_manager(
    strategy: str = "hybrid",
    persistent: bool = True,
    storage_path: Optional[str] = None,
    ttl_days: int = 30,
    **kwargs
) -> SemanticDeduplicationManager:
    """Create a deduplication manager with the specified strategy."""
    config = DedupConfig(
        enabled=True,
        strategy=strategy,
        persistent_storage=persistent,
        storage_path=storage_path,
        ttl_days=ttl_days,
        **kwargs
    )
    return SemanticDeduplicationManager(config)