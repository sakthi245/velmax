from __future__ import annotations
from pathlib import Path
from typing import Any, Optional
from .config import load_config
from .config.schemas import UniversalConfig
from .output import write_output
from .strategy import FallbackStrategyRouter
from .models import ScrapeResult
from .utils.robots import allowed
from urllib.parse import urljoin, urlsplit, urldefrag
from html.parser import HTMLParser
import requests
import asyncio

class _Links(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[str] = []
    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "a" and dict(attrs).get("href"): 
            self.links.append(dict(attrs)["href"])

def _same_origin_links(url: str, config: UniversalConfig) -> list[str]:
    try:
        response = requests.get(url, timeout=config.rate_limit.requests_per_second, headers={"User-Agent": config.robots.user_agent})
        response.raise_for_status()
        parser = _Links()
        parser.feed(response.text)
        origin = urlsplit(url).netloc.lower()
        return [link for raw in parser.links if urlsplit((link := urldefrag(urljoin(response.url, raw))[0])).scheme in {"http", "https"} and urlsplit(link).netloc.lower() == origin]
    except requests.RequestException: 
        return []

def scrape(
    target: str,
    goal: str,
    schema: dict[str, Any] | None = None,
    *,
    config: UniversalConfig | None = None,
    config_path: str | Path | None = None,
    mode: str | None = None,
    engine: str | None = None,
    max_pages: int = 1,
    depth: int = 0,
    output_directory: str | Path | None = None,
    write_files: bool = True,
    use_proxy: bool = False,
    render_js: bool = False,
    extract_schema: dict[str, Any] | None = None,
    prompt: str | None = None,
    resume_session_id: str | None = None,
) -> tuple[ScrapeResult, dict[str, Path]] | ScrapeResult:
    
    config = config or load_config(config_path)
    if mode: 
        pass
    if max_pages < 1 or depth < 0: 
        raise ValueError("max_pages must be >= 1 and depth must be >= 0")
    
    router = FallbackStrategyRouter(config)
    
    async def run_scrape() -> ScrapeResult:
        await router.initialize()
        return await router.scrape(target, goal, schema, engine=engine, resume_session_id=resume_session_id)
    
    result = asyncio.run(run_scrape())
    
    if write_files:
        paths = write_output(result, target, output_directory or config.output_dir)
        return result, paths
    return result

async def scrape_async(
    target: str,
    goal: str,
    schema: dict[str, Any] | None = None,
    *,
    config: UniversalConfig | None = None,
    config_path: str | Path | None = None,
    mode: str | None = None,
    engine: str | None = None,
    max_pages: int = 1,
    depth: int = 0,
    output_directory: str | Path | None = None,
    write_files: bool = True,
    use_proxy: bool = False,
    render_js: bool = False,
    extract_schema: dict[str, Any] | None = None,
    prompt: str | None = None,
    resume_session_id: str | None = None,
) -> tuple[ScrapeResult, dict[str, Path]] | ScrapeResult:
    
    config = config or load_config(config_path)
    if mode: 
        pass
    if max_pages < 1 or depth < 0: 
        raise ValueError("max_pages must be >= 1 and depth must be >= 0")
    
    router = FallbackStrategyRouter(config)
    await router.initialize()
    
    engine_options = {}
    if use_proxy: engine_options["use_proxy"] = True
    if render_js: engine_options["render_js"] = True
    if extract_schema: engine_options["extract_schema"] = extract_schema
    if prompt: engine_options["prompt"] = prompt
    
    result = await router.scrape(target, goal, schema, engine=engine, resume_session_id=resume_session_id)
    
    if write_files:
        paths = write_output(result, target, output_directory or config.output_dir)
        return result, paths
    return result