## Web Research

**ALWAYS use this approach when any internet search is needed.**

### Workflow

1. Read the web-searcher agent: `agents/web-searcher.md`
2. Use internal web search tool with original query for quick results
3. Run external tool for comprehensive deep coverage:
   ```bash
   # Linux/macOS
   ./tools/web_search.sh "query"

   # Windows
   tools\web_search.bat "query"
   ```
4. Synthesize results from both sources into a report

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

### Python Environment

The wrapper scripts automatically create a virtual environment in `env-ai/` and install dependencies (`httpx`, `ddgs`).

To set up manually:
```bash
# Linux/macOS
python3 -m venv env-ai
env-ai/bin/pip install httpx ddgs

# Windows
python -m venv env-ai
env-ai\Scripts\pip.exe install httpx ddgs
```
