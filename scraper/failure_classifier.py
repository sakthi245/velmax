from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set

from .config.schemas import UniversalResult, SiteProfile, FallbackContext, FailureClassification


class FailureClassifier:
    """Classifies failures to determine fallback strategy."""

    # Broad failure categories per requirements
    TRIGGER_CATEGORIES = {
        "network": [
            "timeout", "connection_refused", "connection_reset", "dns_failure",
            "ssl_error", "proxy_error", "certificate_verify_failed",
            "connection_aborted", "connection_closed",
        ],
        "http": [
            "403", "429", "500", "502", "503", "504", "401", "400", "404", "408",
        ],
        "blocking": [
            "captcha", "challenge", "access_denied", "blocked", "rate_limit",
            "waf", "cloudflare", "akamai", "incapsula", "perimeterx", "datadome",
            "please_verify", "unusual_traffic", "robot_check", "bot_detected",
            "access_forbidden", "ip_blocked", "geo_blocked",
        ],
        "content": [
            "empty_response", "zero_bytes", "redirect_loop", "login_required",
            "paywall", "geo_restricted", "age_gate", "membership_required",
            "javascript_required", "cookies_required",
        ],
        "parsing": [
            "schema_validation_failed", "no_matching_selectors", "json_decode_error",
            "encoding_error", "html_parse_error", "xpath_not_found", "css_selector_failed",
            "regex_no_match", "empty_selector_result",
        ],
        "engine": [
            "browser_crash", "out_of_memory", "process_killed", "cdp_disconnected",
            "playwright_timeout", "context_destroyed", "navigation_timeout",
            "script_execution_failed", "element_not_found", "stale_element",
        ],
        "quality": [
            "completeness_below_threshold", "accuracy_below_threshold",
            "duplicate_rate_high", "staleness_high", "schema_mismatch",
            "data_integrity_failed", "enrichment_failed",
        ],
    }

    SEVERITY_MAP = {
        "network": "high",
        "http": "high",
        "blocking": "critical",
        "content": "medium",
        "parsing": "medium",
        "engine": "high",
        "quality": "medium",
    }

    def __init__(self):
        pass

    def classify(
        self,
        error: Exception,
        result: Optional[UniversalResult],
        profile: Optional[SiteProfile],
    ) -> FailureClassification:
        """Classify failure and determine fallback action."""
        error_str = str(error).lower() if error else ""

        # Check all categories
        for category, patterns in self.TRIGGER_CATEGORIES.items():
            if self._matches(error, result, patterns):
                return FailureClassification(
                    category=category,
                    severity=self.SEVERITY_MAP.get(category, "medium"),
                    should_fallback=True,
                    context=self._build_context(category, error, result, profile),
                    retry_suggested=category in ("network", "http", "engine"),
                    suggested_engine=self._suggest_engine(category, profile),
                )

        return FailureClassification(
            category="unknown",
            severity="medium",
            should_fallback=True,
            context={"error": str(error), "result": str(result) if result else None},
            retry_suggested=True,
            suggested_engine=None,
        )

    def _matches(
        self,
        error: Exception,
        result: Optional[UniversalResult],
        patterns: List[str],
    ) -> bool:
        """Check if error/result matches any pattern."""
        error_str = str(error).lower() if error else ""

        # Check error message
        for pattern in patterns:
            if pattern in error_str:
                return True

        # Check result content
        if result and result.data:
            content_str = str(result.data).lower()
            for pattern in patterns:
                if pattern in content_str:
                    return True

            # Check status code
            if hasattr(result, 'status_code') and result.status_code:
                if str(result.status_code) in patterns:
                    return True

        return False

    def _build_context(
        self,
        category: str,
        error: Exception,
        result: Optional[UniversalResult],
        profile: Optional[SiteProfile],
    ) -> Dict[str, Any]:
        return {
            "category": category,
            "error": str(error),
            "error_type": type(error).__name__,
            "url": profile.url if profile else None,
            "profile_category": profile.category if profile else None,
            "js_framework": profile.js_framework if profile else None,
            "anti_bot_level": profile.anti_bot_level if profile else None,
            "requires_js": profile.requires_js if profile else None,
            "result_success": result.success if result else False,
            "result_error": result.error if result else None,
        }

    def _suggest_engine(self, category: str, profile: Optional[SiteProfile]) -> Optional[str]:
        """Suggest alternative engine based on failure category."""
        from .config.schemas import EngineType

        if not profile:
            return None

        if category == "blocking" or category == "http":
            if profile.anti_bot_level in ("high", "extreme"):
                return EngineType.CLOUD.value
            return EngineType.BROWSER.value

        if category == "parsing" and profile.requires_js:
            return EngineType.BROWSER.value

        if category == "engine":
            # Try different engine type
            if profile.requires_js:
                return EngineType.HTTP.value
            return EngineType.BROWSER.value

        if category == "quality":
            if profile.js_framework:
                return EngineType.BROWSER.value
            return EngineType.CLOUD.value

        return None