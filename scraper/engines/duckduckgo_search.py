from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, AsyncIterator, Dict, List, Optional
from urllib.parse import urlparse, urljoin, parse_qs, unquote

import httpx
from selectolax.parser import HTMLParser

from ..config.schemas import EngineType, EngineCapability
from .interfaces import EngineConfig, EngineMetadata
from .base import BaseEngine, ScrapeRequest, ScrapeResponse

LOG = logging.getLogger(__name__)


@dataclass
class DuckDuckGoSearchConfig:
    base_url: str = "https://html.duckduckgo.com/html/"
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    rate_limit_delay: float = 1.0
    max_results_per_query: int = 10
    request_timeout: float = 30.0
    max_retries: int = 3
    backoff_factor: float = 2.0
    verify_ssl: bool = True


@dataclass
class SearchResult:
    url: str
    title: str = ""
    snippet: str = ""
    position: int = 0
    source: str = "duckduckgo"
    timestamp: datetime = field(default_factory=datetime.utcnow)


class DuckDuckGoSearchEngine:
    metadata = {
        "name": "duckduckgo_search",
        "engine_type": "api",
        "capabilities": ["rest_api"],
        "max_concurrent": 3,
        "avg_latency_ms": 3000,
        "requires_external_service": False,
        "cost_per_1k_pages": 0.0,
    }

    def __init__(self):
        self.config = DuckDuckGoSearchConfig()
        self._client = None
        self._last_request_time = 0.0
        self._request_lock = None
        self._initialized = False

    async def initialize(self, config):
        self.config = DuckDuckGoSearchConfig(**config.config.get("duckduckgo_search", {}))
        import httpx
        self._client = httpx.AsyncClient(
            headers={"User-Agent": self.config.user_agent},
            timeout=httpx.Timeout(self.config.request_timeout),
            follow_redirects=True,
            verify=self.config.verify_ssl,
        )
        self._request_lock = asyncio.Lock()
        self._last_request_time = 0.0
        self._initialized = True
        import logging
        logging.getLogger(__name__).info("DuckDuckGo search engine initialized")

    async def shutdown(self):
        if self._client:
            await self._client.aclose()
            self._client = None

    def health_check(self):
        return self._client is not None and not self._client.is_closed

    async def scrape(self, request):
        if not self._initialized:
            raise RuntimeError("DuckDuckGo search engine not initialized")

        query = request.goal or request.url
        results = await self.search(request.goal or request.url, max_results=10)

        if results:
            first = results[0]
            content = f"{first.title}\n{first.snippet}\n{first.url}"
            from scraper.engines.base import ScrapeResponse
            return ScrapeResponse(
                url=first.url,
                success=True,
                data={
                    "results": [
                        {
                            "url": r.url,
                            "title": r.title,
                            "snippet": r.snippet,
                            "position": r.position,
                        } for r in results
                    ]
                },
                markdown=content,
                html="",
                metadata={
                    "title": first.title,
                    "source": "duckduckgo",
                    "total_results": len(results),
                },
                engine="duckduckgo_search",
                latency_ms=0,
            )
        else:
            from scraper.engines.base import ScrapeResponse
            return ScrapeResponse(
                url=request.url,
                success=False,
                data={},
                markdown=None,
                html=None,
                metadata={},
                engine="duckduckgo_search",
                error="No results found",
                latency_ms=0,
            )

    async def crawl(self, urls, config):
        for url in urls:
            from scraper.engines.base import ScrapeRequest
            request = type("ScrapeRequest", (), {"url": url, "goal": config.get("goal", "")})()
            yield await self.scrape(request)

    async def _rate_limit(self):
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()

    def _parse_results(self, html, query):
        from selectolax.parser import HTMLParser
        from urllib.parse import urlparse
        from dataclasses import dataclass

        results = []
        try:
            tree = HTMLParser(html)
            result_elements = tree.css("a.result__snippet, .result__url, .result__title, .web-result, .result")

            if not result_elements:
                result_elements = tree.css(".results .result, .web-result, .result-link")

            seen_urls = set()

            for elem in result_elements:
                try:
                    url = elem.attributes.get("href", "")
                    if not url:
                        continue

                    # Handle DuckDuckGo redirect URLs
                    if "duckduckgo.com/l/" in url and "uddg=" in url:
                        # Extract the actual URL from the uddg parameter
                        parsed_redirect = urlparse(url)
                        query_params = parse_qs(parsed_redirect.query)
                        if "uddg" in query_params:
                            url = unquote(query_params["uddg"][0])
                        else:
                            continue

                    if url.startswith("//"):
                        url = "https:" + url
                    elif url.startswith("/"):
                        url = "https://duckduckgo.com" + url

                    parsed = urlparse(url)
                    if parsed.scheme not in ("http", "https"):
                        continue
                    if parsed.netloc in ("duckduckgo.com", "duckduckgo.com"):
                        continue

                    if url in seen_urls:
                        continue
                    seen_urls.add(url)

                    title_elem = elem.css_first("h2, .result__title, .result-title, h3, .title")
                    title = title_elem.text(strip=True) if title_elem else ""

                    snippet_elem = elem.css_first(".result__snippet, .snippet, .description, .result-text")
                    snippet = snippet_elem.text(strip=True) if snippet_elem else ""

                    if not title and not snippet:
                        text = elem.text(strip=True)
                        if text:
                            snippet = text[:300]

                    if url and (title or snippet):
                        @dataclass
                        class SearchResult:
                            url: str
                            title: str = ""
                            snippet: str = ""
                            position: int = 0
                            source: str = "duckduckgo"
                            timestamp: datetime = None
                        results.append(type("SearchResult", (), {
                            "url": url,
                            "title": title[:200],
                            "snippet": snippet[:500],
                            "position": len(results),
                            "source": "duckduckgo",
                            "timestamp": datetime.utcnow(),
                        })())

                except Exception:
                    continue

        except Exception as e:
            LOG.warning(f"Failed to parse DuckDuckGo results: {e}")
            return results

        return results

    async def search(self, query, max_results=10, region="us-en", safe_search=True):
        if not self._initialized:
            raise RuntimeError("DuckDuckGo search engine not initialized")

        await self._rate_limit()

        params = {"q": query, "kl": region, "kp": "1" if safe_search else "-1"}

        headers = {
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Accept-Encoding": "gzip, deflate",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }

        import httpx
        for attempt in range(self.config.max_retries + 1):
            try:
                await self._rate_limit()

                response = await httpx.AsyncClient(
                    headers={"User-Agent": self.config.user_agent},
                    timeout=httpx.Timeout(self.config.request_timeout),
                    follow_redirects=True,
                    verify=self.config.verify_ssl,
                ).get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query, "kl": region, "kp": "1" if safe_search else "-1"},
                    headers=headers,
                    timeout=self.config.request_timeout,
                    follow_redirects=True,
                )

                response.raise_for_status()
                results = self._parse_results(response.text, query)
                return results[:max_results]

            except Exception as e:
                import logging
                logging.getLogger(__name__).warning(f"Error searching for '{query}' (attempt {attempt + 1}): {e}")
                if attempt < self.config.max_retries:
                    await asyncio.sleep(self.config.backoff_factor ** attempt)
                    continue
                raise

        return []

    async def search_multiple(self, queries, max_results_per_query=10, delay_between_queries=1.0):
        results = {}
        for i, query in enumerate(queries):
            if i > 0:
                await asyncio.sleep(delay_between_queries)
            try:
                results[query] = await self.search(query, max_results=max_results_per_query)
            except Exception as e:
                import logging
                logging.getLogger(__name__).error(f"Failed to search for '{query}': {e}")
                results[query] = []
        return results

    async def _rate_limit(self):
        if self._request_lock is None:
            self._request_lock = asyncio.Lock()
        async with self._request_lock:
            elapsed = time.time() - self._last_request_time
            if elapsed < self.config.rate_limit_delay:
                await asyncio.sleep(self.config.rate_limit_delay - elapsed)
            self._last_request_time = time.time()


class DuckDuckGoSearchConfig:
    base_url = "https://html.duckduckgo.com/html/"
    user_agent = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    rate_limit_delay = 1.0
    max_results_per_query = 10
    request_timeout = 30.0
    max_retries = 3
    backoff_factor = 2.0
    verify_ssl = True

    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


DuckDuckGoSearchEngine.ConfigClass = DuckDuckGoSearchConfig
DuckDuckGoSearchEngine.__module__ = "scraper.engines.duckduckgo_search"