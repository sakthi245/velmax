@echo off
REM Universal Scraper Wrapper - Easy command-line access
REM Usage: scrape.bat --query "your query" --url "https://site.com" --goal "extract info"

cd /d "%~dp0.."
call .venv\Scripts\activate.bat

python custom_scripts\universal_scraper.py %*