"""Deep site profiling module for the universal scraper."""

import asyncio
import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

from playwright.async_api import Page, async_playwright
from playwright.async_api import BrowserContext

from ..config.schemas import EngineType, EngineCapability, AntiBotLevel
from ..engines.registry_v2 import EngineRegistryV2
from ..engines.stealth import StealthManager, StealthConfig
from ..engines.behavioral_mimicry import BehavioralMimicry, InteractionConfig
from ..engines.interfaces import BrowserRequest, BrowserResponse
from ..utils.observability import get_logger

logger = logging.getLogger(__name__)


class ProfileDepth(Enum):
    """Depth of site profiling."""
    QUICK = "quick"          # Basic detection only
    STANDARD = "standard"    # Standard profiling
    DEEP = "deep"            # Deep profiling with interactions


@dataclass
class DeepSiteProfile:
    """Comprehensive site profile for script generation."""
    url: str
    domain: str
    category: str = "unknown"
    js_framework: Optional[str] = None
    js_framework_version: Optional[str] = None
    requires_js: bool = False
    anti_bot_level: AntiBotLevel = AntiBotLevel.NONE
    anti_bot_details: Dict[str, Any] = field(default_factory=dict)
    has_pagination: bool = False
    pagination_type: Optional[str] = None
    pagination_selectors: List[str] = field(default_factory=list)
    page_types: Dict[str, int] = field(default_factory=dict)
    selectors: Dict[str, List[str]] = field(default_factory=dict)
    api_endpoints: List[Dict[str, Any]] = field(default_factory=list)
    auth_required: bool = False
    auth_type: Optional[str] = None
    performance_metrics: Dict[str, float] = field(default_factory=dict)
    recommended_engine: EngineType = EngineType.HTTP
    confidence: float = 0.0
    analyzed_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    sample_pages: int = 0
    
    # Interaction patterns discovered
    interaction_sequences: List[Dict[str, Any]] = field(default_factory=list)
    selector_stability: Dict[str, float] = field(default_factory=dict)
    inferred_schemas: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    fallback_context: Optional[Dict[str, Any]] = None
    profile_depth: str = "standard"
    
    def hash(self) -> str:
        """Generate a hash of the profile for caching."""
        content = f"{self.url}{self.category}{self.js_framework}{self.anti_bot_level}"
        content += f"{self.has_pagination}{self.page_types}{self.selectors}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]


class DeepSiteProfiler:
    """Profiles websites to determine optimal scraping strategy."""
    
    def __init__(self, stealth_config: Optional["StealthConfig"] = None):
        self.stealth_config = stealth_config or StealthConfig()
        self.logger = logging.getLogger("profiler")
        self._browser = None
        self._context = None
        self._page = None
        
        # Regex patterns for detection
        self._js_framework_patterns = {
            "react": [r"react", r"__REACT_DEVTOOLS_GLOBAL_HOOK__", r"react-dom", r"createElement"],
            "vue": [r"vue", r"Vue\.version", r"vue-router", r"Vue\.component"],
            "angular": [r"angular", r"ng-app", r"ng-version", r"@angular"],
            "svelte": [r"svelte", r"svelte-"],
            "nextjs": [r"__NEXT_DATA__", r"next/router", r"_next/static"],
            "nuxt": [r"nuxt", r"__NUXT__"],
            "gatsby": [r"gatsby", r"___gatsby"],
            "remix": [r"remix", r"@remix-run"],
        }
        
        self._anti_bot_patterns = {
            "cloudflare": ["cloudflare", "cf-ray", "cf-cache-status", "__cf_bm", "challenge-platform"],
            "akamai": ["akamai", "akamai-gtm", "akamai-origin-hop"],
            "incapsula": ["incapsula", "_incap_"],
            "perimeterx": ["perimeterx", "px-captcha", "_pxhd"],
            "datadome": ["datadome", "ddos-guard"],
            "shape": ["shape-security", "shape-js"],
        }
        
        self._captcha_patterns = [
            "captcha", "challenge", "recaptcha", "hcaptcha",
            "turnstile", "arkose", "funcaptcha", "geetest",
        ]
        
        # Selector patterns for common elements
        self._selector_patterns = {
            "product": [
                "[data-testid*='product']", "[data-product-id]",
                ".product-card", ".product-item", ".product-tile",
                "[data-testid='product-card']", ".product-grid > div",
            ],
            "pagination": [
                "[aria-label*='pagination']", ".pagination a",
                ".next-page", ".page-next",
                ".pagination .next",
            ],
            "price": [
                "[data-price]", "[data-testid*='price']",
                ".price", ".product-price", ".sale-price",
                "[class*='price']", "[itemprop='price']",
            ],
            "title": [
                "[data-testid*='title']", "[data-testid*='name']",
                "h1.product-title", "h1.product-name",
                ".product-title", ".product-name",
                "[itemprop='name']",
            ],
            "image": [
                "[data-testid*='image'] img", ".product-image img",
                ".product-img img", "[itemprop='image']",
                ".gallery img", ".carousel img",
            ],
            "rating": [
                "[itemprop='ratingValue']", "[data-rating]",
                ".rating", ".stars", ".star-rating",
            ],
            "availability": [
                "[itemprop='availability']", "[data-stock]",
                ".availability", ".stock-status",
                ".in-stock", ".out-of-stock",
            ],
        }

    async def profile(
        self,
        url: str,
        depth: ProfileDepth = ProfileDepth.STANDARD,
        max_pages: int = 5,
    ) -> "DeepSiteProfile":
        """Profile a website to determine optimal scraping strategy."""
        self.logger.info(f"Profiling {url} with depth={depth.value}")
        
        parsed = urlparse(url)
        domain = parsed.netloc
        
        profile = DeepSiteProfile(
            url=url,
            domain=domain,
        )
        
        async with async_playwright() as p:
            browser = await self._launch_browser()
            self._browser = browser
            
            try:
                context = await self._create_context()
                self._context = context
                page = await context.new_page()
                self._page = page
                
                # Apply stealth
                stealth_manager = StealthManager()
                await stealth_manager.apply_to_context(context)
                
                # Navigate to URL
                await self._navigate_and_analyze(page, url, profile, depth)
                
                # Analyze additional pages if deep profiling
                if depth in (ProfileDepth.STANDARD, ProfileDepth.DEEP):
                    await self._analyze_additional_pages(page, profile, depth, max_pages)
                
                # Determine recommended engine
                profile.recommended_engine = self._recommend_engine(profile)
                profile.confidence = self._calculate_confidence(profile)
                
            finally:
                if self._browser:
                    await self._browser.close()
        
        profile.analyzed_at = datetime.utcnow().isoformat()
        return profile

    async def _launch_browser(self):
        """Launch Playwright browser with stealth configuration."""
        p = await async_playwright().start()
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
            ],
        )
        return browser

    async def _create_context(self):
        """Create browser context with stealth settings."""
        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation", "notifications"],
            color_scheme="light",
        )
        return context

    async def _navigate_and_analyze(
        self,
        page: Page,
        url: str,
        profile: "DeepSiteProfile",
        depth: ProfileDepth,
    ):
        """Navigate to URL and perform initial analysis."""
        start_time = time.time()
        
        # Navigate — try networkidle first, fall back to load/domcontentloaded on timeout.
        # Many modern sites (SPAs, e-commerce) never reach networkidle, so we must not
        # hard-fail profiling on it.
        response = None
        try:
            response = await page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception:
            self.logger.info("networkidle timed out, retrying with 'load'", url=url)
            try:
                response = await page.goto(url, wait_until="load", timeout=45000)
            except Exception:
                self.logger.info("'load' timed out, retrying with 'domcontentloaded'", url=url)
                response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
        profile.performance_metrics["initial_load_ms"] = (time.time() - start_time) * 1000
        
        if response:
            profile.performance_metrics["status_code"] = response.status
        
        # Get page content
        content = await page.content()
        profile.sample_pages += 1
        
        # Detect JS framework
        profile.js_framework = await self._detect_js_framework(page)
        profile.requires_js = profile.js_framework is not None
        
        # Detect anti-bot
        profile.anti_bot_level, profile.anti_bot_details = await self._detect_anti_bot(page)
        
        # Detect JS framework version
        profile.js_framework_version = await self._detect_js_version(page)
        
        # Detect category
        profile.category = await self._detect_category(page)
        
        # Detect pagination
        profile.has_pagination = await self._detect_pagination(page)
        if profile.has_pagination:
            profile.pagination_type = await self._detect_pagination_type(page)
            profile.pagination_selectors = await self._find_pagination_selectors(page)
        
        # Find selectors for common elements
        profile.selectors = await self._find_selectors(page)
        
        # Find API endpoints
        profile.api_endpoints = await self._find_api_endpoints(page)
        
        # Detect auth
        profile.auth_required = await self._detect_auth(page)
        if profile.auth_required:
            profile.auth_type = await self._detect_auth_type(page)
        
        # Check for pagination
        profile.has_pagination = await self._detect_pagination(page)

    async def _analyze_additional_pages(
        self,
        page: Page,
        profile: "DeepSiteProfile",
        depth: ProfileDepth,
        max_pages: int,
    ):
        """Analyze additional pages for deep profiling."""
        if profile.has_pagination and profile.pagination_selectors:
            # Filter out selectors that match <link> tags (in <head>, not clickable)
            clickable_selectors = []
            for selector in profile.pagination_selectors:
                # Skip selectors that would match <link> tags
                if selector.startswith("link[") or " link" in selector:
                    self.logger.debug(f"Skipping <link> selector: {selector}")
                    continue
                clickable_selectors.append(selector)

            # Try each pagination selector until one works
            for selector in clickable_selectors:
                try:
                    # Use Playwright locator API which auto-waits for visibility
                    locator = page.locator(selector).first
                    # Wait for element to be visible and stable (up to 10s)
                    await locator.wait_for(state="visible", timeout=10000)
                    # Scroll into view if needed
                    await locator.scroll_into_view_if_needed()
                    # Small delay for human-like behavior
                    await asyncio.sleep(0.3)
                    await locator.click()
                    # Wait for navigation/content load
                    await page.wait_for_load_state("networkidle", timeout=15000)

                    # Analyze this page
                    await self._analyze_page(page, profile)
                    profile.sample_pages += 1

                    if profile.sample_pages >= max_pages:
                        break

                    # Success - don't try other selectors
                    return

                except Exception as e:
                    self.logger.warning(f"Pagination selector '{selector}' failed: {e}")
                    # Try next selector
                    continue

            self.logger.info(f"Analyzed {profile.sample_pages} pages during profiling (no clickable pagination found)")

            self.logger.info(f"Analyzed {profile.sample_pages} pages during profiling")

    async def _analyze_page(self, page: Page, profile: "DeepSiteProfile"):
        """Analyze a single page."""
        profile.sample_pages += 1
        
        # Get page content
        content = await page.content()
        
        # Find additional selectors
        selectors = await self._find_selectors(page)
        for key, selectors_list in selectors.items():
            if key in profile.selectors:
                profile.selectors[key].extend(selectors_list)
            else:
                profile.selectors[key] = selectors_list
        
        # Find API endpoints
        endpoints = await self._find_api_endpoints(page)
        profile.api_endpoints.extend(endpoints)
        
        # Check for new page types
        page_type = await self._classify_page(page)
        if page_type:
            profile.page_types[page_type] = profile.page_types.get(page_type, 0) + 1

    async def _detect_js_framework(self, page: Page) -> Optional[str]:
        """Detect JavaScript framework used by the site."""
        for framework, patterns in self._js_framework_patterns.items():
            for pattern in patterns:
                try:
                    if await page.evaluate(f"() => document.body.innerHTML.includes('{pattern}')"):
                        return framework
                except:
                    continue
        return None

    async def _detect_js_version(self, page: Page) -> Optional[str]:
        """Detect JavaScript framework version."""
        # Try to detect version from common globals
        version_checks = {
            "react": "React.version",
            "vue": "Vue.version",
            "angular": "angular.version.full",
        }
        
        for framework, var in version_checks.items():
            try:
                version = await page.evaluate(f"() => {var}")
                if version:
                    return version
            except:
                continue
        return None

    async def _detect_anti_bot(self, page: Page) -> tuple:
        """Detect anti-bot protection level."""
        # Check for known anti-bot services
        content = await page.content()
        content_lower = content.lower()
        
        details = {}
        max_level = AntiBotLevel.NONE
        
        for service, patterns in self._anti_bot_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    details[service] = True
                    if service in ["cloudflare", "akamai", "incapsula", "perimeterx", "datadome", "shape"]:
                        max_level = AntiBotLevel.HIGH
                    elif service in ["recaptcha", "hcaptcha", "turnstile"]:
                        max_level = max(max_level, AntiBotLevel.MEDIUM)
        
        # Check for CAPTCHA
        for pattern in self._captcha_patterns:
            if pattern in content_lower:
                details["captcha"] = True
                max_level = max(max_level, AntiBotLevel.HIGH)
        
        # Check response headers for anti-bot
        try:
            response = await page.reload()
            headers = dict(response.headers)
            if "cf-ray" in headers:
                details["cloudflare"] = True
                max_level = AntiBotLevel.HIGH
            if "x-sucuri-id" in headers:
                details["sucuri"] = True
                max_level = max(max_level, AntiBotLevel.MEDIUM)
        except:
            pass
        
        return max_level, details

    async def _detect_category(self, page: Page) -> str:
        """Detect page/category type."""
        url = page.url.lower()
        content = await page.content()
        content_lower = content.lower()
        
        categories = {
            "ecommerce": ["product", "cart", "checkout", "price", "buy now", "add to cart", "shop", "store"],
            "news": ["article", "news", "blog", "post", "published", "author", "headline"],
            "social": ["profile", "followers", "following", "tweet", "post", "share", "like"],
            "forum": ["thread", "forum", "reply", "topic", "discussion", "comment"],
            "documentation": ["documentation", "docs", "api reference", "guide", "tutorial"],
            "job": ["job", "career", "position", "hiring", "apply", "salary"],
            "real_estate": ["property", "rent", "sale", "bedroom", "bathroom", "sqft", "listing"],
            "travel": ["hotel", "flight", "booking", "vacation", "resort", "trip"],
            "classified": ["classified", "listing", "for sale", "wanted", "marketplace"],
        }
        
        scores = {}
        for category, keywords in categories.items():
            score = sum(1 for kw in keywords if kw in content_lower)
            if score > 0:
                scores[category] = score
        
        if scores:
            return max(scores, key=scores.get)
        return "unknown"

    async def _detect_pagination(self, page) -> bool:
        """Detect if page has pagination."""
        for pattern in self._selector_patterns["pagination"]:
            try:
                if await page.query_selector(pattern):
                    return True
            except:
                continue
        return False

    async def _detect_pagination_type(self, page) -> str:
        """Detect pagination type."""
        # Check for URL-based pagination
        url = page.url
        if re.search(r'[?&](page|p)=', url):
            return "url_param"
        
        # Check for cursor-based
        content = await page.content()
        if "cursor" in page.url.lower() or "after=" in page.url:
            return "cursor"
        
        # Check for infinite scroll
        if await page.evaluate("() => document.body.scrollHeight > window.innerHeight"):
            return "infinite_scroll"
        
        return "traditional"

    async def _find_pagination_selectors(self, page) -> List[str]:
        """Find pagination selectors on the page, filtering out hidden <link> tags."""
        selectors = []
        for pattern in self._selector_patterns["pagination"]:
            try:
                elements = await page.query_selector_all(pattern)
                if elements:
                    # Filter out patterns that only match hidden <link> tags
                    visible_count = 0
                    for el in elements:
                        tag_name = await el.evaluate("el => el.tagName.toLowerCase()")
                        if tag_name == "link":
                            # Skip <link rel="next"> - it's metadata, not clickable
                            continue
                        # Check if element is visible
                        is_visible = await el.is_visible()
                        if is_visible:
                            visible_count += 1
                    if visible_count > 0:
                        selectors.append(pattern)
            except:
                continue
        return selectors

    async def _find_selectors(self, page) -> Dict[str, List[str]]:
        """Find all relevant selectors on the page."""
        selectors = {}
        for category, patterns in self._selector_patterns.items():
            found = []
            for pattern in patterns:
                try:
                    elements = await page.query_selector_all(pattern)
                    if elements:
                        found.append(pattern)
                except:
                    continue
            if found:
                selectors[category] = found
        return selectors

    async def _find_api_endpoints(self, page) -> List[Dict[str, Any]]:
        """Find API endpoints by monitoring network requests."""
        endpoints = []
        
        # Set up network monitoring
        async def handle_response(response):
            if response.request.resource_type in ["xhr", "fetch"]:
                endpoints.append({
                    "url": response.url,
                    "method": response.request.method,
                    "status": response.status,
                    "resource_type": response.request.resource_type,
                })
        
        page.on("response", handle_response)
        
        # Trigger some navigation to trigger requests
        try:
            await page.reload(wait_until="networkidle", timeout=10000)
        except:
            pass
        
        page.remove_listener("response", handle_response)
        return endpoints

    async def _detect_auth(self, page) -> bool:
        """Detect if authentication is required."""
        # Check for login forms
        login_selectors = [
            "form[action*='login']", "form[action*='signin']",
            "input[type='password']", "[type='password']",
            ".login-form", ".signin-form", "#login-form",
            "button:has-text('Login')", "button:has-text('Sign In')",
        ]
        
        for selector in login_selectors:
            try:
                if await page.query_selector(selector):
                    return True
            except:
                continue
        
        # Check for auth-related cookies
        cookies = await context.cookies()
        auth_cookies = [c for c in cookies if any(
            kw in c["name"].lower() for kw in ["auth", "token", "session", "jwt", "auth"]
        )]
        if auth_cookies:
            return True
        
        return False

    async def _detect_auth_type(self, page) -> str:
        """Detect authentication type."""
        # Check for OAuth providers
        oauth_patterns = {
            "oauth2": ["oauth", "oauth2", "authorization_code"],
            "saml": ["saml", "sso"],
            "oidc": ["openid", "oidc"],
            "jwt": ["jwt", "bearer"],
            "api_key": ["api_key", "apikey", "api-key"],
        }
        
        content = await page.content()
        content_lower = content.lower()
        
        for auth_type, patterns in oauth_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    return auth_type
        
        return "form"

    async def _classify_page(self, page: Page) -> Optional[str]:
        """Classify page type."""
        url = page.url.lower()
        
        if any(p in url for p in ["/product/", "/item/", "/p/", "/item/"]):
            return "product"
        elif any(p in url for p in ["/category/", "/category", "/collection", "/c/"]):
            return "category"
        elif any(p in url for p in ["/search", "/search/", "/s?"]):
            return "search"
        elif any(p in url for p in ["/cart", "/checkout", "/cart"]):
            return "cart"
        elif any(p in url for p in ["/account", "/profile", "/dashboard", "/settings"]):
            return "account"
        elif any(p in url for p in ["/login", "/signin", "/signin"]):
            return "login"
        elif any(p in url for p in ["/register", "/signup", "/register"]):
            return "register"
        elif any(p in url for p in ["/article", "/blog", "/post/", "/news/"]):
            return "article"
        elif any(p in url for p in ["/api/", "/graphql", "/v1/", "/v2/"]):
            return "api"
        
        return "other"

    async def _detect_pagination(self, page) -> bool:
        """Detect if page has pagination."""
        for pattern in self._selector_patterns["pagination"]:
            try:
                if await page.query_selector(pattern):
                    return True
            except:
                continue
        return False

    async def _detect_pagination_type(self, page) -> str:
        """Detect pagination type."""
        url = page.url
        if re.search(r'[?&](page|p)=', url):
            return "url_param"
        if "cursor" in page.url.lower() or "after=" in page.url:
            return "cursor"
        if await page.evaluate("() => document.body.scrollHeight > window.innerHeight"):
            return "infinite_scroll"
        return "traditional"

    async def _find_pagination_selectors(self, page) -> List[str]:
        """Find pagination selectors."""
        selectors = []
        for pattern in self._selector_patterns["pagination"]:
            try:
                elements = await page.query_selector_all(pattern)
                if elements:
                    selectors.append(pattern)
            except:
                continue
        return selectors

    async def _detect_auth(self, page) -> bool:
        """Detect if authentication is required."""
        login_selectors = [
            "form[action*='login']", "form[action*='signin']",
            "input[type='password']", "[type='password']",
            ".login-form", ".signin-form", "#login-form",
            "button:has-text('Login')", "button:has-text('Sign In')",
        ]
        
        for selector in login_selectors:
            try:
                if await page.query_selector(selector):
                    return True
            except:
                continue
        
        # Check for auth cookies
        cookies = await page.context.cookies()
        auth_cookies = [c for c in cookies if any(
            kw in c["name"].lower() for kw in ["auth", "token", "session", "jwt", "auth"]
        )]
        if auth_cookies:
            return True
        
        return False

    async def _detect_auth_type(self, page) -> str:
        """Detect authentication type."""
        oauth_patterns = {
            "oauth2": ["oauth", "oauth2", "authorization_code"],
            "saml": ["saml", "sso"],
            "oidc": ["openid", "oidc"],
            "jwt": ["jwt", "bearer"],
            "api_key": ["api_key", "apikey", "api-key"],
        }
        
        content = await page.content()
        content_lower = content.lower()
        
        for auth_type, patterns in oauth_patterns.items():
            for pattern in patterns:
                if pattern in content_lower:
                    return auth_type
        
        return "form"

    def _recommend_engine(self, profile) -> str:
        """Recommend the best engine based on profile."""
        # Cloud (Firecrawl) for high anti-bot
        if profile.anti_bot_level in ("high", "extreme"):
            return EngineType.CLOUD.value
        
        # Browser for JS-heavy sites
        if profile.requires_js or profile.js_framework:
            if profile.anti_bot_level in ("medium", "high"):
                return EngineType.CLOUD.value
            return EngineType.BROWSER.value
        
        # Managed (Crawlee) for large scale
        if profile.has_pagination and profile.sample_pages > 5:
            return EngineType.MANAGED.value
        
        # HTTP for simple static sites
        return EngineType.HTTP.value

    def _calculate_confidence(self, profile) -> float:
        """Calculate confidence score for the profile."""
        score = 0.0
        
        # Base confidence
        score += 0.2
        
        # JS framework detected
        if profile.js_framework:
            score += 0.2
        
        # Anti-bot detected
        if profile.anti_bot_level != "none":
            score += 0.1
        
        # Selectors found
        if profile.selectors:
            score += min(0.3, len(profile.selectors) * 0.05)
        
        # API endpoints found
        if profile.api_endpoints:
            score += 0.15
        
        # Pagination detected
        if profile.has_pagination:
            score += 0.1
        
        # Category identified
        if profile.category != "unknown":
            score += 0.15
        
        return min(score, 1.0)

    def _generate_crawl_strategy(self, profile) -> Dict[str, Any]:
        """Generate crawl strategy based on profile."""
        strategy = {
            "engine": profile.recommended_engine,
            "use_stealth": True,
            "rate_limit": 2.0,
            "concurrent_requests": 3,
        }
        
        if profile.anti_bot_level in ("high", "extreme"):
            strategy.update({
                "use_stealth": True,
                "use_proxy": True,
                "rate_limit": 1.0,
                "concurrent_requests": 1,
            })
        
        if profile.has_pagination:
            strategy["pagination"] = {
                "type": profile.pagination_type,
                "selectors": profile.pagination_selectors,
            }
        
        if profile.selectors:
            strategy["selectors"] = profile.selectors
        
        return strategy


async def profile_site(url: str, depth: ProfileDepth = ProfileDepth.STANDARD, max_pages: int = 5) -> "DeepSiteProfile":
    """Convenience function to profile a site."""
    profiler = DeepSiteProfiler()
    return await profiler.profile(url, depth, max_pages)