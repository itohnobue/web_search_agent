# Web Search Agent

A web search agent for any LLM-based service or model (i.e. Claude Code) which gives ability to process 50+ results (web links) for each search request.

## Quick Start (Highly Recommended)

1. **Copy files to your project**: Put `tools/` and `agents/` folders into your LLM (Claude Code) working directory

2. **Add instructions from CLAUDE.md to your model instructions file**: Copy the contents of `CLAUDE.md` into your project's instruction file (create one if it doesn't exist)

3. **Test it**: Ask your LLM (Claude Code) to perform a web search, for example: *"Search the web and bring me a list of most beautiful Hokusai paintings, explaining why they are great"*

The wrapper scripts will automatically install **uv** (if needed), which handles Python and all dependencies.

## What it does and why you may need it (read this first)

The main purpose of this agent is to bring extensive web search capabilities to LLMs so they'll be able to do deep researches by using 50+ web links for each web search operation. It is based on DuckDuckGo search results because it's the only search engine I was able to find which allows such usage.

Most services and tools (including Claude Code) are restricted to use only ~10 first results from their default web search engine which greatly limits their capabilities.

The only exception I am aware of is a web Qwen service with Search function which can find & process 100s of websites for each query.

I wanted to built an universal agent which gives Qwen Search-like capabilities to any other LLM and here is the result.

I am currently using it with Claude Code but it's made model-agnostic and theoretically can be applied to any other service or model out there, with minor instructions tweaking (see `CLAUDE.md` for details).

According to my tests (I am using it for all my web search requests) this agent tremendously improve any research-based workflows like solving tricky bugs, doing tech researches and any others, where amount of processed information can be the game changer.

---

## Features

- **Autonomous Search + Fetch**: Single command to search, filter, fetch, and report
- **Smart Filtering**: Automatically filters blocked domains, index pages, and low-content URLs
- **Jina Reader Fallback**: Uses Jina Reader API for sites that block direct scraping
- **Streaming Pipeline**: Search and fetch run in parallel (30-40% faster)
- **Multiple Output Formats**: Raw text, JSON, or Markdown reports
- **Zero Setup**: Uses uv with inline dependencies - no manual venv or pip needed

## Usage

### Using Wrapper Scripts (Recommended)

The wrapper scripts handle everything automatically:

```bash
# Linux/macOS
./tools/web_search.sh "your search query"

# Windows
tools\web_search.bat "your search query"
```

On first run, the scripts will:
1. Install uv if not present
2. uv will install Python if needed
3. uv will install dependencies (httpx, ddgs) from inline metadata

### Direct with uv

If you have uv installed:

```bash
uv run tools/web_research.py "your search query"
```

### Requirements

- **uv**: Installed automatically by wrapper scripts, or manually via:
  ```bash
  # Linux/macOS
  curl -LsSf https://astral.sh/uv/install.sh | sh

  # Windows
  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
  ```
- **Python 3.11+**: Installed automatically by uv if needed
- **Dependencies**: Defined inline in `web_research.py` (PEP 723), installed automatically

## CLI Examples

```bash
# Basic search (fetches ALL pages, outputs raw text)
./tools/web_search.sh "AI trends 2025"

# Limit number of pages to fetch
./tools/web_search.sh "query" --fetch 30

# Different output formats
./tools/web_search.sh "query" -o json      # Structured JSON
./tools/web_search.sh "query" -o markdown  # Formatted report
./tools/web_search.sh "query" -o raw       # Plain text (default)

# Verbose mode (shows Jina fallbacks, errors)
./tools/web_search.sh "query" -v
```

## CLI Options

| Option | Description | Default |
|--------|-------------|---------|
| `-s, --search N` | Number of search results | 50 |
| `-f, --fetch N` | Max pages to fetch (0=ALL) | 0 (ALL) |
| `-m, --max-length N` | Max chars per page | 4000 |
| `-o, --output FORMAT` | json, raw, markdown | raw |
| `-t, --timeout N` | Fetch timeout (seconds) | 20 |
| `-c, --concurrent N` | Max concurrent connections | 10 |
| `-q, --quiet` | Suppress progress | false |
| `-v, --verbose` | Enable debug logging | false |

## Example Output

```
Researching: "AI agents best practices 2025"
  Mode: streaming pipeline (search + fetch in parallel)
  Done: 43/43 pages (7 via Jina) [6 filtered] (165,448 chars)
```

**Output explanation**:
- `43/43 pages`: Successfully fetched / total URLs found
- `(7 via Jina)`: Pages that used Jina Reader fallback (blocked sites)
- `[6 filtered]`: URLs blocked during search (domains, patterns)
- `(165,448 chars)`: Total content collected

## Blocked Domains

The following domains are automatically filtered (require login or block scraping):
- reddit.com, twitter.com, x.com, facebook.com
- youtube.com, tiktok.com, instagram.com
- linkedin.com, medium.com

## License

MIT License
