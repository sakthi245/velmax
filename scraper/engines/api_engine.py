from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Union
from urllib.parse import urlparse

import httpx

from .base_v2 import BaseAPIEngineV2
from .interfaces import (
    EngineConfig,
    EngineMetadata,
    APIEndpoint,
)
from .browser_engine import BrowserEngine
from ..utils.observability import get_logger, MetricsCollector
from ..utils.retry import RetryPolicy, create_retry_policy
from ..config.schemas import APIEngineConfig, EngineType, EngineCapability


@dataclass
class AuthConfig:
    method: str = "none"
    api_key: Optional[str] = None
    bearer_token: Optional[str] = None
    oauth_client_id: Optional[str] = None
    oauth_client_secret: Optional[str] = None
    oauth_token_url: Optional[str] = None
    cookie_jar: Dict[str, str] = field(default_factory=dict)
    custom_headers: Dict[str, str] = field(default_factory=dict)


@dataclass
class APIEndpointPattern:
    pattern: str
    method: Optional[str] = None
    auth: Optional[AuthConfig] = None
    response_schema: Optional[Dict[str, Any]] = None
    rate_limit: Optional[int] = None


@dataclass
class MockModeConfig:
    enabled: bool = False
    har_path: Optional[Path] = None
    record_mode: bool = False


class APIEngine(BaseAPIEngineV2):
    metadata = EngineMetadata(
        name="api",
        engine_type=EngineType.API,
        capabilities={
            EngineCapability.API_INTERCEPTION,
            EngineCapability.LARGE_CRAWL,
            EngineCapability.AUTH_FLOWS,
            EngineCapability.MOCK_MODE,
        },
        max_concurrent=16,
        avg_latency_ms=1000,
        requires_external_service=False,
        cost_per_1k_pages=0.0,
    )

    def __init__(
        self,
        rate_limit_config: Optional[Any] = None,
        retry_policy: Optional[Any] = None,
        session_manager: Optional[Any] = None,
        circuit_breaker_config: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(rate_limit_config, retry_policy, session_manager, circuit_breaker_config)
        self._engine_config = APIEngineConfig()
        self._client: Optional[Any] = None
        self._browser_engine: Optional[BrowserEngine] = None
        self._intercepted_endpoints: List[APIEndpoint] = []
        self._endpoint_patterns: List[APIEndpointPattern] = []
        self._auth_configs: Dict[str, AuthConfig] = {}
        self._mock_mode = MockModeConfig()
        self._mock_har_data: Optional[Dict] = None
        self._token_cache: Dict[str, Dict[str, Any]] = {}
        self._rate_limiters: Dict[str, Any] = {}

    async def _initialize_impl(self, config: EngineConfig) -> None:
        self._engine_config = APIEngineConfig(**config.config.get("api_engine", {}))

        # Initialize HTTP client for direct API calls
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
        )

        # Initialize browser engine for network interception
        if self._engine_config.intercept_network:
            browser_config = EngineConfig(
                name="api_browser",
                config={"browser_engine": config.config.get("browser_engine", {})},
            )
            self._browser_engine = BrowserEngine()
            await self._browser_engine.initialize(browser_config)

        # Parse endpoint patterns
        self._endpoint_patterns = [
            APIEndpointPattern(pattern=p)
            for p in self._engine_config.endpoint_patterns
        ]

        # Initialize mock mode
        if self._engine_config.mock_mode and self._engine_config.mock_har_path:
            await self._load_mock_har(self._engine_config.mock_har_path)

        self.logger.info("API engine initialized", intercept=self._engine_config.intercept_network)

    async def _shutdown_impl(self) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

        if self._browser_engine:
            await self._browser_engine.shutdown()
            self._browser_engine = None

    def _health_check_impl(self) -> bool:
        return True

    async def call(
        self,
        endpoint: APIEndpoint,
        auth: Optional[Dict[str, Any]] = None
    ) -> APIEndpoint:
        """Call an API endpoint with authentication."""
        if not self._initialized:
            raise RuntimeError(f"Engine {self.metadata.name} not initialized")

        # Mock mode: replay from HAR
        if self._mock_mode.enabled and self._mock_har_data:
            return await self._replay_from_har(endpoint)

        # Apply authentication
        headers = dict(endpoint.headers)
        if auth:
            await self._apply_auth(headers, auth)

        # Check rate limit
        domain = urlparse(endpoint.url).netloc
        if domain in self._rate_limiters:
            await self._rate_limiters[domain].acquire(domain)

        # Apply endpoint-specific auth
        matched_pattern = self._match_endpoint_pattern(endpoint.url)
        if matched_pattern and matched_pattern.auth:
            await self._apply_auth(headers, matched_pattern.auth.to_dict())

        # Execute request
        retryer = self._create_retryer()

        async def _call():
            response = await self._client.request(
                method=endpoint.method,
                url=endpoint.url,
                headers=headers,
                params=endpoint.request_body if endpoint.method == "GET" else None,
                json=endpoint.request_body if endpoint.method in ("POST", "PUT", "PATCH") else None,
            )

            # Update endpoint with response
            endpoint.response_status = response.status_code
            endpoint.response_headers = dict(response.headers)
            endpoint.timing["response_time"] = response.elapsed.total_seconds()

            content_type = response.headers.get("content-type", "")
            if "application/json" in content_type:
                endpoint.response_body = response.json()
            else:
                endpoint.response_body = response.text

            # Check rate limit headers
            self._update_rate_limit_from_headers(domain, response.headers)

            return endpoint

        return await self._execute_with_retry(_call)

    async def _apply_auth(self, headers: Dict[str, str], auth: Dict[str, Any]):
        """Apply authentication to headers."""
        method = auth.get("method", "none")

        if method == "bearer" and auth.get("access_token"):
            headers["Authorization"] = f"Bearer {auth['access_token']}"
        elif method == "api_key" and auth.get("api_key"):
            key_name = auth.get("header_name", "X-API-Key")
            headers[key_name] = auth["api_key"]
        elif method == "cookie" and auth.get("cookies"):
            cookie_header = "; ".join(f"{k}={v}" for k, v in auth["cookies"].items())
            headers["Cookie"] = cookie_header
        elif method == "custom" and auth.get("custom_headers"):
            headers.update(auth["custom_headers"])

    def _match_endpoint_pattern(self, url: str) -> Optional[Any]:
        """Match URL against endpoint patterns."""
        for pattern in self._endpoint_patterns:
            if re.search(pattern.pattern, url):
                return pattern
        return None

    async def discover_endpoints(self, url: str) -> List[APIEndpoint]:
        """Discover API endpoints by intercepting network traffic."""
        if not self._browser_engine:
            return []

        return await self.intercept_network(url, self._engine_config.rate_limit_per_endpoint * 1000)

    async def intercept_network(self, url: str, duration_ms: int) -> List[APIEndpoint]:
        """Intercept network traffic to discover API endpoints."""
        if not self._browser_engine:
            return []

        self._intercepted_endpoints = []

        # Set up CDP network interception
        context = await self._browser_engine._get_context()
        page = await context.new_page()

        intercepted = []

        def handle_request(request):
            # Filter for API-like requests
            if self._is_api_request(request):
                intercepted.append({
                    "url": request.url,
                    "method": request.method,
                    "headers": dict(request.headers),
                    "post_data": request.post_data,
                    "resource_type": request.resource_type,
                    "timestamp": time.time(),
                })

        def handle_response(response):
            # Match with request
            for req in intercepted:
                if req.get("url") == response.url and "response" not in req:
                    req["response"] = {
                        "status": response.status,
                        "headers": dict(response.headers),
                        "timestamp": time.time(),
                    }
                    break

        page.on("request", handle_request)
        page.on("response", handle_response)

        try:
            await page.goto(url, wait_until="networkidle", timeout=60000)
            await asyncio.sleep(duration_ms / 1000)

            # Convert to APIEndpoint objects
            for item in intercepted:
                if "response" in item:
                    endpoint = APIEndpoint(
                        url=item["url"],
                        method=item["method"],
                        headers=item.get("headers", {}),
                        request_body=item.get("post_data"),
                        response_status=item["response"]["status"],
                        response_headers=item["response"]["headers"],
                        timing=item["response"],
                        is_graphql=item["response"].get("headers", {}).get("content-type", "").startswith("application/graphql"),
                    )
                    self._intercepted_endpoints.append(endpoint)

            return self._intercepted_endpoints

        finally:
            page.remove_listener("request", handle_request)
            page.remove_listener("response", handle_response)
            await page.close()

    def _is_api_request(self, request) -> bool:
        """Determine if a request is an API request."""
        url = request.url
        content_type = request.headers.get("content-type", "")
        accept = request.headers.get("accept", "")

        # Check URL patterns
        for pattern_obj in self._endpoint_patterns:
            if pattern_obj and pattern_obj.pattern:
                try:
                    if re.search(pattern_obj.pattern, url):
                        return True
                except re.error:
                    # Skip invalid regex patterns
                    continue

        # Check content types
        api_types = ["application/json", "application/graphql", "application/x-www-form-urlencoded"]
        if any(t in content_type for t in api_types):
            return True
        if any(t in accept for t in api_types):
            return True

        return False

    async def _replay_from_har(self, endpoint: APIEndpoint) -> APIEndpoint:
        """Replay request from HAR file."""
        if not self._mock_har_data:
            return endpoint

        for entry in self._mock_har_data.get("log", {}).get("entries", []):
            req = entry.get("request", {})
            resp = entry.get("response", {})

            if req.get("url") == endpoint.url and req.get("method") == endpoint.method:
                endpoint.response_status = resp.get("status", 0)
                endpoint.response_headers = {
                    h["name"]: h["value"] for h in resp.get("headers", [])
                }
                content = resp.get("content", {})
                endpoint.response_body = content.get("text")
                break

        return endpoint

    def _update_rate_limit_from_headers(self, domain: str, headers: Dict[str, str]):
        """Update rate limiter from response headers."""
        if domain not in self._rate_limiters:
            from ..utils.rate_limiter import RateLimiter, RateLimitConfig
            self._rate_limiters[domain] = RateLimiter(RateLimitConfig(
                requests_per_second=self._engine_config.rate_limit_per_endpoint / 60,
            ))

        rate_limit_remaining = headers.get("X-RateLimit-Remaining") or headers.get("x-ratelimit-remaining")
        rate_limit_reset = headers.get("X-RateLimit-Reset") or headers.get("x-ratelimit-reset")

        if rate_limit_remaining is not None:
            try:
                remaining = int(rate_limit_remaining)
                if remaining <= 5:
                    # Slow down
                    pass
            except ValueError:
                pass

    async def replay_request(self, endpoint: APIEndpoint) -> APIEndpoint:
        """Replay a previously captured request."""
        return await self.call(endpoint)

    async def refresh_token(self, auth_config: Dict[str, Any]) -> Dict[str, Any]:
        """Refresh OAuth token."""
        token_url = auth_config.get("token_url") or auth_config.get("oauth_token_url")
        if not token_url:
            raise ValueError("No token URL configured for refresh")

        client_id = auth_config.get("client_id") or auth_config.get("oauth_client_id")
        client_secret = auth_config.get("client_secret") or auth_config.get("oauth_client_secret")
        refresh_token = auth_config.get("refresh_token")

        if not all([client_id, client_secret, refresh_token]):
            raise ValueError("Missing required OAuth credentials for token refresh")

        data = {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(token_url, data=data)
            response.raise_for_status()
            token_data = response.json()

            # Update cache
            cache_key = f"{client_id}:{token_url}"
            self._token_cache[cache_key] = token_data

            return token_data

    async def _call_impl(
        self, endpoint: APIEndpoint, auth: Optional[Dict[str, Any]]
    ) -> APIEndpoint:
        """Internal implementation of API call."""
        return await self.call(endpoint, auth)

    async def _discover_endpoints_impl(self, url: str) -> List[APIEndpoint]:
        """Internal implementation of endpoint discovery."""
        return await self.discover_endpoints(url)

    async def _intercept_network_impl(self, url: str, duration_ms: int) -> List[APIEndpoint]:
        """Internal implementation of network interception."""
        return await self.intercept_network(url, duration_ms)

    async def _replay_request_impl(self, endpoint: APIEndpoint) -> APIEndpoint:
        """Internal implementation of request replay."""
        return await self.replay_request(endpoint)

    async def _refresh_token_impl(self, auth_config: Dict[str, Any]) -> Dict[str, Any]:
        """Internal implementation of token refresh."""
        return await self.refresh_token(auth_config)

    def enable_mock_mode(self, har_file: str):
        """Enable mock mode with HAR file."""
        self._mock_mode.enabled = True
        self._mock_mode.har_path = Path(har_file)
        asyncio.create_task(self._load_mock_har(har_file))

    def disable_mock_mode(self):
        """Disable mock mode."""
        self._mock_mode.enabled = False
        self._mock_har_data = None

    async def _load_mock_har(self, har_path: str):
        """Load HAR file for mock mode."""
        try:
            with open(har_path) as f:
                self._mock_har_data = json.load(f)
            self.logger.info("Loaded mock HAR file", path=har_path, entries=len(self._mock_har_data.get("log", {}).get("entries", [])))
        except Exception as e:
            self.logger.error("Failed to load HAR file", path=har_path, error=str(e))

    def _create_retryer(self):
        return create_retry_policy(
            max_attempts=self.retry_policy.max_attempts,
            base_delay=self.retry_policy.base_delay,
            max_delay=self.retry_policy.max_delay,
            retryable_status_codes=self.retry_policy.retryable_status_codes,
            retryable_exceptions=self.retry_policy.retryable_exceptions,
        )

    async def graphql_query(self, url: str, query: str, variables: Dict[str, Any] = None, auth: Dict = None) -> Dict[str, Any]:
        """Execute a GraphQL query."""
        endpoint = APIEndpoint(
            url=url,
            method="POST",
            headers={"Content-Type": "application/json"},
            request_body={"query": query, "variables": variables or {}},
            is_graphql=True,
        )
        return await self.call(endpoint, auth)


async def create_api_engine(config: EngineConfig) -> APIEngine:
    """Factory function to create API engine."""
    engine = APIEngine()
    await engine.initialize(config)
    return engine