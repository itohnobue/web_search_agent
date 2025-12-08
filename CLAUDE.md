# Web Search Agent for Claude Code

This repository contains a web research agent for use with Claude Code CLI.

## Quick Start

1. Clone this repository
2. Run the wrapper script or Python directly:

```bash
# Using wrapper script (auto-creates venv)
./tools/web_search.sh "your search query"

# Or directly with Python
python3 tools/web_research.py "your search query"
```

---

## Agents

The `agents/` folder contains agent instructions for Claude Code.
Load the `web-searcher.md` agent when performing web research tasks.

### Agent Usage Workflow

1. Read the agent file: `agents/web-searcher.md`
2. Apply the instructions to your web research task
3. Use the tool with appropriate options

---

## Web Research Tool

### Workflow

1. Use Claude Code's built-in web search for quick results
2. Run the external tool for comprehensive deep coverage:
   ```bash
   # Linux/macOS: Use the wrapper script
   ./tools/web_search.sh "query"

   # Windows: Use the batch wrapper script
   tools\web_search.bat "query"
   ```
3. Synthesize results from both sources into a report

### Tool Location

`web_research.py` is in the `tools/` folder.

### CLI Options

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

---

## Python Environment Setup

### Virtual Environment Configuration
Set up a Python 3.11+ virtual environment in `env-ai/` folder.

### Setup Instructions (Linux/macOS)
1. Create virtual environment: `python3 -m venv env-ai`
2. Install required packages:
   ```bash
   env-ai/bin/pip install httpx ddgs
   ```
3. Run Python scripts using:
   ```bash
   env-ai/bin/python tools/web_research.py "query"
   ```

### Setup Instructions (Windows)
1. Create virtual environment: `python -m venv env-ai`
2. Install required packages:
   ```cmd
   env-ai\Scripts\pip.exe install httpx ddgs
   ```
3. Run Python scripts with UTF-8 encoding:
   ```cmd
   set PYTHONIOENCODING=utf-8 && env-ai\Scripts\python.exe tools\web_research.py "query"
   ```

### Usage
- The wrapper scripts (`tools/web_search.sh` and `tools/web_search.bat`) automatically create and use the virtual environment
- Use this environment for all web searches via `tools/web_research.py`
