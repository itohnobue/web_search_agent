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

### Requirements

The wrapper scripts use **uv** for Python and dependency management. uv will be installed automatically if not present.

- Dependencies are defined inline in `web_research.py` (PEP 723)
- No manual venv or pip setup needed
- uv handles Python installation if needed
