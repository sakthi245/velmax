"""LLM Response Cache for caching LLM responses to avoid redundant API calls."""

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Optional
from pathlib import Path


@dataclass
class CacheEntry:
    """Single cache entry."""
    key: str
    response: Any
    created_at: float = field(default_factory=time.time)
    tokens_used: int = 0
    cost_estimate: float = 0.0
    hit_count: int = 0


class LLMResponseCache:
    """Simple in-memory + disk cache for LLM responses."""
    
    def __init__(self, cache_dir: str = ".llm_cache", max_size_mb: int = 100, ttl_hours: int = 168):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(exist_ok=True)
        self.max_size_bytes = max_size_mb * 1024 * 1024
        self.ttl_seconds = ttl_hours * 3600
        self._memory_cache: Dict[str, CacheEntry] = {}
        self._load_from_disk()
    
    def _make_key(self, prompt: str, model: str, **kwargs) -> str:
        """Generate cache key from prompt and parameters."""
        content = f"{model}:{prompt}:{json.dumps(kwargs, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:32]
    
    def get(self, prompt: str, model: str, **kwargs) -> Optional[Any]:
        """Get cached response if available and not expired."""
        key = self._make_key(prompt, model, **kwargs)
        
        # Check memory cache first
        if key in self._memory_cache:
            entry = self._memory_cache[key]
            if time.time() - entry.created_at < self.ttl_seconds:
                entry.hit_count += 1
                return entry.response
            else:
                del self._memory_cache[key]
        
        # Check disk cache
        cache_file = self.cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                if time.time() - data['created_at'] < self.ttl_seconds:
                    entry = CacheEntry(
                        key=key,
                        response=data['response'],
                        created_at=data['created_at'],
                        tokens_used=data.get('tokens_used', 0),
                        cost_estimate=data.get('cost_estimate', 0.0),
                        hit_count=data.get('hit_count', 0) + 1
                    )
                    self._memory_cache[key] = entry
                    return entry.response
                else:
                    cache_file.unlink()
            except Exception:
                pass
        
        return None
    
    def set(self, prompt: str, model: str, response: Any, **kwargs) -> None:
        """Cache a response."""
        key = self._make_key(prompt, model, **kwargs)
        entry = CacheEntry(
            key=key,
            response=response,
            tokens_used=kwargs.get('tokens_used', 0),
            cost_estimate=kwargs.get('cost_estimate', 0.0)
        )
        self._memory_cache[key] = entry
        
        # Persist to disk
        cache_file = self.cache_dir / f"{key}.json"
        try:
            with open(cache_file, 'w') as f:
                json.dump({
                    'key': key,
                    'response': response,
                    'created_at': entry.created_at,
                    'tokens_used': entry.tokens_used,
                    'cost_estimate': entry.cost_estimate,
                    'hit_count': entry.hit_count
                }, f)
        except Exception:
            pass
        
        # Check size limit
        self._enforce_size_limit()
    
    def _load_from_disk(self) -> None:
        """Load cache entries from disk on startup."""
        for cache_file in self.cache_dir.glob("*.json"):
            try:
                with open(cache_file, 'r') as f:
                    data = json.load(f)
                if time.time() - data['created_at'] < self.ttl_seconds:
                    entry = CacheEntry(
                        key=data['key'],
                        response=data['response'],
                        created_at=data['created_at'],
                        tokens_used=data.get('tokens_used', 0),
                        cost_estimate=data.get('cost_estimate', 0.0),
                        hit_count=data.get('hit_count', 0)
                    )
                    self._memory_cache[entry.key] = entry
                else:
                    cache_file.unlink()
            except Exception:
                pass
    
    def _enforce_size_limit(self) -> None:
        """Remove oldest entries if cache exceeds size limit."""
        total_size = sum(
            (self.cache_dir / f"{k}.json").stat().st_size 
            for k in self._memory_cache 
            if (self.cache_dir / f"{k}.json").exists()
        )
        
        if total_size > self.max_size_bytes:
            # Sort by hit count and age, remove least useful
            sorted_entries = sorted(
                self._memory_cache.items(),
                key=lambda x: (x[1].hit_count, x[1].created_at)
            )
            
            # Remove oldest 25%
            remove_count = len(sorted_entries) // 4
            for key, _ in sorted_entries[:remove_count]:
                cache_file = self.cache_dir / f"{key}.json"
                if cache_file.exists():
                    cache_file.unlink()
                del self._memory_cache[key]
    
    def clear(self) -> None:
        """Clear all cache entries."""
        self._memory_cache.clear()
        for cache_file in self.cache_dir.glob("*.json"):
            cache_file.unlink()
    
    def stats(self) -> Dict:
        """Get cache statistics."""
        return {
            "entries": len(self._memory_cache),
            "disk_size_mb": sum(
                f.stat().st_size for f in self.cache_dir.glob("*.json")
            ) / (1024 * 1024),
            "hit_rate": sum(e.hit_count for e in self._memory_cache.values()) / max(1, sum(1 for _ in self._memory_cache))
        }


# Global cache instance
_global_cache: Optional[LLMResponseCache] = None


def get_cache() -> LLMResponseCache:
    """Get or create global cache instance."""
    global _global_cache
    if _global_cache is None:
        _global_cache = LLMResponseCache()
    return _global_cache