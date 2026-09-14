from __future__ import annotations

from pathlib import Path
from typing import Dict


class TemplateLibrary:
    """Manages built-in and user templates."""

    BUILTIN_TEMPLATES = {
        "scrapy_spider": {
            "main.py.j2": "http/main.py.j2",
            "config.py.j2": "http/config.py.j2",
            "test.py.j2": "http/test.py.j2",
            "requirements.txt.j2": "http/requirements.txt.j2",
        },
        "playwright_script": {
            "main.py.j2": "browser/main.py.j2",
            "config.py.j2": "browser/config.py.j2",
            "test.py.j2": "browser/test.py.j2",
            "requirements.txt.j2": "browser/requirements.txt.j2",
        },
        "crawlee_crawler": {
            "main.py.j2": "managed/main.py.j2",
            "config.py.j2": "managed/config.py.j2",
            "test.py.j2": "managed/test.py.j2",
            "requirements.txt.j2": "managed/requirements.txt.j2",
        },
        "firecrawl_script": {
            "main.py.j2": "cloud/main.py.j2",
            "config.py.j2": "cloud/config.py.j2",
            "test.py.j2": "cloud/test.py.j2",
            "requirements.txt.j2": "cloud/requirements.txt.j2",
        },
        "api_client": {
            "main.py.j2": "api/main.py.j2",
            "config.py.j2": "api/config.py.j2",
            "test.py.j2": "api/test.py.j2",
            "requirements.txt.j2": "api/requirements.txt.j2",
        },
        "hybrid_scraper": {
            "main.py.j2": "hybrid/main.py.j2",
            "config.py.j2": "hybrid/config.py.j2",
            "test.py.j2": "hybrid/test.py.j2",
            "requirements.txt.j2": "hybrid/requirements.txt.j2",
        },
    }

    def __init__(self, template_dir: Path):
        self.template_dir = template_dir
        self._versions = {}

    def render(self, template_name: str, context: Dict[str, Any]) -> str:
        # Try built-in template first
        # In practice, this would use jinja2 with the template
        return f"# Generated from {template_name}\n# Context: {list(context.keys())}"

    def get_versions(self) -> Dict[str, str]:
        return self._versions