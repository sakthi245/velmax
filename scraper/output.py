from __future__ import annotations
import csv, json, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from .models import ScrapeResult

def _stem(url: str) -> str:
    return re.sub(r"[^a-zA-Z0-9]+", "-", url).strip("-")[:80] or "scrape"

def write_output(result: ScrapeResult, target: str, directory: str | Path) -> dict[str, Path]:
    root = Path(directory); root.mkdir(parents=True, exist_ok=True); stem = _stem(target)
    jsonl = root / f"{stem}.jsonl"; meta = root / f"{stem}.meta.json"
    with jsonl.open("w", encoding="utf-8") as file:
        for item in result.items: file.write(json.dumps(item, ensure_ascii=False) + "\n")
    meta.write_text(json.dumps({"target": target, "created_at": datetime.now(timezone.utc).isoformat(), "engine_used": result.engine, "engine_attempts": result.attempts, "limits_hit": result.limits_hit, "item_count": len(result.items)}, indent=2), encoding="utf-8")
    paths = {"jsonl": jsonl, "meta": meta}
    if result.items and all(isinstance(v, (str, int, float, bool, type(None))) for item in result.items for v in item.values()):
        columns = sorted({key for item in result.items for key in item})
        csv_path = root / f"{stem}.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=columns); writer.writeheader(); writer.writerows(result.items)
        paths["csv"] = csv_path
    return paths
