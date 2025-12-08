# Web Search Agent

A powerful web research tool for Claude Code that combines DuckDuckGo search with intelligent web scraping.

## Quick Start (Recommended)

1. **Copy files to your project**: Put `tools/` and `agents/` folders into your Claude Code working directory

2. **Add instructions to CLAUDE.md**: Copy the contents of `CLAUDE.md` into your project's `CLAUDE.md` file (create one if it doesn't exist)

3. **Test it**: Ask Claude to perform a web search, for example: *"Search the web for latest AI trends in 2025"*

The wrapper scripts will automatically install **uv** (if needed), which handles Python and all dependencies.

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
