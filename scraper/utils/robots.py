from __future__ import annotations
from functools import lru_cache
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser
import requests

@lru_cache(maxsize=128)
def _robots(origin: str, agent: str) -> RobotFileParser:
    parser = RobotFileParser(); parser.set_url(origin + "/robots.txt")
    try:
        response = requests.get(parser.url, timeout=10, headers={"User-Agent": agent})
        if response.ok: parser.parse(response.text.splitlines())
        else: parser.parse([])
    except requests.RequestException:
        # An unavailable robots file is not permission to bypass an explicit policy;
        # allow only because no policy could be retrieved, and log at the caller.
        parser.parse([])
    return parser

def allowed(url: str, agent: str) -> bool:
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}: return False
    return _robots(f"{parts.scheme}://{parts.netloc}", agent).can_fetch(agent, url)
