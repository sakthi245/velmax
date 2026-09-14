from __future__ import annotations
import json, os
from pathlib import Path
from dotenv import load_dotenv

# Loads a developer's ignored local .env file; existing OS environment values win.
load_dotenv()

# State file for tracking engine limits
STATE_FILE = Path(".scraper_state.json")

def _state() -> dict[str, str]:
    try: return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError): return {}

def _mark(name: str, value: str) -> None:
    data = _state(); data[name] = value
    STATE_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")

def mark_limit_reached(name: str) -> None:
    _mark(name, "limited")

def get_limit_state(name: str) -> str:
    return _state().get(name, "ok")
