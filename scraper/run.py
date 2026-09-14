from __future__ import annotations
import argparse, json, logging
from pathlib import Path
from .api import scrape

def main() -> int:
    parser = argparse.ArgumentParser(description="Robots-aware free-first scraper with self-hosted Firecrawl, Crawlee, Playwright, and Scrapy")
    parser.add_argument("--target", help="Public URL to scrape; prompted for when omitted")
    parser.add_argument("--goal", help="What to extract; prompted for when omitted")
    parser.add_argument("--schema", help="JSON schema file for structured extraction")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--mode", choices=["auto", "free_only", "cloud_preferred"], default="free_only")
    parser.add_argument("--engine", choices=["firecrawl", "crawlee", "playwright", "scrapy", "auto"], default="auto", help="Force specific engine (default: auto-select)")
    parser.add_argument("--output-path", help="Override output directory")
    parser.add_argument("--max-pages", type=int, default=1, help="Maximum same-domain pages to scrape")
    parser.add_argument("--depth", type=int, default=0, help="Maximum same-domain link depth")
    parser.add_argument("--use-proxy", action="store_true", help="Enable proxy rotation (requires proxy config)")
    parser.add_argument("--render-js", action="store_true", help="Force JavaScript rendering")
    parser.add_argument("--extract-schema", help="JSON schema file for structured extraction (Firecrawl)")
    parser.add_argument("--prompt", help="Natural language extraction prompt (Firecrawl Agent)")
    parser.add_argument("--resume", help="Resume crawl from session ID")
    args = parser.parse_args()
    
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    
    args.target = args.target or input("Public URL to scrape: ").strip()
    args.goal = args.goal or input("What do you need from this page? ").strip()
    
    if not args.target or not args.goal:
        parser.error("a URL and goal are required")
    
    schema = json.loads(Path(args.schema).read_text(encoding="utf-8")) if args.schema else {}
    extract_schema = json.loads(Path(args.extract_schema).read_text(encoding="utf-8")) if args.extract_schema else None
    
    engine = None if args.engine == "auto" else args.engine
    
    result, paths = scrape(
        args.target, 
        args.goal, 
        schema, 
        config_path=args.config, 
        mode=args.mode, 
        engine=engine, 
        max_pages=args.max_pages, 
        depth=args.depth, 
        output_directory=args.output_path,
        use_proxy=args.use_proxy,
        render_js=args.render_js,
        extract_schema=extract_schema,
        prompt=args.prompt,
        resume_session_id=args.resume,
    )
    
    print(json.dumps({
        "engine": result.engine, 
        "items": len(result.items), 
        "attempts": result.attempts,
        "files": {k: str(v) for k, v in paths.items()}
    }, indent=2))
    return 0

if __name__ == "__main__": raise SystemExit(main())