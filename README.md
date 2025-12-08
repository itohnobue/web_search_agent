# Web Search Agent

A powerful web research tool for Claude Code that combines DuckDuckGo search with intelligent web scraping.

## Features

- **Autonomous Search + Fetch**: Single command to search, filter, fetch, and report
- **Smart Filtering**: Automatically filters blocked domains, index pages, and low-content URLs
- **Jina Reader Fallback**: Uses Jina Reader API for sites that block direct scraping
- **Streaming Pipeline**: With `httpx` + `ddgs` installed, search and fetch run in parallel (30-40% faster)
- **Multiple Output Formats**: Raw text, JSON, or Markdown reports

## Installation

### Quick Start (Recommended)

The wrapper scripts automatically create a Python virtual environment and install dependencies:

```bash
# Linux/macOS
./tools/web_search.sh "your search query"

# Windows
tools\web_search.bat "your search query"
```

### Manual Setup

```bash
# Create virtual environment
python3 -m venv env-ai

# Install dependencies (optional but recommended)
env-ai/bin/pip install httpx ddgs

# Run directly
env-ai/bin/python tools/web_research.py "your search query"
```

### Dependencies

- **Required**: Python 3.11+ (standard library only for basic functionality)
- **Optional**: `httpx` (3x faster parallel fetching), `ddgs` (better DuckDuckGo results)

## Usage

```bash
# Basic search (fetches ALL pages, outputs raw text)
python3 tools/web_research.py "AI trends 2025"

# Limit number of pages to fetch
python3 tools/web_research.py "query" --fetch 30

# Different output formats
python3 tools/web_research.py "query" -o json      # Structured JSON
python3 tools/web_research.py "query" -o markdown  # Formatted report
python3 tools/web_research.py "query" -o raw       # Plain text (default)

# Verbose mode (shows Jina fallbacks, errors)
python3 tools/web_research.py "query" -v
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

## Claude Code Integration

This repository includes a `CLAUDE.md` file with instructions for Claude Code. Copy the `agents/web-searcher.md` file to your project's agents folder to use it as an in-session agent.

## License

MIT License
