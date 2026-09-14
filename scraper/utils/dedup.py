from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse
import xxhash


@dataclass
class DedupConfig:
    enabled: bool = True
    strategy: str = "url_content"
    url_normalize: bool = True
    content_hash_algorithm: str = "xxhash"
    bloom_filter_size: int = 1_000_000
    bloom_filter_fp_rate: float = 0.01
    persistent_storage: bool = True
    storage_path: Optional[Path] = None
    ttl_days: int = 30
    strip_query_params: List[str] = field(default_factory=lambda: ["utm_*", "fbclid", "gclid", "ref", "source", "medium", "campaign"])
    canonicalize_urls: bool = True
    case_sensitive: bool = False


class BloomFilter:
    def __init__(self, size: int = 1_000_000, fp_rate: float = 0.01):
        import math
        self.size = size
        self.fp_rate = fp_rate
        self.hash_count = max(1, int(-math.log(fp_rate) / math.log(2)))
        self.bit_array = bytearray((size + 7) // 8)

    def _hash(self, item: str, seed: int) -> int:
        if isinstance(item, str):
            item = item.encode('utf-8')
        return xxhash.xxh64(item, seed=seed).intdigest() % self.size

    def add(self, item: str) -> None:
        for i in range(self.hash_count):
            idx = self._hash(item, i)
            self.bit_array[idx // 8] |= 1 << (idx % 8)

    def __contains__(self, item: str) -> bool:
        for i in range(self.hash_count):
            idx = self._hash(item, i)
            if not (self.bit_array[idx // 8] & (1 << (idx % 8))):
                return False
        return True

    def clear(self) -> None:
        self.bit_array = bytearray((self.size + 7) // 8)


class URLNormalizer:
    def __init__(self, config: DedupConfig):
        self.config = config

    def normalize(self, url: str) -> str:
        if not url:
            return url

        parsed = urlparse(url)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()

        if not self.config.case_sensitive:
            path = parsed.path.lower()
        else:
            path = parsed.path

        if self.config.strip_query_params:
            params = parse_qsl(parsed.query, keep_blank_values=True)
            filtered = []
            for k, v in params:
                should_strip = False
                for pattern in self.config.strip_query_params:
                    if pattern.endswith("*"):
                        if k.startswith(pattern[:-1]):
                            should_strip = True
                            break
                    elif k == pattern:
                        should_strip = True
                        break
                if not should_strip:
                    filtered.append((k, v))
            query = urlencode(filtered)
        else:
            query = parsed.query

        fragment = ""
        if not self.config.canonicalize_urls:
            fragment = parsed.fragment

        return urlunparse((scheme, netloc, path, "", query, fragment))


class ContentHasher:
    def __init__(self, algorithm: str = "xxhash"):
        self.algorithm = algorithm.lower()

    def hash(self, content: Union[str, bytes]) -> str:
        if isinstance(content, str):
            content = content.encode("utf-8")

        if self.algorithm == "xxhash":
            return xxhash.xxh64(content).hexdigest()
        elif self.algorithm == "md5":
            return hashlib.md5(content).hexdigest()
        elif self.algorithm == "sha256":
            return hashlib.sha256(content).hexdigest()
        else:
            return xxhash.xxh64(content).hexdigest()

    def hash_dict(self, data: Dict[str, Any]) -> str:
        serialized = json.dumps(data, sort_keys=True, separators=(",", ":"))
        return self.hash(serialized)


class DeduplicationStore:
    def __init__(self, config: DedupConfig):
        self.config = config
        self.normalizer = URLNormalizer(config)
        self.hasher = ContentHasher(config.content_hash_algorithm)
        self.bloom_filter = BloomFilter(config.bloom_filter_size, config.bloom_filter_fp_rate)
        self._lock = threading.RLock()

        self._memory_cache: Dict[str, float] = {}
        self._db_conn: Optional[sqlite3.Connection] = None

        if config.persistent_storage:
            self._init_db()

    def _init_db(self):
        db_path = self.config.storage_path or Path("./data/dedup.db")
        db_path.parent.mkdir(parents=True, exist_ok=True)

        self._db_conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._db_conn.execute("""
            CREATE TABLE IF NOT EXISTS seen_urls (
                hash TEXT PRIMARY KEY,
                url TEXT NOT NULL,
                content_hash TEXT,
                created_at REAL NOT NULL,
                last_seen REAL NOT NULL,
                hit_count INTEGER DEFAULT 1
            )
        """)
        self._db_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_url ON seen_urls(url)
        """)
        self._db_conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_created ON seen_urls(created_at)
        """)
        self._db_conn.commit()

        self._load_bloom_filter()

    def _load_bloom_filter(self):
        if not self._db_conn:
            return
        cursor = self._db_conn.execute("SELECT hash FROM seen_urls")
        for row in cursor:
            self.bloom_filter.add(row[0])

    def _cleanup_expired(self):
        if not self._db_conn:
            return
        cutoff = time.time() - (self.config.ttl_days * 86400)
        self._db_conn.execute("DELETE FROM seen_urls WHERE created_at < ?", (cutoff,))
        self._db_conn.commit()

        self.bloom_filter = BloomFilter(self.config.bloom_filter_size, self.config.bloom_filter_fp_rate)
        self._load_bloom_filter()

    def check_url(self, url: str) -> bool:
        if not self.config.enabled:
            return False

        normalized = self.normalizer.normalize(url)
        url_hash = self.hasher.hash(normalized)

        with self._lock:
            if url_hash in self.bloom_filter:
                if self._check_db(url_hash):
                    return True
                return False
            return False

    def _check_db(self, url_hash: str) -> bool:
        if not self._db_conn:
            return url_hash in self._memory_cache

        cursor = self._db_conn.execute(
            "SELECT 1 FROM seen_urls WHERE hash = ?", (url_hash,)
        )
        return cursor.fetchone() is not None

    def add_url(self, url: str, content: Optional[str] = None) -> bool:
        if not self.config.enabled:
            return False

        normalized = self.normalizer.normalize(url)
        url_hash = self.hasher.hash(normalized)

        content_hash = None
        if content:
            content_hash = self.hasher.hash(content)

        with self._lock:
            if url_hash in self.bloom_filter:
                if self._check_db(url_hash):
                    self._update_hit_count(url_hash)
                    return False

            self.bloom_filter.add(url_hash)

            now = time.time()
            if self._db_conn:
                self._db_conn.execute(
                    """
                    INSERT OR REPLACE INTO seen_urls (hash, url, content_hash, created_at, last_seen, hit_count)
                    VALUES (?, ?, ?, ?, ?, COALESCE((SELECT hit_count FROM seen_urls WHERE hash = ?), 0) + 1)
                    """,
                    (url_hash, normalized, content_hash, now, now, url_hash)
                )
                self._db_conn.commit()
            else:
                self._memory_cache[url_hash] = now

        return True

    def add_content(self, content: str) -> bool:
        if not self.config.enabled:
            return False

        content_hash = self.hasher.hash(content)

        with self._lock:
            if content_hash in self.bloom_filter:
                return False

            self.bloom_filter.add(content_hash)
            return True

    def check_content(self, content: str) -> bool:
        if not self.config.enabled:
            return False

        content_hash = self.hasher.hash(content)
        return content_hash in self.bloom_filter

    def _update_hit_count(self, url_hash: str):
        if not self._db_conn:
            return
        now = time.time()
        self._db_conn.execute(
            "UPDATE seen_urls SET last_seen = ?, hit_count = hit_count + 1 WHERE hash = ?",
            (now, url_hash)
        )
        self._db_conn.commit()

    def is_duplicate(self, url: str, content: Optional[str] = None) -> bool:
        if self.config.strategy == "url":
            return self.check_url(url)
        elif self.config.strategy == "content":
            if content:
                return self.check_content(content)
            return False
        elif self.config.strategy == "url_content":
            if self.check_url(url):
                return True
            if content and self.check_content(content):
                return True
            return False
        else:
            return self.check_url(url)

    def mark_seen(self, url: str, content: Optional[str] = None) -> bool:
        if self.config.strategy == "url":
            return self.add_url(url)
        elif self.config.strategy == "content":
            if content:
                return self.add_content(content)
            return False
        elif self.config.strategy == "url_content":
            url_added = self.add_url(url)
            content_added = False
            if content:
                content_added = self.add_content(content)
            return url_added or content_added
        else:
            return self.add_url(url)

    def get_stats(self) -> Dict[str, Any]:
        stats = {
            "bloom_filter_size": self.config.bloom_filter_size,
            "bloom_filter_fp_rate": self.config.bloom_filter_fp_rate,
            "strategy": self.config.strategy,
        }

        if self._db_conn:
            cursor = self._db_conn.execute("SELECT COUNT(*) FROM seen_urls")
            stats["db_count"] = cursor.fetchone()[0]

            cursor = self._db_conn.execute("SELECT SUM(hit_count) FROM seen_urls")
            stats["total_hits"] = cursor.fetchone()[0] or 0
        else:
            stats["memory_count"] = len(self._memory_cache)

        return stats

    def clear(self):
        with self._lock:
            self.bloom_filter.clear()
            if self._db_conn:
                self._db_conn.execute("DELETE FROM seen_urls")
                self._db_conn.commit()
            else:
                self._memory_cache.clear()

    def close(self):
        if self._db_conn:
            self._db_conn.close()
            self._db_conn = None


class DeduplicationManager:
    def __init__(self, config: Optional[DedupConfig] = None):
        self.config = config or DedupConfig()
        self.store = DeduplicationStore(self.config)
        self._stats = {
            "checked": 0,
            "duplicates": 0,
            "added": 0,
        }

    def is_duplicate(self, url: str, content: Optional[str] = None) -> bool:
        self._stats["checked"] += 1
        result = self.store.is_duplicate(url, content)
        if result:
            self._stats["duplicates"] += 1
        return result

    def mark_seen(self, url: str, content: Optional[str] = None) -> bool:
        result = self.store.mark_seen(url, content)
        if result:
            self._stats["added"] += 1
        return result

    def check_and_mark(self, url: str, content: Optional[str] = None) -> Tuple[bool, bool]:
        is_dup = self.is_duplicate(url, content)
        if not is_dup:
            self.mark_seen(url, content)
        return is_dup, not is_dup

    def get_stats(self) -> Dict[str, Any]:
        store_stats = self.store.get_stats()
        return {
            **store_stats,
            **self._stats,
            "duplicate_rate": self._stats["duplicates"] / max(1, self._stats["checked"]),
        }

    def reset_stats(self):
        self._stats = {"checked": 0, "duplicates": 0, "added": 0}

    def clear(self):
        self.store.clear()
        self.reset_stats()

    def close(self):
        self.store.close()


def create_dedup_manager(
    strategy: str = "url_content",
    persistent: bool = True,
    storage_path: Optional[Path] = None,
    ttl_days: int = 30,
    **kwargs
) -> DeduplicationManager:
    config = DedupConfig(
        strategy=strategy,
        persistent_storage=persistent,
        storage_path=storage_path,
        ttl_days=ttl_days,
        **kwargs
    )
    return DeduplicationManager(config)