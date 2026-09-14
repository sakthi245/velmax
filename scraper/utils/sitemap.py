from __future__ import annotations

import asyncio
import hashlib
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from xml.etree.ElementTree import ParseError

import httpx

from ..utils.observability import get_logger
from ..utils.http_cache import HTTPCache, HTTPCacheConfig


@dataclass
class SitemapConfig:
    enabled: bool = True
    max_urls: int = 10000
    max_depth: int = 3
    follow_sitemap_index: bool = True
    cache_enabled: bool = True
    cache_ttl: int = 86400
    timeout: float = 30.0
    user_agent: str = "HybridScraper/1.0 (+https://github.com/hybrid-scraper)"
    respect_lastmod: bool = True
    min_lastmod_days: Optional[int] = None


@dataclass
class SitemapEntry:
    url: str
    lastmod: Optional[datetime] = None
    changefreq: Optional[str] = None
    priority: Optional[float] = None
    images: List[Dict[str, str]] = field(default_factory=list)
    videos: List[Dict[str, str]] = field(default_factory=list)
    news: Optional[Dict[str, Any]] = None


class SitemapParser:
    """Async sitemap parser with caching and incremental updates."""

    def __init__(self, config: Optional[SitemapConfig] = None):
        self.config = config or SitemapConfig()
        self.logger = get_logger("sitemap")
        self._cache: Optional[HTTPCache] = None
        self._client: Optional[httpx.AsyncClient] = None
        self._visited_sitemaps: Set[str] = set()

        if self.config.cache_enabled:
            cache_config = HTTPCacheConfig(
                ttl=self.config.cache_ttl,
                max_size=100_000_000,
            )
            self._cache = HTTPCache(cache_config)

    async def __aenter__(self):
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout),
            headers={"User-Agent": self.config.user_agent},
            follow_redirects=True,
        )
        if self._cache:
            await self._cache.initialize()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._client:
            await self._client.aclose()
        if self._cache:
            await self._cache.close()

    async def parse(self, sitemap_url: str) -> AsyncIterator[SitemapEntry]:
        """Parse sitemap and yield entries."""
        if sitemap_url in self._visited_sitemaps:
            return

        self._visited_sitemaps.add(sitemap_url)

        # Check cache first
        if self._cache:
            cached = await self._cache.get(f"sitemap:{sitemap_url}")
            if cached:
                self.logger.debug("Using cached sitemap", url=sitemap_url)
                content = cached["content"]
            else:
                content = await self._fetch_sitemap(sitemap_url)
                if content:
                    await self._cache.set(f"sitemap:{sitemap_url}", {
                        "url": sitemap_url,
                        "content": content,
                        "fetched_at": datetime.utcnow().isoformat(),
                    })
        else:
            content = await self._fetch_sitemap(sitemap_url)

        if not content:
            return

        # Parse content
        try:
            root = ET.fromstring(content)
        except ParseError as e:
            self.logger.error("Failed to parse sitemap XML", url=sitemap_url, error=str(e))
            return

        # Check if it's a sitemap index
        if self._is_sitemap_index(root):
            if self.config.follow_sitemap_index:
                async for entry in self._parse_sitemap_index(root, sitemap_url):
                    yield entry
        else:
            async for entry in self._parse_urlset(root):
                yield entry

    async def _fetch_sitemap(self, url: str) -> Optional[bytes]:
        """Fetch sitemap content."""
        try:
            response = await self._client.get(url)
            if response.status_code == 200:
                return response.content
            self.logger.warning("Failed to fetch sitemap", url=url, status=response.status_code)
        except Exception as e:
            self.logger.error("Error fetching sitemap", url=url, error=str(e))
        return None

    def _is_sitemap_index(self, root: ET.Element) -> bool:
        """Check if root is a sitemap index."""
        return root.tag.endswith("}sitemapindex") or root.tag == "sitemapindex"

    async def _parse_sitemap_index(
        self,
        root: ET.Element,
        base_url: str
    ) -> AsyncIterator[SitemapEntry]:
        """Parse sitemap index and recursively parse child sitemaps."""
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        sitemaps = root.findall(".//sm:sitemap", namespace) or root.findall(".//sitemap")

        for sitemap in sitemaps:
            loc_elem = sitemap.find("sm:loc", namespace) or sitemap.find("loc")
            if loc_elem is None or not loc_elem.text:
                continue

            child_url = urljoin(base_url, loc_elem.text.strip())

            # Check lastmod if available
            lastmod_elem = sitemap.find("sm:lastmod", namespace) or sitemap.find("lastmod")
            if lastmod_elem is not None and lastmod_elem.text:
                try:
                    lastmod = datetime.fromisoformat(lastmod_elem.text.replace("Z", "+00:00"))
                    if self.config.min_lastmod_days:
                        if datetime.utcnow() - lastmod > timedelta(days=self.config.min_lastmod_days):
                            continue
                except ValueError:
                    pass

            if len(self._visited_sitemaps) >= self.config.max_depth:
                break

            async for entry in self.parse(child_url):
                yield entry

    async def _parse_urlset(self, root: ET.Element) -> AsyncIterator[SitemapEntry]:
        """Parse URL set from sitemap."""
        namespace = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

        urls = root.findall(".//sm:url", namespace) or root.findall(".//url")

        count = 0
        for url_elem in urls:
            if count >= self.config.max_urls:
                break

            loc_elem = url_elem.find("sm:loc", namespace) or url_elem.find("loc")
            if loc_elem is None or not loc_elem.text:
                continue

            url = loc_elem.text.strip()

            # Parse optional fields
            lastmod = None
            lastmod_elem = url_elem.find("sm:lastmod", namespace) or url_elem.find("lastmod")
            if lastmod_elem is not None and lastmod_elem.text:
                try:
                    lastmod = datetime.fromisoformat(lastmod_elem.text.replace("Z", "+00:00"))
                except ValueError:
                    pass

            changefreq = None
            cf_elem = url_elem.find("sm:changefreq", namespace) or url_elem.find("changefreq")
            if cf_elem is not None and cf_elem.text:
                changefreq = cf_elem.text.strip()

            priority = None
            pr_elem = url_elem.find("sm:priority", namespace) or url_elem.find("priority")
            if pr_elem is not None and pr_elem.text:
                try:
                    priority = float(pr_elem.text.strip())
                except ValueError:
                    pass

            # Parse images
            images = []
            for img in url_elem.findall(".//sm:image", namespace):
                img_loc = img.find("sm:loc", namespace) or img.find("loc")
                if img_loc is not None and img_loc.text:
                    images.append({"loc": img_loc.text.strip()})

            # Parse videos
            videos = []
            for vid in url_elem.findall(".//sm:video", namespace):
                vid_loc = vid.find("sm:loc", namespace) or vid.find("loc")
                if vid_loc is not None and vid_loc.text:
                    videos.append({"loc": vid_loc.text.strip()})

            # Filter by lastmod if configured
            if lastmod and self.config.min_lastmod_days:
                if datetime.utcnow() - lastmod > timedelta(days=self.config.min_lastmod_days):
                    continue

            yield SitemapEntry(
                url=url,
                lastmod=lastmod,
                changefreq=changefreq,
                priority=priority,
                images=images,
                videos=videos,
            )
            count += 1

    async def discover_sitemaps(self, base_url: str) -> List[str]:
        """Discover sitemaps from robots.txt and common locations."""
        parsed = urlparse(base_url)
        base = f"{parsed.scheme}://{parsed.netloc}"

        sitemap_urls = []

        # Check robots.txt
        robots_sitemaps = await self._get_sitemaps_from_robots(base)
        sitemap_urls.extend(robots_sitemaps)

        # Common sitemap locations
        common_paths = [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemaps.xml",
            "/sitemap/sitemap.xml",
        ]

        for path in common_paths:
            url = urljoin(base, path)
            if url not in sitemap_urls:
                sitemap_urls.append(url)

        # Validate each sitemap
        valid_sitemaps = []
        for url in sitemap_urls:
            try:
                response = await self._client.head(url, timeout=10.0)
                if response.status_code == 200:
                    valid_sitemaps.append(url)
            except Exception:
                pass

        return valid_sitemaps

    async def _get_sitemaps_from_robots(self, base_url: str) -> List[str]:
        """Extract sitemap URLs from robots.txt."""
        robots_url = urljoin(base_url, "/robots.txt")
        sitemaps = []

        try:
            response = await self._client.get(robots_url, timeout=10.0)
            if response.status_code == 200:
                for line in response.text.splitlines():
                    line = line.strip()
                    if line.lower().startswith("sitemap:"):
                        sitemap_url = line.split(":", 1)[1].strip()
                        sitemaps.append(sitemap_url)
        except Exception:
            pass

        return sitemaps


class RobotsParser:
    """Async robots.txt parser with caching."""

    def __init__(self, config: Optional[SitemapConfig] = None):
        self.config = config or SitemapConfig()
        self.logger = get_logger("robots")
        self._cache: Dict[str, Any] = {}
        self._cache_times: Dict[str, float] = {}
        self._cache_ttl = self.config.cache_ttl

    async def can_fetch(self, url: str, user_agent: str = None) -> bool:
        """Check if URL can be fetched according to robots.txt."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        rp = await self._get_robots_parser(base_url)
        if rp is None:
            return True

        ua = user_agent or self.config.user_agent
        return rp.can_fetch(ua, url)

    async def get_crawl_delay(self, url: str, user_agent: str = None) -> Optional[float]:
        """Get crawl delay for user agent."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        rp = await self._get_robots_parser(base_url)
        if rp is None:
            return None

        ua = user_agent or self.config.user_agent
        delay = rp.crawl_delay(ua)
        return float(delay) if delay else None

    async def get_sitemaps(self, url: str) -> List[str]:
        """Get sitemap URLs from robots.txt."""
        parsed = urlparse(url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        rp = await self._get_robots_parser(base_url)
        if rp is None:
            return []

        return rp.sitemaps() or []

    async def _get_robots_parser(self, base_url: str):
        """Get or create robots.txt parser for domain."""
        now = time.time()

        # Check cache
        if base_url in self._cache:
            if now - self._cache_times.get(base_url, 0) < self._cache_ttl:
                return self._cache[base_url]

        # Fetch robots.txt
        robots_url = urljoin(base_url, "/robots.txt")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(robots_url, headers={"User-Agent": self.config.user_agent})
                if response.status_code == 200:
                    from urllib.robotparser import RobotFileParser
                    rp = RobotFileParser()
                    rp.parse(response.text.splitlines())
                    self._cache[base_url] = rp
                    self._cache_times[base_url] = time.time()
                    return rp
        except Exception as e:
            self.logger.debug("Failed to fetch robots.txt", url=robots_url, error=str(e))

        return None


async def parse_sitemap(sitemap_url: str, config: Optional[SitemapConfig] = None) -> List[SitemapEntry]:
    """Convenience function to parse sitemap and return all entries."""
    entries = []
    async with SitemapParser(config) as parser:
        async for entry in parser.parse(sitemap_url):
            entries.append(entry)
    return entries


async def discover_sitemaps(base_url: str, config: Optional[SitemapConfig] = None) -> List[str]:
    """Discover all sitemaps for a domain."""
    async with SitemapParser(config) as parser:
        return await parser.discover_sitemaps(base_url)


async def check_robots(url: str, user_agent: str = None, config: Optional[SitemapConfig] = None) -> bool:
    """Quick robots.txt check."""
    async with SitemapParser(config) as parser:
        return await parser.can_fetch(url, user_agent)


async def get_crawl_delay(url: str, user_agent: str = None, config: Optional[SitemapConfig] = None) -> Optional[float]:
    """Get crawl delay from robots.txt."""
    async with SitemapParser(config) as parser:
        return await parser.get_crawl_delay(url, user_agent)