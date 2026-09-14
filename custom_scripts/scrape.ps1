<#
.SYNOPSIS
    Universal Scraper - Multi-engine scraping with auto-fallback
    
.DESCRIPTION
    Scrapes websites using all available engines (Scrapy, Playwright, Crawlee, Firecrawl)
    with automatic fallback. Supports multi-site scraping, structured extraction,
    and auto-manages Firecrawl Docker container.
    
.EXAMPLE
    # Simple scrape
    .\scrape.ps1 -Query "product info" -Url "https://example.com" -Goal "Extract title and price"
    
.EXAMPLE
    # Multi-site price comparison (Amazon + Flipkart)
    .\scrape.ps1 -MultiSite `
        -Site @("amazon", "https://amazon.in/s?k=phones+20000+25000") `
        -Site @("flipkart", "https://flipkart.com/search?q=phones+20000+25000") `
        -Goal "Extract phone name, price, rating, product link" `
        -Schema '{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"},"rating":{"type":"string"},"link":{"type":"string"}}}'
    
.EXAMPLE
    # Structured extraction with LLM
    .\scrape.ps1 -Url "https://site.com" -Goal "Extract all products with prices" `
        -Schema '{"type":"object","properties":{"products":{"type":"array","items":{"type":"object","properties":{"name":{"type":"string"},"price":{"type":"string"}}}}}}'
    
.EXAMPLE
    # With Firecrawl Docker (for anti-bot sites)
    .\scrape.ps1 -Url "https://amazon.in/product" -Goal "Extract product details" -UseFirecrawl
    
.PARAMETER Query
    Search query or description of what to scrape
    
.PARAMETER Url
    URL(s) to scrape (can specify multiple)
    
.PARAMETER Goal
    Extraction goal/instruction for the scraper
    
.PARAMETER Schema
    JSON schema for structured extraction (Groq LLM)
    
.PARAMETER MaxPages
    Maximum pages to crawl per URL (default: 10)
    
.PARAMETER Engine
    Force specific engine(s): scrapy, playwright, crawlee, firecrawl
    
.PARAMETER UseFirecrawl
    Enable Firecrawl Docker (auto-starts if not running)
    
.PARAMETER NoFirecrawl
    Disable Firecrawl Docker
    
.PARAMETER MultiSite
    Enable multi-site scraping mode
    
.PARAMETER Site
    Site specification for multi-site mode: @("name", "url")
#>

param(
    [string]$Query,
    [string[]]$Url,
    [string]$Goal,
    [string]$Schema,
    [string]$SchemaFile,
    [int]$MaxPages = 10,
    [string[]]$Engine,
    [switch]$UseFirecrawl,
    [switch]$NoFirecrawl,
    [switch]$MultiSite,
    [string[]]$Site
)

# Set working directory to project root
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

# Build arguments for Python script
$Args = @()

if ($Query) { $Args += "--query", $Query }
if ($Url) { foreach ($u in $Url) { $Args += "--url", $u } }
if ($Goal) { $Args += "--goal", $Goal }
if ($Schema) { $Args += "--schema", $Schema }
if ($SchemaFile) { $Args += "--schema-file", $SchemaFile }
if ($MaxPages) { $Args += "--max-pages", $MaxPages }
if ($Engine) { foreach ($e in $Engine) { $Args += "--engine", $e } }
if ($UseFirecrawl) { $Args += "--use-firecrawl" }
if ($NoFirecrawl) { $Args += "--no-firecrawl" }
if ($MultiSite) { $Args += "--multi-site" }
if ($Site) { 
    # Site parameter comes as pairs: name1 url1 name2 url2 ...
    for ($i = 0; $i -lt $Site.Count; $i += 2) {
        if ($i + 1 -lt $Site.Count) {
            $Args += "--site", $Site[$i], $Site[$i + 1]
        }
    }
}

# Run the universal scraper
python "custom_scripts/universal_scraper.py" @Args