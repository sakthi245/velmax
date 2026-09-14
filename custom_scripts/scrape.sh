#!/bin/bash
# Universal Scraper Wrapper - Linux/macOS
# Usage: ./scrape.sh "your query" --url "https://site.com" --goal "extract info"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT"

# Activate virtual environment
source .venv/bin/activate

# Run the universal scraper
python custom_scripts/universal_scraper.py "$@"