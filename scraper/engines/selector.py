from __future__ import annotations
from typing import Optional, List
from .base import EngineCapability
from .registry import EngineRegistry
from urllib.parse import urlparse
import fnmatch
import logging

LOG = logging.getLogger(__name__)

class EngineSelector:
    def __init__(self, registry: EngineRegistry, config: dict):
        self.registry = registry
        self.config = config
        self.routing_rules = config.get("routing", {}).get("rules", [])
        self.default_engine = config.get("routing", {}).get("default", "crawlee")
    
    def select(self, request: "ScrapeRequest") -> str:
        url = request.url
        parsed = urlparse(url)
        
        if request.engine_options.get("engine"):
            engine = request.engine_options["engine"]
            if self.registry.is_registered(engine):
                return engine
            LOG.warning(f"Requested engine '{engine}' not available, using selector")
        
        for rule in self.routing_rules:
            if self._matches_rule(url, parsed, rule):
                engine = rule.get("engine")
                if engine and self.registry.is_registered(engine):
                    LOG.debug(f"Rule matched for {url}: {rule.get('reason', 'no reason')} -> {engine}")
                    return engine
        
        required = self._infer_capabilities(request)
        best = self.registry.select_best(required)
        if best:
            LOG.debug(f"Inferred capabilities {required} -> {best}")
            return best
        
        LOG.debug(f"No match, using default: {self.default_engine}")
        return self.default_engine
    
    def _matches_rule(self, url: str, parsed, rule: dict) -> bool:
        if "domain" in rule and rule["domain"] is not None and rule["domain"] not in parsed.netloc:
            return False
        if "pattern" in rule and rule["pattern"] is not None and not fnmatch.fnmatch(url, rule["pattern"]):
            return False
        if "path_prefix" in rule and rule["path_prefix"] is not None and not parsed.path.startswith(rule["path_prefix"]):
            return False
        return True
    
    def _infer_capabilities(self, request: "ScrapeRequest") -> List[EngineCapability]:
        caps = []
        opts = request.engine_options
        
        if opts.get("render_js") or opts.get("wait_for_selector"):
            caps.append(EngineCapability.JAVASCRIPT)
        
        if opts.get("use_proxy"):
            caps.append(EngineCapability.PROXY_ROTATION)
        
        if opts.get("extract_schema") or opts.get("prompt"):
            caps.append(EngineCapability.LLM_EXTRACTION)
        
        if opts.get("crawl") or request.goal.lower().startswith("crawl"):
            caps.append(EngineCapability.LARGE_CRAWL)
        
        if opts.get("login_required") or opts.get("requires_auth"):
            caps.append(EngineCapability.AUTH_FLOWS)
        
        if request.url.lower().endswith(".pdf"):
            caps.append(EngineCapability.PDF_PARSING)
        
        return caps

from .base import ScrapeRequest