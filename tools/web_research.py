#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx", "ddgs"]
# ///
# -*- coding: utf-8 -*-
"""
Web Research Tool - Autonomous Search + Fetch + Report

Unified tool combining search and fetch into a single optimized workflow:
1. Search via DuckDuckGo (50 results)
2. Filter and deduplicate URLs during search (early filtering)
3. Fetch content in parallel with connection reuse and Jina fallback
4. Output combined results

Usage:
    python web_research.py "search query"
    python web_research.py "Mac Studio M3 Ultra LLM" --fetch 50
    python web_research.py "AI trends 2025" -o markdown

Requirements:
    - Python 3.11+ (standard library only)
    - Optional: pip install httpx (3x faster fetching)
    - Optional: pip install ddgs (better DuckDuckGo results)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import random
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html import unescape
from typing import Callable, Dict, List, Optional, Set, Tuple

# =============================================================================
# LOGGING CONFIGURATION
# =============================================================================

logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr
)
logger = logging.getLogger(__name__)

# =============================================================================
# CONSTANTS
# =============================================================================

USER_AGENTS: Tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:123.0) Gecko/20100101 Firefox/123.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 Safari/605.1.15",
)

# Domains that block scraping or require login
BLOCKED_DOMAINS: Tuple[str, ...] = (
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "youtube.com", "tiktok.com", "instagram.com",
    "linkedin.com", "medium.com",  # Require login / block scraping
)

SKIP_URL_PATTERNS: Tuple[str, ...] = (
    # File types
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.gif$",
    # Auth/commerce pages
    r"/login", r"/signin", r"/signup", r"/cart", r"/checkout",
    r"amazon\.com/.*/(dp|gp)/", r"ebay\.com/itm/",
    # Index/aggregation pages (low content density)
    r"/tag/", r"/tags/", r"/category/", r"/categories/",
    r"/topic/", r"/topics/", r"/archive/", r"/page/\d+",
    # Shopping/store pages (low content density)
    r"/shop/", r"/store/", r"/buy/", r"/product/", r"/products/",
)

# Jina Reader API for fallback on blocked/complex sites
JINA_READER_URL = "https://r.jina.ai/"

# =============================================================================
# COMPILED REGEX PATTERNS (Performance optimization)
# =============================================================================

RE_STRIP_TAGS = re.compile(r"<(script|style|nav|footer|header|aside|noscript)[^>]*>.*?</\1>", re.DOTALL | re.IGNORECASE)
RE_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)
RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_BLOCK_END = re.compile(r"</(p|div|h[1-6]|li|tr|article|section)>", re.IGNORECASE)
RE_LI = re.compile(r"<li[^>]*>", re.IGNORECASE)
RE_ALL_TAGS = re.compile(r"<[^>]+>")
RE_SPACES = re.compile(r"[ \t]+")
RE_LEADING_SPACE = re.compile(r"\n[ \t]+")
RE_MULTI_NEWLINE = re.compile(r"\n{3,}")
RE_WHITESPACE = re.compile(r"\s+")
RE_SKIP_PATTERNS = tuple(re.compile(p) for p in SKIP_URL_PATTERNS)

# DuckDuckGo parsing patterns
RE_DDG_RESULT_BLOCK = re.compile(r'<div[^>]*class="[^"]*result[^"]*results_links')
RE_DDG_LINK = re.compile(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)
RE_DDG_SNIPPET = re.compile(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', re.DOTALL | re.IGNORECASE)

# =============================================================================
# OPTIONAL DEPENDENCIES
# =============================================================================

try:
    import httpx
    HAS_HTTPX = True
except ImportError:
    HAS_HTTPX = False

try:
    from ddgs import DDGS
    HAS_DDGS = True
except ImportError:
    HAS_DDGS = False

# =============================================================================
# CONFIGURATION DATACLASS
# =============================================================================

@dataclass
class ResearchConfig:
    """Configuration for research workflow."""
    query: str
    fetch_count: int = 0  # 0 = fetch ALL URLs
    max_content_length: int = 4000
    timeout: int = 20
    quiet: bool = False
    min_content_length: int = 200
    max_concurrent: int = 10
    search_results: int = 50

# =============================================================================
# CUSTOM EXCEPTIONS
# =============================================================================

class SearchError(Exception):
    """Base exception for search errors."""
    pass

class RateLimitError(SearchError):
    """Raised when search engine rate limits requests."""
    pass

# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class SearchResult:
    """Single search result."""
    title: str
    url: str
    snippet: str
    engine: str

@dataclass
class FetchResult:
    """Single fetch result."""
    url: str
    success: bool
    content: str = ""
    title: str = ""
    error: Optional[str] = None
    source: str = "direct"  # "direct" or "jina"

@dataclass
class ResearchResult:
    """Complete research result."""
    query: str
    search_results: List[SearchResult]
    fetch_results: List[FetchResult]
    urls_searched: int
    urls_fetched: int
    urls_filtered: int
    content_chars: int
    jina_fallback_count: int = 0

# =============================================================================
# SSL CONTEXT (Reusable)
# =============================================================================

_SSL_CONTEXT: Optional[ssl.SSLContext] = None

def get_ssl_context() -> ssl.SSLContext:
    """Get or create reusable SSL context."""
    global _SSL_CONTEXT
    if _SSL_CONTEXT is None:
        _SSL_CONTEXT = ssl.create_default_context()
        _SSL_CONTEXT.check_hostname = False
        _SSL_CONTEXT.verify_mode = ssl.CERT_NONE
    return _SSL_CONTEXT

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def clean_text(text: str) -> str:
    """Clean HTML entities and normalize whitespace."""
    if not text:
        return ""
    text = unescape(text)
    text = RE_ALL_TAGS.sub("", text)
    text = RE_WHITESPACE.sub(" ", text)
    return text.strip()

def is_blocked_url(url: str) -> bool:
    """Check if URL should be blocked."""
    url_lower = url.lower()

    for domain in BLOCKED_DOMAINS:
        if domain in url_lower:
            return True

    for pattern in RE_SKIP_PATTERNS:
        if pattern.search(url_lower):
            return True

    return False

def extract_text(html: str) -> str:
    """Extract readable text from HTML using compiled regex patterns."""
    # Remove unwanted elements
    html = RE_STRIP_TAGS.sub("", html)
    html = RE_COMMENTS.sub("", html)

    # Extract title
    title_match = RE_TITLE.search(html)
    title = unescape(title_match.group(1).strip()) if title_match else ""

    # Convert structure to text
    html = RE_BR.sub("\n", html)
    html = RE_BLOCK_END.sub("\n\n", html)
    html = RE_LI.sub("• ", html)

    # Remove remaining tags
    text = RE_ALL_TAGS.sub(" ", html)

    # Clean whitespace
    text = unescape(text)
    text = RE_SPACES.sub(" ", text)
    text = RE_LEADING_SPACE.sub("\n", text)
    text = RE_MULTI_NEWLINE.sub("\n\n", text)
    text = text.strip()

    if title:
        text = f"# {title}\n\n{text}"

    return text

def get_random_user_agent() -> str:
    """Get a random user agent string."""
    return random.choice(USER_AGENTS)

def extract_title_from_content(content: str) -> str:
    """Extract title from markdown-formatted content."""
    if content.startswith("# "):
        newline = content.find("\n")
        if newline > 0:
            return content[2:newline]
    return ""

def is_valid_url(url: str) -> bool:
    """Validate URL format before fetching."""
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False

# =============================================================================
# HTTP UTILITIES
# =============================================================================

def fetch_url_sync(
    url: str,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30
) -> str:
    """Fetch URL synchronously using urllib."""
    if headers is None:
        headers = {}

    headers.setdefault("User-Agent", get_random_user_agent())
    headers.setdefault("Accept", "text/html,application/xhtml+xml")
    headers.setdefault("Accept-Language", "en-US,en;q=0.9")

    req = urllib.request.Request(url, headers=headers)
    ctx = get_ssl_context()

    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise RateLimitError(f"Rate limited (429) by {url.split('/')[2]}")
        raise

# =============================================================================
# DUCKDUCKGO SEARCH (with early URL filtering)
# =============================================================================

class DuckDuckGoSearch:
    """DuckDuckGo search implementation with early URL filtering."""

    BASE_URL = "https://html.duckduckgo.com/html/"

    def search(
        self,
        query: str,
        num_results: int = 50,
        delay: float = 2.0,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[SearchResult]:
        """Search DuckDuckGo for results with early filtering."""
        results: List[SearchResult] = []
        seen_urls: Set[str] = set()

        def add_if_valid(title: str, url: str, snippet: str, engine: str) -> bool:
            """Add result only if URL is valid and not blocked (early filtering)."""
            if url in seen_urls or is_blocked_url(url):
                return False
            seen_urls.add(url)
            results.append(SearchResult(
                title=title,
                url=url,
                snippet=snippet,
                engine=engine
            ))
            if progress_callback:
                progress_callback(len(results), num_results)
            return True

        # Try ddgs library first (better results) with SSL verification disabled
        if HAS_DDGS:
            try:
                # Use explicit DuckDuckGo backend with verify=False
                ddg = DDGS(verify=False)
                ddg_results = ddg.text(query, max_results=num_results * 2)  # Request more to account for filtering
                for r in ddg_results:
                    url = r.get("href", "")
                    if url:
                        add_if_valid(
                            title=r.get("title", ""),
                            url=url,
                            snippet=r.get("body", ""),
                            engine="duckduckgo"
                        )
                    if len(results) >= num_results:
                        break
                if results:
                    return results[:num_results]
            except Exception as e:
                logger.debug(f"ddgs library failed: {e}")

        # Fallback to HTML scraping
        return self._search_html(query, num_results, delay, add_if_valid)

    def _search_html(
        self,
        query: str,
        num_results: int,
        delay: float,
        add_if_valid: Callable[[str, str, str, str], bool]
    ) -> List[SearchResult]:
        """Search using HTML scraping fallback with early filtering."""
        results: List[SearchResult] = []
        consecutive_empty = 0
        max_pages = (num_results // 10) + 3

        for page in range(1, max_pages + 1):
            if consecutive_empty >= 3:
                break

            try:
                params = {"q": query}
                if page > 1:
                    params["s"] = str((page - 1) * 30)

                url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
                html = fetch_url_sync(url)

                # Check for bot detection
                if "anomaly.js" in html or "cc=botnet" in html:
                    logger.warning("DuckDuckGo bot detection triggered")
                    break

                page_results = self._parse_html(html)

                if not page_results:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0

                for title, result_url, snippet in page_results:
                    add_if_valid(title, result_url, snippet, "duckduckgo")

                if page < max_pages:
                    time.sleep(delay)

            except RateLimitError:
                logger.warning("DuckDuckGo rate limited")
                break
            except Exception as e:
                logger.debug(f"DuckDuckGo page {page} failed: {e}")
                consecutive_empty += 1

        # Results are added to parent's list via add_if_valid callback
        return []

    def _parse_html(self, html: str) -> List[Tuple[str, str, str]]:
        """Parse DuckDuckGo HTML results."""
        results: List[Tuple[str, str, str]] = []

        # Split into result blocks
        blocks = RE_DDG_RESULT_BLOCK.split(html)

        for block in blocks[1:]:
            link_match = RE_DDG_LINK.search(block)
            if not link_match:
                continue

            raw_url = link_match.group(1)
            title = clean_text(link_match.group(2))

            if not title or "ad_provider" in raw_url:
                continue

            # Extract real URL
            url = self._extract_url(raw_url)
            if not url:
                continue

            # Extract snippet
            snippet = ""
            snippet_match = RE_DDG_SNIPPET.search(block)
            if snippet_match:
                snippet = clean_text(snippet_match.group(1))

            results.append((title, url, snippet))

        return results

    def _extract_url(self, ddg_url: str) -> Optional[str]:
        """Extract actual URL from DuckDuckGo redirect."""
        if not ddg_url:
            return None

        ddg_url = unescape(ddg_url)

        # Direct URL
        if ddg_url.startswith(("http://", "https://")) and "duckduckgo.com" not in ddg_url:
            return ddg_url

        # Extract from uddg parameter
        if "uddg=" in ddg_url:
            try:
                start = ddg_url.find("uddg=") + 5
                end = ddg_url.find("&", start)
                if end == -1:
                    end = len(ddg_url)
                return urllib.parse.unquote(ddg_url[start:end])
            except Exception:
                pass

        return None

# =============================================================================
# JINA READER FALLBACK
# =============================================================================

# Jina API rate limiting
_last_jina_call: float = 0.0
JINA_MIN_INTERVAL: float = 0.5  # 2 requests/second max

async def fetch_via_jina_async(
    client: "httpx.AsyncClient",
    url: str,
    timeout: int = 20
) -> Optional[str]:
    """Fetch URL content via Jina Reader API (fallback for blocked sites)."""
    global _last_jina_call

    # Rate limiting for Jina API
    import time as time_module
    elapsed = time_module.monotonic() - _last_jina_call
    if elapsed < JINA_MIN_INTERVAL:
        await asyncio.sleep(JINA_MIN_INTERVAL - elapsed)
    _last_jina_call = time_module.monotonic()

    try:
        jina_url = f"{JINA_READER_URL}{url}"
        resp = await client.get(
            jina_url,
            headers={
                "User-Agent": get_random_user_agent(),
                "Accept": "text/plain",
                "X-Return-Format": "text",  # Jina-specific header
            },
            timeout=timeout,  # Use same timeout as direct fetch
            follow_redirects=True
        )
        if resp.status_code == 200:
            content = resp.text
            # Check for Jina error responses
            if any(x in content for x in ["Target URL returned error", "You've been blocked", "SecurityCompromiseError"]):
                return None
            return content
    except Exception as e:
        logger.debug(f"Jina Reader failed for {url}: {e}")
    return None

_last_jina_call_sync: float = 0.0

def fetch_via_jina_sync(url: str, timeout: int = 20) -> Optional[str]:
    """Fetch URL content via Jina Reader API (sync version)."""
    global _last_jina_call_sync

    # Rate limiting for Jina API
    elapsed = time.monotonic() - _last_jina_call_sync
    if elapsed < JINA_MIN_INTERVAL:
        time.sleep(JINA_MIN_INTERVAL - elapsed)
    _last_jina_call_sync = time.monotonic()

    try:
        jina_url = f"{JINA_READER_URL}{url}"
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/plain",
            "X-Return-Format": "text",  # Jina-specific header
        }
        req = urllib.request.Request(jina_url, headers=headers)
        ctx = get_ssl_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            if any(x in content for x in ["Target URL returned error", "You've been blocked", "SecurityCompromiseError"]):
                return None
            return content
    except Exception as e:
        logger.debug(f"Jina Reader failed for {url}: {e}")
    return None

# =============================================================================
# CONTENT FETCHER (with connection reuse and Jina fallback)
# =============================================================================

if HAS_HTTPX:
    async def _fetch_single_async(
        client: "httpx.AsyncClient",
        url: str,
        timeout: int,
        min_content_length: int
    ) -> FetchResult:
        """Fetch single URL using shared client with Jina fallback."""
        # Try direct fetch first
        try:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": get_random_user_agent(),
                    "Accept": "text/html,application/xhtml+xml",
                },
                timeout=timeout,
                follow_redirects=True
            )

            if resp.status_code == 200:
                content = extract_text(resp.text)

                if len(content) >= min_content_length:
                    return FetchResult(
                        url=url,
                        success=True,
                        content=content,
                        title=extract_title_from_content(content),
                        source="direct"
                    )
                # Content too short - try Jina fallback

            elif resp.status_code in (403, 401, 429):
                # Blocked or rate limited - try Jina fallback
                logger.debug(f"HTTP {resp.status_code} for {url}, trying Jina fallback")
            else:
                return FetchResult(
                    url=url,
                    success=False,
                    error=f"HTTP {resp.status_code}"
                )

        except Exception as e:
            logger.debug(f"Direct fetch failed for {url}: {e}")

        # Jina Reader fallback
        jina_content = await fetch_via_jina_async(client, url, timeout)
        if jina_content and len(jina_content) >= min_content_length:
            return FetchResult(
                url=url,
                success=True,
                content=jina_content,
                title=extract_title_from_content(jina_content),
                source="jina"
            )

        return FetchResult(
            url=url,
            success=False,
            error="All fetch methods failed"
        )

    async def fetch_batch_async(
        urls: List[str],
        max_concurrent: int = 10,
        timeout: int = 20,
        min_content_length: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[FetchResult]:
        """Fetch multiple URLs with connection reuse and TaskGroup."""
        completed = 0
        total = len(urls)

        # Use connection pooling
        async with httpx.AsyncClient(
            verify=False,
            limits=httpx.Limits(max_connections=max_concurrent, max_keepalive_connections=max_concurrent),
            timeout=timeout
        ) as client:
            semaphore = asyncio.Semaphore(max_concurrent)

            async def fetch_with_sem(url: str) -> FetchResult:
                nonlocal completed
                async with semaphore:
                    result = await _fetch_single_async(client, url, timeout, min_content_length)
                    completed += 1
                    if progress_callback:
                        progress_callback(completed, total)
                    return result

            # Use TaskGroup for better error handling (Python 3.11+)
            async with asyncio.TaskGroup() as tg:
                tasks = [tg.create_task(fetch_with_sem(url)) for url in urls]

            return [task.result() for task in tasks]

    def fetch_batch(
        urls: List[str],
        max_concurrent: int = 10,
        timeout: int = 20,
        min_content_length: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[FetchResult]:
        """Sync wrapper for batch fetch."""
        return asyncio.run(fetch_batch_async(
            urls, max_concurrent, timeout, min_content_length, progress_callback
        ))

else:
    # Fallback without httpx - sequential fetching with Jina fallback
    def fetch_batch(
        urls: List[str],
        max_concurrent: int = 10,
        timeout: int = 20,
        min_content_length: int = 200,
        progress_callback: Optional[Callable[[int, int], None]] = None
    ) -> List[FetchResult]:
        """Fetch URLs sequentially (fallback without httpx)."""
        results: List[FetchResult] = []
        total = len(urls)

        for i, url in enumerate(urls, 1):
            result = None

            # Try direct fetch
            try:
                html = fetch_url_sync(url, timeout=timeout)
                content = extract_text(html)

                if len(content) >= min_content_length:
                    result = FetchResult(
                        url=url,
                        success=True,
                        content=content,
                        title=extract_title_from_content(content),
                        source="direct"
                    )
            except urllib.error.HTTPError as e:
                if e.code in (403, 401, 429):
                    logger.debug(f"HTTP {e.code} for {url}, trying Jina fallback")
                else:
                    result = FetchResult(url=url, success=False, error=f"HTTP {e.code}")
            except Exception as e:
                logger.debug(f"Direct fetch failed for {url}: {e}")

            # Jina fallback if direct failed or content too short
            if result is None:
                jina_content = fetch_via_jina_sync(url, timeout)
                if jina_content and len(jina_content) >= min_content_length:
                    result = FetchResult(
                        url=url,
                        success=True,
                        content=jina_content,
                        title=extract_title_from_content(jina_content),
                        source="jina"
                    )
                else:
                    result = FetchResult(url=url, success=False, error="All fetch methods failed")

            results.append(result)

            if progress_callback:
                progress_callback(i, total)

        return results

# =============================================================================
# STREAMING SEARCH + FETCH PIPELINE
# =============================================================================

if HAS_HTTPX:
    async def search_and_fetch_streaming(
        config: ResearchConfig,
        progress_callback: Optional[Callable[[str, int, int], None]] = None
    ) -> ResearchResult:
        """
        Streaming pipeline: start fetching URLs as soon as they arrive from search.

        This overlaps search and fetch phases for better performance.
        """
        all_search_results: List[SearchResult] = []
        all_fetch_results: List[FetchResult] = []
        seen_urls: Set[str] = set()
        filtered_count = [0]  # Use list for mutable counter in closure
        fetch_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def search_producer() -> None:
            """Producer: Search and add URLs to fetch queue."""
            nonlocal all_search_results

            def add_to_queue(title: str, url: str, snippet: str, engine: str) -> bool:
                # Validate URL format first
                if not is_valid_url(url):
                    filtered_count[0] += 1
                    return False
                if url in seen_urls:
                    return False
                if is_blocked_url(url):
                    filtered_count[0] += 1
                    return False
                seen_urls.add(url)
                result = SearchResult(title=title, url=url, snippet=snippet, engine=engine)
                all_search_results.append(result)
                fetch_queue.put_nowait(url)
                if progress_callback:
                    progress_callback("search", len(all_search_results), config.search_results)
                return True

            if HAS_DDGS:
                try:
                    ddg_instance = DDGS(verify=False)
                    ddg_results = ddg_instance.text(config.query, max_results=config.search_results * 2)
                    for r in ddg_results:
                        url = r.get("href", "")
                        if url:
                            add_to_queue(
                                title=r.get("title", ""),
                                url=url,
                                snippet=r.get("body", ""),
                                engine="duckduckgo"
                            )
                        if len(all_search_results) >= config.search_results:
                            break
                except Exception as e:
                    logger.debug(f"ddgs streaming failed: {e}")

            # Signal end of search with None
            await fetch_queue.put(None)

        async def fetch_consumer(client: "httpx.AsyncClient") -> None:
            """Consumer: Fetch URLs from queue as they arrive."""
            nonlocal all_fetch_results
            semaphore = asyncio.Semaphore(config.max_concurrent)
            pending_tasks: List[asyncio.Task] = []

            async def fetch_one(url: str) -> None:
                async with semaphore:
                    result = await _fetch_single_async(
                        client, url, config.timeout, config.min_content_length
                    )
                    all_fetch_results.append(result)
                    if progress_callback:
                        progress_callback("fetch", len(all_fetch_results), len(seen_urls))

            while True:
                url = await fetch_queue.get()
                if url is None:
                    break

                # Respect fetch_count limit
                if config.fetch_count > 0 and len(pending_tasks) >= config.fetch_count:
                    continue

                task = asyncio.create_task(fetch_one(url))
                pending_tasks.append(task)

            # Wait for remaining tasks
            if pending_tasks:
                await asyncio.gather(*pending_tasks, return_exceptions=True)

        async with httpx.AsyncClient(
            verify=False,
            limits=httpx.Limits(
                max_connections=config.max_concurrent,
                max_keepalive_connections=config.max_concurrent
            ),
            timeout=config.timeout
        ) as client:
            await asyncio.gather(
                search_producer(),
                fetch_consumer(client)
            )

        # Filter and truncate successful results
        successful_results: List[FetchResult] = []
        jina_count = 0
        for r in all_fetch_results:
            if r.success:
                if len(r.content) > config.max_content_length:
                    r.content = r.content[:config.max_content_length] + "\n\n[Truncated...]"
                successful_results.append(r)
                if r.source == "jina":
                    jina_count += 1

        total_chars = sum(len(r.content) for r in successful_results)

        return ResearchResult(
            query=config.query,
            search_results=all_search_results,
            fetch_results=successful_results,
            urls_searched=len(all_search_results),
            urls_fetched=len(successful_results),
            urls_filtered=filtered_count[0],
            content_chars=total_chars,
            jina_fallback_count=jina_count
        )

# =============================================================================
# RESEARCH WORKFLOW
# =============================================================================

def run_research(config: ResearchConfig) -> ResearchResult:
    """Execute the complete research workflow."""

    # Use streaming pipeline if httpx and ddgs are available
    if HAS_HTTPX and HAS_DDGS:
        if not config.quiet:
            print(f"Researching: \"{config.query}\"", file=sys.stderr)
            print("  Mode: streaming pipeline (search + fetch in parallel)", file=sys.stderr)

        def streaming_progress(phase: str, current: int, total: int) -> None:
            if not config.quiet:
                print(f"\r    {phase.capitalize()}: {current}/{total}    \033[K", end="", file=sys.stderr)

        result = asyncio.run(search_and_fetch_streaming(config, streaming_progress))

        if not config.quiet:
            print(file=sys.stderr)  # New line
            jina_info = f" ({result.jina_fallback_count} via Jina)" if result.jina_fallback_count > 0 else ""
            filter_info = f" [{result.urls_filtered} filtered]" if result.urls_filtered > 0 else ""
            print(f"  Done: {result.urls_fetched}/{result.urls_searched} pages{jina_info}{filter_info} ({result.content_chars:,} chars)", file=sys.stderr)

        return result

    # Fallback to sequential workflow
    all_search_results: List[SearchResult] = []
    seen_urls: Set[str] = set()
    filtered_count = 0

    def add_results(results: List[SearchResult]) -> None:
        nonlocal filtered_count
        for r in results:
            if not is_valid_url(r.url):
                filtered_count += 1
                continue
            if r.url in seen_urls:
                continue
            if is_blocked_url(r.url):
                filtered_count += 1
                continue
            seen_urls.add(r.url)
            all_search_results.append(r)

    # Phase 1: Search
    if not config.quiet:
        print(f"Researching: \"{config.query}\"", file=sys.stderr)
        mode = "sequential (httpx: {}, ddgs: {})".format("yes" if HAS_HTTPX else "no", "yes" if HAS_DDGS else "no")
        print(f"  Mode: {mode}", file=sys.stderr)
        print("  Phase 1: Searching...", file=sys.stderr)

    # DuckDuckGo search
    ddg = DuckDuckGoSearch()
    try:
        ddg_results = ddg.search(config.query, config.search_results)
        add_results(ddg_results)
        if not config.quiet:
            print(f"    DuckDuckGo: {len(ddg_results)} results", file=sys.stderr)
    except SearchError as e:
        logger.error(f"DuckDuckGo search failed: {e}")
        if not config.quiet:
            print(f"    DuckDuckGo: failed ({e})", file=sys.stderr)
    except Exception as e:
        logger.error(f"Unexpected search error: {e}")
        if not config.quiet:
            print(f"    DuckDuckGo: failed ({e})", file=sys.stderr)

    if not all_search_results:
        logger.warning(f"No results found for query: {config.query}")
        if not config.quiet:
            print("  Warning: No results found. Try a different query.", file=sys.stderr)
        return ResearchResult(
            query=config.query,
            search_results=[],
            fetch_results=[],
            urls_searched=0,
            urls_fetched=0,
            urls_filtered=filtered_count,
            content_chars=0,
            jina_fallback_count=0
        )

    if not config.quiet:
        filter_info = f" ({filtered_count} filtered)" if filtered_count > 0 else ""
        print(f"  Total unique URLs: {len(all_search_results)}{filter_info}", file=sys.stderr)

    # Phase 2: Fetch
    target_count = config.fetch_count if config.fetch_count > 0 else len(all_search_results)
    urls_to_fetch = [r.url for r in all_search_results[:target_count]]

    if not config.quiet:
        print(f"  Phase 2: Fetching {len(urls_to_fetch)} pages...", file=sys.stderr)

    def progress_callback(completed: int, total: int) -> None:
        if not config.quiet:
            # Fixed progress indicator with line clearing
            print(f"\r    Progress: {completed}/{total} pages\033[K", end="", file=sys.stderr)

    # Fetch all URLs
    fetch_results = fetch_batch(
        urls_to_fetch,
        max_concurrent=config.max_concurrent,
        timeout=config.timeout,
        min_content_length=config.min_content_length,
        progress_callback=progress_callback if not config.quiet else None
    )

    if not config.quiet:
        print(file=sys.stderr)  # New line after progress

    # Filter successful results and truncate content
    successful_results: List[FetchResult] = []
    jina_count = 0
    for r in fetch_results:
        if r.success:
            if len(r.content) > config.max_content_length:
                r.content = r.content[:config.max_content_length] + "\n\n[Truncated...]"
            successful_results.append(r)
            if r.source == "jina":
                jina_count += 1

    total_chars = sum(len(r.content) for r in successful_results)

    if not config.quiet:
        jina_info = f" ({jina_count} via Jina)" if jina_count > 0 else ""
        print(f"  Done: {len(successful_results)}/{len(urls_to_fetch)} pages{jina_info} ({total_chars:,} chars)", file=sys.stderr)

    return ResearchResult(
        query=config.query,
        search_results=all_search_results,
        fetch_results=successful_results,
        urls_searched=len(all_search_results),
        urls_fetched=len(successful_results),
        urls_filtered=filtered_count,
        content_chars=total_chars,
        jina_fallback_count=jina_count
    )

# =============================================================================
# OUTPUT FORMATTERS
# =============================================================================

def format_json(result: ResearchResult) -> str:
    """Format result as JSON."""
    return json.dumps({
        "query": result.query,
        "stats": {
            "urls_searched": result.urls_searched,
            "urls_fetched": result.urls_fetched,
            "content_chars": result.content_chars
        },
        "content": [
            {"url": r.url, "title": r.title, "content": r.content, "source": r.source}
            for r in result.fetch_results if r.success
        ]
    }, indent=2, ensure_ascii=False)

def format_raw(result: ResearchResult) -> str:
    """Format result as raw text."""
    lines: List[str] = []
    for r in result.fetch_results:
        if r.success:
            lines.append(f"=== {r.url} ===")
            lines.append(r.content)
            lines.append("")
    return "\n".join(lines)

def format_markdown(result: ResearchResult) -> str:
    """Format result as markdown."""
    lines: List[str] = [
        f"# Research: {result.query}",
        "",
        f"**Sources Analyzed**: {result.urls_fetched} pages from {result.urls_searched} search results",
        "",
        "---",
        ""
    ]

    for r in result.fetch_results:
        if r.success and r.content:
            title = r.title or r.url
            lines.append(f"## {title}")
            lines.append(f"*Source: {r.url}*")
            lines.append("")
            content_preview = r.content[:2000]
            if len(r.content) > 2000:
                content_preview += "..."
            lines.append(content_preview)
            lines.append("")
            lines.append("---")
            lines.append("")

    return "\n".join(lines)

# =============================================================================
# CLI
# =============================================================================

def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Web Research Tool - Autonomous Search + Fetch",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python web_research.py "Mac Studio M3 Ultra LLM performance"
  python web_research.py "AI trends 2025" --fetch 50
  python web_research.py "Python best practices" -o markdown
  python web_research.py "climate change solutions" -o raw -m 2000

Workflow:
  1. Search: DuckDuckGo (50 results)
  2. Filter: Remove duplicates, blocked domains, index pages
  3. Fetch: Download pages in parallel with Jina Reader fallback
  4. Output: JSON, raw text, or markdown format

Blocked domains: reddit, twitter, facebook, youtube, tiktok, instagram, linkedin, medium

Performance:
  - Install httpx for 3x faster parallel fetching: pip install httpx
  - Install ddgs for better DuckDuckGo results: pip install ddgs
  - With both installed, uses streaming pipeline (search + fetch in parallel)
        """
    )

    parser.add_argument("query", help="Search query")
    parser.add_argument("-s", "--search", type=int, default=50,
                        help="Number of search results (default: 50)")
    parser.add_argument("-f", "--fetch", type=int, default=0,
                        help="Max pages to fetch (default: 0 = fetch ALL)")
    parser.add_argument("-m", "--max-length", type=int, default=4000,
                        help="Max content length per page (default: 4000)")
    parser.add_argument("-o", "--output", choices=["json", "raw", "markdown"], default="raw",
                        help="Output format (default: raw)")
    parser.add_argument("-t", "--timeout", type=int, default=20,
                        help="Fetch timeout in seconds (default: 20)")
    parser.add_argument("-c", "--concurrent", type=int, default=10,
                        help="Max concurrent connections (default: 10)")
    parser.add_argument("-q", "--quiet", action="store_true",
                        help="Suppress progress messages")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable verbose logging")

    args = parser.parse_args()

    # Configure logging level (only our module's logger, not root)
    if args.verbose:
        logger.setLevel(logging.DEBUG)

    config = ResearchConfig(
        query=args.query,
        fetch_count=args.fetch,
        max_content_length=args.max_length,
        timeout=args.timeout,
        quiet=args.quiet,
        max_concurrent=args.concurrent,
        search_results=args.search,
    )

    try:
        result = run_research(config)

        if args.output == "json":
            print(format_json(result))
        elif args.output == "markdown":
            print(format_markdown(result))
        else:
            print(format_raw(result))

    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Research failed: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
