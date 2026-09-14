#!/usr/bin/env python3
"""
Universal Scraper - Uses all engines with auto-fallback
Supports: Scrapy, Playwright, Crawlee, Firecrawl (Docker)
Auto-fixes Docker issues, reports failures
"""

import asyncio
import json
import sys
import os
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scraper import scrape, scrape_async
from scraper.engines.groq_llm_engine import CrawleeLLMCrawler
from scraper.config import ScraperConfig, load_config

OUTPUT_DIR = PROJECT_ROOT / "output"
CUSTOM_SCRIPTS_DIR = PROJECT_ROOT / "custom_scripts"
DOCKER_COMPOSE_FILE = PROJECT_ROOT / "docker-compose.firecrawl.yml"
ENV_FILE = PROJECT_ROOT / ".env.firecrawl"

@dataclass
class ScrapeTask:
    query: str
    urls: List[str]
    goal: str
    schema: Optional[Dict] = None
    engines: List[str] = None
    max_pages: int = 10
    use_docker_firecrawl: bool = True

@dataclass
class ScrapeResult:
    task: ScrapeTask
    success: bool
    engine_used: str
    data: Any
    errors: List[str]
    timestamp: str
    output_files: List[str]

class DockerFirecrawlManager:
    """Manages Firecrawl Docker container with auto-repair"""
    
    def __init__(self):
        self.compose_file = DOCKER_COMPOSE_FILE
        self.env_file = ENV_FILE
        self.required_services = [
            "firecrawl-api", "playwright", "postgres", "redis", "rabbitmq"
        ]
    
    def is_running(self) -> bool:
        """Check if all Firecrawl services are healthy"""
        try:
            result = subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "ps", "--format", "json"],
                capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                return False
            
            services = []
            for line in result.stdout.strip().split('\n'):
                if line:
                    services.append(json.loads(line))
            
            for svc in services:
                if svc.get("Service") in self.required_services:
                    health = svc.get("Health", "")
                    if "healthy" not in health.lower() and "starting" not in health.lower():
                        return False
            return len(services) >= len(self.required_services)
        except Exception:
            return False
    
    def start(self) -> bool:
        """Start Firecrawl stack with auto-repair"""
        print("[Docker] Starting Firecrawl stack...")
        
        # Ensure .env.firecrawl exists
        if not self.env_file.exists():
            print("[Docker] ERROR: .env.firecrawl not found")
            return False
        
        # Login to ghcr.io if needed
        self._ensure_ghcr_login()
        
        # Start containers
        try:
            subprocess.run(
                ["docker", "compose", "-f", str(self.compose_file), "up", "-d"],
                check=True, timeout=120
            )
        except subprocess.CalledProcessError as e:
            print(f"[Docker] Failed to start: {e}")
            return False
        
        # Wait for health checks
        print("[Docker] Waiting for services to become healthy...")
        for i in range(60):  # 5 minutes max
            if self.is_running():
                print("[Docker] All services healthy!")
                return True
            time.sleep(5)
            if i % 6 == 0:
                print(f"[Docker] Still waiting... ({i*5}s)")
        
        print("[Docker] Timeout waiting for health checks")
        self._diagnose_failures()
        return False
    
    def _ensure_ghcr_login(self):
        """Ensure ghcr.io authentication"""
        try:
            subprocess.run(["docker", "login", "ghcr.io"], 
                         capture_output=True, timeout=10)
        except Exception:
            pass  # May already be logged in
    
    def _diagnose_failures(self):
        """Diagnose and report Docker failures"""
        print("\n[Docker] Diagnosing failures...")
        for svc in self.required_services:
            result = subprocess.run(
                ["docker", "logs", f"firecrawl-{svc}", "--tail", "50"],
                capture_output=True, text=True
            )
            if result.returncode == 0 and result.stdout:
                print(f"\n--- {svc} logs ---")
                print(result.stdout[-2000:])
    
    def stop(self):
        """Stop Firecrawl stack"""
        subprocess.run(
            ["docker", "compose", "-f", str(self.compose_file), "down"],
            capture_output=True
        )
    
    def restart_failed(self):
        """Restart only failed services"""
        subprocess.run(
            ["docker", "compose", "-f", str(self.compose_file), "restart"],
            capture_output=True
        )

    def ensure_running(self) -> bool:
        """Ensure Firecrawl is running, start if not"""
        if self.is_running():
            return True
        return self.start()


class UniversalScraper:
    """Main scraper orchestrating all engines with fallback"""
    
    ENGINE_PRIORITY = ["firecrawl", "crawlee", "playwright", "scrapy"]
    
    def __init__(self, use_docker_firecrawl: bool = True, auto_firecrawl: bool = True):
        self.use_docker_firecrawl = use_docker_firecrawl
        self.auto_firecrawl = auto_firecrawl
        self.docker_manager = DockerFirecrawlManager() if use_docker_firecrawl else None
        self.groq_crawler = None
        self.results_history = []
        
        # Ensure output directory exists
        OUTPUT_DIR.mkdir(exist_ok=True)
    
    async def initialize(self):
        """Initialize all components"""
        print("[Init] Initializing universal scraper...")
        
        # Initialize Groq + Crawlee for LLM features
        try:
            from scraper.engines.groq_llm_engine import CrawleeLLMCrawler
            groq_key = os.getenv("GROQ_API_KEY") or self._get_groq_key_from_env()
            if groq_key:
                self.groq_crawler = CrawleeLLMCrawler(groq_key, model="groq/compound")
                await self.groq_crawler.initialize({"use_browser": True, "headless": True})
                print("[Init] Groq + Crawlee LLM ready")
        except Exception as e:
            print(f"[Init] Groq LLM not available: {e}")
        
        # Initialize Firecrawl Docker if requested (auto or explicit)
        if self.use_docker_firecrawl and self.docker_manager:
            if self.auto_firecrawl:
                # Auto-start if needed (lazy initialization)
                print("[Init] Firecrawl auto-mode enabled")
            else:
                # Explicit start
                if not self.docker_manager.is_running():
                    print("[Init] Firecrawl Docker not running, starting...")
                    success = self.docker_manager.start()
                    if not success:
                        print("[Init] WARNING: Firecrawl Docker failed to start, continuing without it")
                        self.use_docker_firecrawl = False
                else:
                    print("[Init] Firecrawl Docker already running")
    
    def _get_groq_key_from_env(self) -> Optional[str]:
        """Read Groq key from .env.firecrawl"""
        if ENV_FILE.exists():
            with open(ENV_FILE) as f:
                for line in f:
                    if line.startswith("OPENAI_API_KEY="):
                        return line.split("=", 1)[1].strip()
        return None
    
    def determine_engines_for_task(self, task: ScrapeTask) -> List[str]:
        """Determine best engines for the task"""
        engines = []
        
        # Check if task needs JavaScript rendering
        needs_js = any("amazon" in u or "flipkart" in u or "dynamic" in task.goal.lower() 
                      for u in task.urls)
        
        # Check if task needs PDF processing
        needs_pdf = any(u.endswith(".pdf") for u in task.urls)
        needs_pdf = needs_pdf or getattr(task, 'pdf', False)
        
        # Check if task needs screenshot
        needs_screenshot = getattr(task, 'screenshot', False)
        
        # Check if task needs LLM extraction
        needs_llm_extraction = bool(task.schema or getattr(task, 'extract_schema', None))
        
        # Check if task needs anti-bot handling
        needs_antibot = any("amazon" in u or "flipkart" in u or "linkedin" in u 
                           for u in task.urls)
        
        # Check for anti-bot indicators in goal
        antibot_keywords = ["cloudflare", "akamai", "incapsula", "perimeterx", "datadome", "captcha", "challenge", "blocked", "rate limit"]
        if any(kw in task.goal.lower() for kw in antibot_keywords):
            needs_antibot = True
        
        # Build engine list based on requirements - FIRECRAWL FIRST for anti-bot/PDF/screenshot/LLM
        if (needs_antibot or needs_pdf or needs_screenshot or needs_llm_extraction) and self.use_docker_firecrawl:
            engines.append("firecrawl")
        
        if needs_js or needs_antibot:
            engines.append("playwright")
            engines.append("crawlee")
        
        if needs_pdf and self.use_docker_firecrawl:
            if "firecrawl" not in engines:
                engines.append("firecrawl")
        
        if needs_screenshot and self.use_docker_firecrawl:
            if "firecrawl" not in engines:
                engines.append("firecrawl")
        
        if needs_llm_extraction and self.use_docker_firecrawl:
            if "firecrawl" not in engines:
                engines.append("firecrawl")
        
        # Always add scrapy as fallback
        engines.append("scrapy")
        
        # Add crawlee if not present
        if "crawlee" not in engines:
            engines.append("crawlee")
        
        # Remove duplicates while preserving order
        seen = set()
        unique_engines = []
        for e in engines:
            if e not in seen:
                seen.add(e)
                unique_engines.append(e)
        
        return unique_engines
    
    async def scrape_with_fallback(self, task: ScrapeTask) -> ScrapeResult:
        """Scrape with automatic engine fallback"""
        engines = task.engines or self.determine_engines_for_task(task)
        errors = []
        output_files = []
        
        print(f"\n[Scrape] Task: {task.query}")
        print(f"[Scrape] URLs: {task.urls}")
        print(f"[Scrape] Engine priority: {engines}")
        
        for engine in engines:
            if engine == "firecrawl" and not self.use_docker_firecrawl:
                errors.append("firecrawl: Docker not available")
                continue
            
            # Auto-ensure Firecrawl is running when firecrawl engine is selected
            if engine == "firecrawl" and self.docker_manager:
                if not self.docker_manager.ensure_running():
                    errors.append("firecrawl: Failed to start Docker")
                    continue
            
            print(f"\n[Scrape] Trying engine: {engine}")
            
            try:
                if engine == "firecrawl":
                    result, files = await self._scrape_firecrawl(task)
                else:
                    result, files = await self._scrape_local(engine, task)
                
                if result and (result.get("success") or result.get("items", 0) > 0):
                    output_files.extend(files)
                    return ScrapeResult(
                        task=task,
                        success=True,
                        engine_used=engine,
                        data=result,
                        errors=errors,
                        timestamp=datetime.now().isoformat(),
                        output_files=output_files
                    )
                else:
                    errors.append(f"{engine}: No data returned")
                    
            except Exception as e:
                error_msg = f"{engine}: {str(e)}"
                print(f"[Scrape] {error_msg}")
                errors.append(error_msg)
                
                # If Firecrawl fails, try to restart Docker
                if engine == "firecrawl" and self.docker_manager:
                    print("[Scrape] Firecrawl failed, attempting Docker restart...")
                    self.docker_manager.restart_failed()
                    await asyncio.sleep(10)
        
        # All engines failed
        return ScrapeResult(
            task=task,
            success=False,
            engine_used="none",
            data=None,
            errors=errors,
            timestamp=datetime.now().isoformat(),
            output_files=[]
        )
    
    async def _scrape_local(self, engine: str, task: ScrapeTask) -> tuple:
        """Scrape using local engines (scrapy, playwright, crawlee)"""
        # Use the project's scrape_async function since we're in async context
        goal = task.goal
        if task.schema:
            goal += f" Schema: {json.dumps(task.schema)}"
        
        all_results = []
        all_files = []
        
        for url in task.urls:
            try:
                result, files = await scrape_async(
                    url, 
                    goal, 
                    max_pages=task.max_pages,
                    engine=engine
                )
                all_results.append({
                    "url": url,
                    "result": result.__dict__ if hasattr(result, '__dict__') else str(result)
                })
                all_files.extend([str(f) for f in files.values()])
            except Exception as e:
                all_results.append({"url": url, "error": str(e)})
        
        return {"success": True, "items": len(all_results), "results": all_results}, all_files
    
    async def _scrape_firecrawl(self, task: ScrapeTask) -> tuple:
        """Scrape using Firecrawl Docker API"""
        # Use firecrawl-py client
        try:
            from firecrawl import FirecrawlApp
            app = FirecrawlApp(api_url="http://localhost:3002", api_key="local-dev")
            
            all_results = []
            for url in task.urls:
                result = app.scrape_url(
                    url,
                    formats=["markdown", "html"],
                    only_main_content=True
                )
                # Convert result to serializable dict
                if hasattr(result, "model_dump"):
                    data = result.model_dump()
                    markdown = getattr(result, "markdown", None)
                    html = getattr(result, "html", None)
                    metadata = result.metadata.model_dump() if hasattr(result.metadata, "model_dump") else dict(result.metadata)
                else:
                    data = dict(result) if result else {}
                    markdown = data.get("markdown")
                    html = data.get("html")
                    metadata = data.get("metadata", {})
                
                all_results.append({
                    "url": url,
                    "result": data,
                    "markdown": markdown,
                    "html": html,
                    "metadata": metadata
                })
            
            # Save to output
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"firecrawl_{timestamp}.json"
            filepath = OUTPUT_DIR / filename
            with open(filepath, "w") as f:
                json.dump(all_results, f, indent=2)
            
            return {"success": True, "items": len(all_results)}, [str(filepath)]
        except Exception as e:
            raise Exception(f"Firecrawl API error: {e}")
    
    async def extract_structured(self, task: ScrapeTask) -> Dict:
        """Use Groq LLM for structured extraction"""
        if not self.groq_crawler:
            return {"error": "Groq LLM not initialized"}
        
        # Scrape first, then extract
        scrape_result = await self.scrape_with_fallback(task)
        
        if not scrape_result.success:
            return {"error": "Scraping failed, cannot extract"}
        
        # Extract content from scrape result - handle different engine result formats
        content = None
        
        # Format 1: Firecrawl returns {'success': True, 'items': N} with data in output files
        # Format 2: Local engines return data with 'results' key
        # Format 3: Direct result data
        
        if scrape_result.data:
            if "results" in scrape_result.data:
                # Format 2: Local engines
                for item in scrape_result.data["results"]:
                    if "result" in item and item["result"]:
                        content = str(item["result"])[:10000]
                        break
            elif "data" in scrape_result.data and isinstance(scrape_result.data["data"], dict):
                # Format 3: Direct data
                content = str(scrape_result.data["data"])[:10000]
            elif "items" in scrape_result.data and scrape_result.output_files:
                # Format 1: Firecrawl - read from output file
                import json
                for filepath in scrape_result.output_files:
                    try:
                        with open(filepath, 'r') as f:
                            file_data = json.load(f)
                            if isinstance(file_data, list) and file_data:
                                content = str(file_data[0].get("result", {}))[:10000]
                            elif isinstance(file_data, dict):
                                content = str(file_data)[:10000]
                            break
                    except Exception:
                        continue
        
        if not content:
            return {"error": "No content to extract"}
        
        try:
            extract_result = self.groq_crawler.llm.extract(
                content, 
                task.schema or {"type": "object", "properties": {}},
                task.goal
            )
            if extract_result.success:
                return extract_result.data
        except Exception as e:
            print(f"[Extract] Error: {e}")
        
        return {"error": "Extraction failed"}
    
    async def multi_site_scrape(self, 
                                sites: Dict[str, List[str]], 
                                goal: str,
                                schema: Optional[Dict] = None,
                                engines: Optional[List[str]] = None) -> Dict[str, ScrapeResult]:
        """Scrape multiple sites with same goal"""
        results = {}
        
        for site_name, urls in sites.items():
            print(f"\n{'='*60}")
            print(f"[MultiScrape] Site: {site_name}")
            print(f"{'='*60}")
            
            task = ScrapeTask(
                query=f"{site_name}: {goal}",
                urls=urls,
                goal=goal,
                schema=schema,
                engines=engines,
                max_pages=10
            )
            
            result = await self.scrape_with_fallback(task)
            results[site_name] = result
            
            # Small delay between sites
            await asyncio.sleep(2)
        
        return results
    
    async def close(self):
        """Cleanup"""
        if self.groq_crawler:
            await self.groq_crawler.shutdown()
        if self.docker_manager:
            # Optionally stop Docker
            pass


async def main():
    """Main entry point for command-line usage"""
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Universal Scraper - Multi-engine with auto-fallback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Simple scrape
  python universal_scraper.py --query "product info" --url "https://example.com" --goal "Extract title and price"
  
  # Multi-site price comparison
  python universal_scraper.py --multi-site \
    --site amazon "https://amazon.in/s?k=phones+20000+25000" \
    --site flipkart "https://flipkart.com/search?q=phones+20000+25000" \
    --goal "Extract phone name, price, rating, link" \
    --schema '{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"rating":{"type":"string"},"link":{"type":"string"}}}'
  
  # Structured extraction with LLM
  python universal_scraper.py --url "https://site.com" --goal "Extract products" \
    --schema '{"type":"object","properties":{"products":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"}}}}}}'
  
  # With Firecrawl Docker
  python universal_scraper.py --url "https://site.com" --goal "Extract" --use-firecrawl
        """
    )
    
    parser.add_argument("--query", help="Search query/description")
    parser.add_argument("--url", action="append", help="URL to scrape (can repeat)")
    parser.add_argument("--goal", help="Extraction goal/instruction")
    parser.add_argument("--schema", help="JSON schema for structured extraction")
    parser.add_argument("--schema-file", help="Path to JSON schema file for structured extraction")
    parser.add_argument("--max-pages", type=int, default=10, help="Max pages per URL")
    parser.add_argument("--engine", action="append", help="Force specific engine(s)")
    parser.add_argument("--use-firecrawl", action="store_true", default=True, help="Enable Firecrawl Docker (default: True)")
    parser.add_argument("--no-firecrawl", action="store_true", help="Disable Firecrawl Docker")
    
    # Multi-site options
    parser.add_argument("--multi-site", action="store_true", help="Multi-site mode")
    parser.add_argument("--site", action="append", nargs=2, metavar=("NAME", "URL"),
                       help="Add site for multi-site mode (name url)")
    
    args = parser.parse_args()
    
    # Parse schema
    schema = None
    if args.schema_file:
        try:
            with open(args.schema_file) as f:
                schema = json.load(f)
        except Exception as e:
            print(f"ERROR: Failed to read schema file: {e}")
            sys.exit(1)
    elif args.schema:
        try:
            schema = json.loads(args.schema)
        except json.JSONDecodeError:
            print("ERROR: Invalid JSON schema")
            sys.exit(1)
    
    # Initialize scraper
    use_firecrawl = args.use_firecrawl and not args.no_firecrawl
    scraper = UniversalScraper(use_docker_firecrawl=use_firecrawl)
    await scraper.initialize()
    
    try:
        if args.multi_site and args.site:
            # Multi-site mode
            sites = {name: [url] for name, url in args.site}
            results = await scraper.multi_site_scrape(sites, args.goal or args.query, schema, args.engine)
            
            # Print summary
            print("\n" + "="*60)
            print("MULTI-SITE RESULTS SUMMARY")
            print("="*60)
            for site, result in results.items():
                status = "SUCCESS" if result.success else "FAILED"
                print(f"  {site}: {status} (engine: {result.engine_used})")
                if result.errors:
                    for err in result.errors:
                        print(f"    Error: {err}")
        
        elif args.url:
            # Single task mode
            task = ScrapeTask(
                query=args.query or "Extract data",
                urls=args.url,
                goal=args.goal or "Extract all relevant information",
                schema=schema,
                engines=args.engine,
                max_pages=args.max_pages
            )
            
            result = await scraper.scrape_with_fallback(task)
            
            print("\n" + "="*60)
            print("SCRAPE RESULT")
            print("="*60)
            print(f"Success: {result.success}")
            print(f"Engine: {result.engine_used}")
            print(f"Output files: {result.output_files}")
            if result.errors:
                print("Errors:")
                for err in result.errors:
                    print(f"  - {err}")
            
            # Structured extraction if requested
            if schema and result.success:
                print("\n[Extract] Running structured extraction...")
                extracted = await scraper.extract_structured(task)
                print(f"Extracted: {json.dumps(extracted, indent=2)}")
        
        else:
            parser.print_help()
            sys.exit(1)
    
    finally:
        await scraper.close()


if __name__ == "__main__":
    asyncio.run(main())