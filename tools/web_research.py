#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["httpx[http2]", "ddgs"]
# ///
# -*- coding: utf-8 -*-
"""
Web Research Tool - Autonomous Search + Fetch + Report

Unified tool combining search and fetch into a single optimized workflow:
1. Search via DuckDuckGo (50 results)
2. Filter and deduplicate URLs during search (early filtering)
3. Fetch content in parallel with connection reuse and Jina fallback
4. Output combined results (streaming or batched)

Usage:
    python web_research.py "search query"
    python web_research.py "Mac Studio M3 Ultra LLM" --fetch 50
    python web_research.py "AI trends 2025" -o markdown
    python web_research.py "query" --stream  # Stream output as results arrive
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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from functools import partial
from html import unescape
from io import StringIO
from typing import (
    AsyncIterator,
    Callable,
    Dict,
    Iterator,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)

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

BLOCKED_DOMAINS: Tuple[str, ...] = (
    "reddit.com", "twitter.com", "x.com", "facebook.com",
    "youtube.com", "tiktok.com", "instagram.com",
    "linkedin.com", "medium.com",
)

SKIP_URL_PATTERNS: Tuple[str, ...] = (
    r"\.pdf$", r"\.jpg$", r"\.png$", r"\.gif$",
    r"/login", r"/signin", r"/signup", r"/cart", r"/checkout",
    r"amazon\.com/.*/(dp|gp)/", r"ebay\.com/itm/",
    r"/tag/", r"/tags/", r"/category/", r"/categories/",
    r"/topic/", r"/topics/", r"/archive/", r"/page/\d+",
    r"/shop/", r"/store/", r"/buy/", r"/product/", r"/products/",
)

JINA_READER_URL = "https://r.jina.ai/"
JINA_MIN_INTERVAL: float = 0.5
JINA_ERROR_MARKERS: Tuple[str, ...] = (
    "Target URL returned error",
    "You've been blocked",
    "SecurityCompromiseError",
)

# =============================================================================
# COMPILED REGEX PATTERNS
# =============================================================================

# URL filtering - single combined pattern for performance
_BLOCKED_URL_PATTERN = re.compile(
    r'(?:' + '|'.join(re.escape(d) for d in BLOCKED_DOMAINS) + r')|(?:' + '|'.join(SKIP_URL_PATTERNS) + r')',
    re.IGNORECASE
)

# HTML extraction patterns - Phase 1: Remove invisible elements
RE_INVISIBLE = re.compile(
    r"<(script|style|noscript|template|svg|canvas|iframe|object|embed|video|audio)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE
)
RE_COMMENTS = re.compile(r"<!--.*?-->", re.DOTALL)

# Phase 2: Remove elements by boilerplate class/id patterns
_BOILERPLATE_CLASSES = (
    r'nav\b', r'navbar', r'navigation', r'menu', r'breadcrumb',
    r'sidebar', r'aside', r'widget', r'related',
    r'header', r'footer', r'masthead', r'bottom',
    r'social', r'share', r'sharing', r'follow',
    r'comment', r'disqus', r'respond',
    r'\bad\b', r'ads\b', r'advert', r'sponsor', r'promo',
    r'popup', r'modal', r'overlay', r'banner', r'cookie', r'gdpr', r'consent',
    r'newsletter', r'subscribe', r'signup', r'login', r'search-form',
    r'pagination', r'pager', r'toc', r'table-of-contents',
    r'skip-link', r'screen-reader', r'sr-only', r'visually-hidden',
)
RE_BOILERPLATE_CLASS = re.compile(
    r'<([a-z][a-z0-9]*)\s+[^>]*(?:class|id)\s*=\s*["\'][^"\']*(?:' +
    '|'.join(_BOILERPLATE_CLASSES) +
    r')[^"\']*["\'][^>]*>.*?</\1>',
    re.DOTALL | re.IGNORECASE
)

# Phase 3: Remove semantic boilerplate tags
RE_SEMANTIC_BOILERPLATE = re.compile(
    r"<(nav|aside|footer|header|figcaption)[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE
)

# Phase 4: Extract main content area
RE_MAIN_CONTENT = re.compile(r"<(article|main)[^>]*>(.*?)</\1>", re.DOTALL | re.IGNORECASE)
RE_BODY = re.compile(r"<body[^>]*>(.*?)</body>", re.DOTALL | re.IGNORECASE)

# Text extraction patterns
RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
RE_HEADING = re.compile(r"<h([1-6])[^>]*>(.*?)</h\1>", re.IGNORECASE | re.DOTALL)
RE_BLOCK_TAGS = re.compile(r"</(p|div|h[1-6]|li|tr|article|section|blockquote|pre)>", re.IGNORECASE)
RE_LI = re.compile(r"<li[^>]*>", re.IGNORECASE)
RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_P_TAG = re.compile(r"<p[^>]*>", re.IGNORECASE)
RE_ALL_TAGS = re.compile(r"<[^>]+>")

# Whitespace normalization
RE_MULTI_SPACE = re.compile(r"[ \t]+")
RE_MULTI_NEWLINE = re.compile(r"\n{3,}")
RE_LEADING_WHITESPACE = re.compile(r"\n[ \t]+")
RE_WHITESPACE = re.compile(r"\s+")

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
# DATA CLASSES
# =============================================================================

@dataclass
class ResearchConfig:
    """Configuration for research workflow."""
    query: str
    fetch_count: int = 0
    max_content_length: int = 4000
    timeout: int = 20
    quiet: bool = False
    min_content_length: int = 200
    max_concurrent: int = 10
    search_results: int = 50
    stream: bool = False  # New: enable streaming output


@dataclass
class FetchResult:
    """Single fetch result."""
    url: str
    success: bool
    content: str = ""
    title: str = ""
    error: Optional[str] = None
    source: str = "direct"


@dataclass
class ResearchStats:
    """Statistics for research run."""
    query: str = ""
    urls_searched: int = 0
    urls_fetched: int = 0
    urls_filtered: int = 0
    content_chars: int = 0
    jina_fallback_count: int = 0


# =============================================================================
# PROGRESS REPORTER (Unified)
# =============================================================================

class ProgressReporter:
    """Unified progress reporting."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self._last_line_len = 0

    def message(self, msg: str) -> None:
        """Print a message line."""
        if not self.quiet:
            print(msg, file=sys.stderr)

    def update(self, phase: str, current: int, total: int) -> None:
        """Update progress on same line."""
        if not self.quiet:
            line = f"\r    {phase.capitalize()}: {current}/{total}"
            # Clear previous content if shorter
            padding = max(0, self._last_line_len - len(line))
            print(f"{line}{' ' * padding}", end="", file=sys.stderr)
            self._last_line_len = len(line)

    def newline(self) -> None:
        """Print newline after progress updates."""
        if not self.quiet:
            print(file=sys.stderr)
            self._last_line_len = 0


# =============================================================================
# SSL CONTEXT
# =============================================================================

_SSL_CONTEXT: Optional[ssl.SSLContext] = None

def get_ssl_context() -> ssl.SSLContext:
    """Get or create reusable SSL context (verification disabled for reliability)."""
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
    """Check if URL should be blocked (optimized single-regex check)."""
    return bool(_BLOCKED_URL_PATTERN.search(url))


def is_valid_url(url: str) -> bool:
    """Validate URL format."""
    try:
        result = urllib.parse.urlparse(url)
        return all([result.scheme in ('http', 'https'), result.netloc])
    except Exception:
        return False


def extract_text(html: str) -> str:
    """Extract readable text from HTML with boilerplate removal.

    Uses a multi-phase approach:
    1. Remove invisible elements (script, style, etc.)
    2. Remove elements with boilerplate class/id patterns
    3. Remove semantic boilerplate tags (nav, aside, footer, header)
    4. Extract from <article>/<main> if present
    5. Convert to clean text with markdown headings
    """
    # Extract title first
    title_match = RE_TITLE.search(html)
    title = unescape(title_match.group(1).strip()) if title_match else ""
    # Clean title (remove site name suffix)
    if " | " in title:
        title = title.split(" | ")[0].strip()
    elif " - " in title:
        parts = title.split(" - ")
        if len(parts) > 1 and len(parts[0]) > 10:
            title = parts[0].strip()

    # Phase 1: Remove invisible/script elements
    html = RE_INVISIBLE.sub("", html)
    html = RE_COMMENTS.sub("", html)

    # Phase 2: Remove elements with boilerplate class/id (multiple passes for nesting)
    for _ in range(3):
        html = RE_BOILERPLATE_CLASS.sub("", html)

    # Phase 3: Remove semantic boilerplate tags
    html = RE_SEMANTIC_BOILERPLATE.sub("", html)

    # Phase 4: Try to extract main content area
    main_match = RE_MAIN_CONTENT.search(html)
    if main_match:
        html = main_match.group(2)
    else:
        body_match = RE_BODY.search(html)
        if body_match:
            html = body_match.group(1)

    # Phase 5: Convert to text with structure

    # Convert headings to markdown
    def heading_replace(m: re.Match) -> str:
        level = int(m.group(1))
        text = RE_ALL_TAGS.sub("", m.group(2)).strip()
        if text:
            return f"\n\n{'#' * level} {text}\n\n"
        return ""

    html = RE_HEADING.sub(heading_replace, html)

    # Add line breaks for block elements
    html = RE_BR.sub("\n", html)
    html = RE_BLOCK_TAGS.sub("\n\n", html)
    html = RE_P_TAG.sub("\n", html)
    html = RE_LI.sub("- ", html)

    # Strip remaining tags
    text = RE_ALL_TAGS.sub(" ", html)
    text = unescape(text)

    # Normalize whitespace
    text = RE_MULTI_SPACE.sub(" ", text)
    text = RE_LEADING_WHITESPACE.sub("\n", text)
    text = RE_MULTI_NEWLINE.sub("\n\n", text)

    # Final cleanup: remove short lines (UI remnants) and empty bullets
    lines = []
    for line in text.split("\n"):
        line = line.strip()
        # Skip empty lines and very short non-heading lines
        if not line:
            continue
        if len(line) <= 2 and not line.startswith("#"):
            continue
        # Skip empty bullet points
        if line in ("-", "•", "*"):
            continue
        lines.append(line)

    text = "\n".join(lines)
    text = RE_MULTI_NEWLINE.sub("\n\n", text)
    text = text.strip()

    # Add title if not already in content
    if title and not text.startswith("#"):
        text = f"# {title}\n\n{text}"

    return text


def extract_title_from_content(content: str) -> str:
    """Extract title from markdown-formatted content."""
    if content.startswith("# "):
        newline = content.find("\n")
        if newline > 0:
            return content[2:newline]
    return ""


def get_random_user_agent() -> str:
    """Get a random user agent string."""
    return random.choice(USER_AGENTS)


# =============================================================================
# JINA READER (Unified implementation)
# =============================================================================

class JinaRateLimiter:
    """Rate limiter for Jina API calls with async support.

    Uses sliding window approach to allow concurrent requests while
    respecting rate limits.
    """

    def __init__(self, requests_per_second: float = 2.0):
        self._interval = 1.0 / requests_per_second
        self._last_call: float = 0.0
        self._lock = asyncio.Lock() if asyncio else None
        self._sync_lock = None  # Lazy init for sync

    def wait_sync(self) -> None:
        """Synchronous wait for rate limit."""
        import threading
        if self._sync_lock is None:
            self._sync_lock = threading.Lock()

        with self._sync_lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._interval:
                time.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()

    async def wait_async(self) -> None:
        """Async wait for rate limit with proper concurrency."""
        async with self._lock:
            elapsed = time.monotonic() - self._last_call
            if elapsed < self._interval:
                await asyncio.sleep(self._interval - elapsed)
            self._last_call = time.monotonic()


_jina_limiter = JinaRateLimiter(requests_per_second=2.0)


def _check_jina_content(content: str) -> bool:
    """Check if Jina content is valid (not an error response)."""
    return not any(marker in content for marker in JINA_ERROR_MARKERS)


def fetch_via_jina_sync(url: str, timeout: int = 20) -> Optional[str]:
    """Fetch URL via Jina Reader API (synchronous)."""
    _jina_limiter.wait_sync()
    try:
        jina_url = f"{JINA_READER_URL}{url}"
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "text/plain",
            "X-Return-Format": "text",
        }
        req = urllib.request.Request(jina_url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as resp:
            content = resp.read().decode("utf-8", errors="replace")
            return content if _check_jina_content(content) else None
    except Exception as e:
        logger.debug(f"Jina Reader failed for {url}: {e}")
    return None


async def fetch_via_jina_async(
    client: "httpx.AsyncClient",
    url: str,
    timeout: int = 20
) -> Optional[str]:
    """Fetch URL via Jina Reader API (async)."""
    await _jina_limiter.wait_async()
    try:
        jina_url = f"{JINA_READER_URL}{url}"
        resp = await client.get(
            jina_url,
            headers={
                "User-Agent": get_random_user_agent(),
                "Accept": "text/plain",
                "X-Return-Format": "text",
            },
            timeout=timeout,
            follow_redirects=True
        )
        if resp.status_code == 200:
            content = resp.text
            return content if _check_jina_content(content) else None
    except Exception as e:
        logger.debug(f"Jina Reader failed for {url}: {e}")
    return None


# =============================================================================
# URL FETCHER (Unified core logic)
# =============================================================================

def _create_fetch_result(
    url: str,
    content: Optional[str],
    source: str,
    min_length: int,
    max_length: int
) -> FetchResult:
    """Create FetchResult from content, applying length checks and truncation."""
    if content and len(content) >= min_length:
        if len(content) > max_length:
            content = content[:max_length] + "\n\n[Truncated...]"
        return FetchResult(
            url=url,
            success=True,
            content=content,
            title=extract_title_from_content(content),
            source=source
        )
    return FetchResult(url=url, success=False, error="Content too short or empty")


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
    with urllib.request.urlopen(req, timeout=timeout, context=get_ssl_context()) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def fetch_single_sync(
    url: str,
    timeout: int,
    min_content_length: int,
    max_content_length: int
) -> FetchResult:
    """Fetch single URL with Jina fallback (synchronous)."""
    # Try direct fetch
    try:
        html = fetch_url_sync(url, timeout=timeout)
        content = extract_text(html)
        if len(content) >= min_content_length:
            return _create_fetch_result(url, content, "direct", min_content_length, max_content_length)
    except urllib.error.HTTPError as e:
        if e.code not in (403, 401, 429):
            return FetchResult(url=url, success=False, error=f"HTTP {e.code}")
        logger.debug(f"HTTP {e.code} for {url}, trying Jina fallback")
    except Exception as e:
        logger.debug(f"Direct fetch failed for {url}: {e}")

    # Jina fallback
    jina_content = fetch_via_jina_sync(url, timeout)
    if jina_content:
        return _create_fetch_result(url, jina_content, "jina", min_content_length, max_content_length)

    return FetchResult(url=url, success=False, error="All fetch methods failed")


# =============================================================================
# ASYNC FETCHER (httpx)
# =============================================================================

MAX_CONTENT_BYTES = 2_000_000  # 2MB max content size

if HAS_HTTPX:
    async def fetch_single_async(
        client: "httpx.AsyncClient",
        url: str,
        timeout: int,
        min_content_length: int,
        max_content_length: int
    ) -> FetchResult:
        """Fetch single URL with Jina fallback (async)."""
        # Try direct fetch
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
                # Early content-length check to skip huge pages
                content_length = resp.headers.get('content-length')
                if content_length and int(content_length) > MAX_CONTENT_BYTES:
                    return FetchResult(url=url, success=False, error="Content too large")

                content = extract_text(resp.text)
                if len(content) >= min_content_length:
                    return _create_fetch_result(url, content, "direct", min_content_length, max_content_length)
            elif resp.status_code not in (403, 401, 429):
                return FetchResult(url=url, success=False, error=f"HTTP {resp.status_code}")
            else:
                logger.debug(f"HTTP {resp.status_code} for {url}, trying Jina fallback")
        except Exception as e:
            logger.debug(f"Direct fetch failed for {url}: {e}")

        # Jina fallback - content is already clean markdown, skip extraction
        jina_content = await fetch_via_jina_async(client, url, timeout)
        if jina_content:
            # Jina returns clean text, create result directly without re-extraction
            return _create_fetch_result(url, jina_content, "jina", min_content_length, max_content_length)

        return FetchResult(url=url, success=False, error="All fetch methods failed")


# =============================================================================
# DUCKDUCKGO SEARCH
# =============================================================================

class DuckDuckGoSearch:
    """DuckDuckGo search with early URL filtering."""

    BASE_URL = "https://html.duckduckgo.com/html/"

    def search(
        self,
        query: str,
        num_results: int = 50,
        delay: float = 2.0,
    ) -> Iterator[Tuple[str, str]]:
        """
        Search DuckDuckGo and yield (url, title) tuples.
        Filters blocked URLs during iteration.
        """
        seen_urls: Set[str] = set()
        count = 0

        # Try ddgs library first
        if HAS_DDGS:
            try:
                ddg = DDGS(verify=False)
                for r in ddg.text(query, max_results=num_results * 2):
                    url = r.get("href", "")
                    if url and url not in seen_urls and is_valid_url(url) and not is_blocked_url(url):
                        seen_urls.add(url)
                        yield url, r.get("title", "")
                        count += 1
                        if count >= num_results:
                            return
                if count > 0:
                    return
            except Exception as e:
                logger.debug(f"ddgs library failed: {e}")

        # Fallback to HTML scraping
        yield from self._search_html(query, num_results, delay, seen_urls, count)

    def _search_html(
        self,
        query: str,
        num_results: int,
        delay: float,
        seen_urls: Set[str],
        current_count: int
    ) -> Iterator[Tuple[str, str]]:
        """Search using HTML scraping fallback."""
        consecutive_empty = 0
        max_pages = (num_results // 10) + 3
        count = current_count

        for page in range(1, max_pages + 1):
            if consecutive_empty >= 3 or count >= num_results:
                break

            try:
                params = {"q": query}
                if page > 1:
                    params["s"] = str((page - 1) * 30)

                url = f"{self.BASE_URL}?{urllib.parse.urlencode(params)}"
                html = fetch_url_sync(url)

                if "anomaly.js" in html or "cc=botnet" in html:
                    logger.warning("DuckDuckGo bot detection triggered")
                    break

                page_results = self._parse_html(html)

                if not page_results:
                    consecutive_empty += 1
                else:
                    consecutive_empty = 0

                for title, result_url in page_results:
                    if result_url not in seen_urls and is_valid_url(result_url) and not is_blocked_url(result_url):
                        seen_urls.add(result_url)
                        yield result_url, title
                        count += 1
                        if count >= num_results:
                            return

                if page < max_pages:
                    time.sleep(delay)

            except Exception as e:
                logger.debug(f"DuckDuckGo page {page} failed: {e}")
                consecutive_empty += 1

    def _parse_html(self, html: str) -> List[Tuple[str, str]]:
        """Parse DuckDuckGo HTML results."""
        results: List[Tuple[str, str]] = []
        blocks = RE_DDG_RESULT_BLOCK.split(html)

        for block in blocks[1:]:
            link_match = RE_DDG_LINK.search(block)
            if not link_match:
                continue

            raw_url = link_match.group(1)
            title = clean_text(link_match.group(2))

            if not title or "ad_provider" in raw_url:
                continue

            url = self._extract_url(raw_url)
            if url:
                results.append((title, url))

        return results

    def _extract_url(self, ddg_url: str) -> Optional[str]:
        """Extract actual URL from DuckDuckGo redirect."""
        if not ddg_url:
            return None

        ddg_url = unescape(ddg_url)

        if ddg_url.startswith(("http://", "https://")) and "duckduckgo.com" not in ddg_url:
            return ddg_url

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
# STREAMING OUTPUT
# =============================================================================

def format_result_raw(result: FetchResult) -> str:
    """Format single result as raw text."""
    return f"=== {result.url} ===\n{result.content}\n"


def format_result_json(result: FetchResult) -> str:
    """Format single result as JSON line."""
    return json.dumps({
        "url": result.url,
        "title": result.title,
        "content": result.content,
        "source": result.source
    }, ensure_ascii=False)


def stream_results(
    results: Iterator[FetchResult],
    output_format: str = "raw"
) -> Iterator[str]:
    """Stream formatted results."""
    formatter = format_result_json if output_format == "json" else format_result_raw
    for result in results:
        if result.success:
            yield formatter(result)


# =============================================================================
# RESEARCH WORKFLOWS
# =============================================================================

def run_research_sync(
    config: ResearchConfig,
    progress: ProgressReporter
) -> Iterator[FetchResult]:
    """
    Synchronous research workflow (generator).
    Yields FetchResult objects as they complete.
    """
    progress.message(f'Researching: "{config.query}"')
    progress.message("  Mode: sequential")

    # Search phase
    progress.message("  Phase 1: Searching...")
    ddg = DuckDuckGoSearch()
    urls: List[Tuple[str, str]] = []
    filtered_count = 0

    for url, title in ddg.search(config.query, config.search_results):
        urls.append((url, title))
        progress.update("search", len(urls), config.search_results)

    progress.newline()
    progress.message(f"  Found: {len(urls)} URLs")

    if not urls:
        progress.message("  Warning: No results found.")
        return

    # Fetch phase
    target_count = config.fetch_count if config.fetch_count > 0 else len(urls)
    urls_to_fetch = urls[:target_count]
    progress.message(f"  Phase 2: Fetching {len(urls_to_fetch)} pages...")

    fetched = 0
    for url, title in urls_to_fetch:
        result = fetch_single_sync(
            url,
            config.timeout,
            config.min_content_length,
            config.max_content_length
        )
        fetched += 1
        progress.update("fetch", fetched, len(urls_to_fetch))
        yield result

    progress.newline()


if HAS_HTTPX:
    async def run_research_async(
        config: ResearchConfig,
        progress: ProgressReporter
    ) -> AsyncIterator[FetchResult]:
        """
        Async streaming research workflow.
        Yields FetchResult objects as they complete.
        """
        progress.message(f'Researching: "{config.query}"')
        progress.message("  Mode: streaming pipeline (search + fetch in parallel)")

        urls: List[str] = []
        fetch_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()
        result_queue: asyncio.Queue[Optional[FetchResult]] = asyncio.Queue()
        stats = ResearchStats(query=config.query)

        async def search_producer() -> None:
            """Search and queue URLs for fetching (runs in thread pool)."""
            loop = asyncio.get_event_loop()
            ddg = DuckDuckGoSearch()

            # Run blocking search in thread pool to not block event loop
            def search_sync():
                return list(ddg.search(config.query, config.search_results))

            with ThreadPoolExecutor(max_workers=1) as executor:
                search_results = await loop.run_in_executor(executor, search_sync)

            for url, title in search_results:
                urls.append(url)
                stats.urls_searched = len(urls)
                await fetch_queue.put(url)
                progress.update("search", len(urls), config.search_results)
            await fetch_queue.put(None)

        async def fetch_consumer(client: "httpx.AsyncClient") -> None:
            """Fetch URLs and queue results."""
            semaphore = asyncio.Semaphore(config.max_concurrent)
            pending: List[asyncio.Task] = []
            fetch_limit = config.fetch_count if config.fetch_count > 0 else float('inf')

            async def fetch_one(url: str) -> None:
                async with semaphore:
                    result = await fetch_single_async(
                        client, url, config.timeout,
                        config.min_content_length, config.max_content_length
                    )
                    await result_queue.put(result)

            while True:
                url = await fetch_queue.get()
                if url is None:
                    break
                if len(pending) < fetch_limit:
                    pending.append(asyncio.create_task(fetch_one(url)))

            if pending:
                await asyncio.gather(*pending, return_exceptions=True)
            await result_queue.put(None)

        # HTTP/2 enabled with optimized connection pool
        async with httpx.AsyncClient(
            verify=False,
            http2=True,  # Enable HTTP/2 for multiplexing
            limits=httpx.Limits(
                max_connections=config.max_concurrent,
                max_keepalive_connections=config.max_concurrent,
                keepalive_expiry=30.0
            ),
            timeout=httpx.Timeout(config.timeout, connect=5.0)
        ) as client:
            # Start search and fetch concurrently
            asyncio.create_task(search_producer())
            asyncio.create_task(fetch_consumer(client))

            # Yield results as they arrive
            fetched = 0
            while True:
                result = await result_queue.get()
                if result is None:
                    break
                fetched += 1
                if result.success:
                    stats.urls_fetched += 1
                    stats.content_chars += len(result.content)
                    if result.source == "jina":
                        stats.jina_fallback_count += 1
                progress.update("fetch", fetched, stats.urls_searched or fetched)
                yield result

        progress.newline()
        jina_info = f" ({stats.jina_fallback_count} via Jina)" if stats.jina_fallback_count > 0 else ""
        progress.message(f"  Done: {stats.urls_fetched}/{stats.urls_searched} pages{jina_info} ({stats.content_chars:,} chars)")


# =============================================================================
# BATCH OUTPUT FORMATTERS (for non-streaming mode)
# =============================================================================

def format_batch_json(results: List[FetchResult], query: str) -> str:
    """Format all results as JSON."""
    successful = [r for r in results if r.success]
    return json.dumps({
        "query": query,
        "stats": {
            "urls_fetched": len(successful),
            "content_chars": sum(len(r.content) for r in successful)
        },
        "content": [
            {"url": r.url, "title": r.title, "content": r.content, "source": r.source}
            for r in successful
        ]
    }, indent=2, ensure_ascii=False)


def format_batch_raw(results: List[FetchResult]) -> str:
    """Format all results as raw text (optimized with StringIO)."""
    buffer = StringIO()
    for r in results:
        if r.success:
            buffer.write(f"=== {r.url} ===\n")
            buffer.write(r.content)
            buffer.write("\n\n")
    return buffer.getvalue()


def format_batch_markdown(results: List[FetchResult], query: str, max_preview: int = 4000) -> str:
    """Format all results as markdown (optimized with StringIO)."""
    successful = [r for r in results if r.success]
    buffer = StringIO()

    buffer.write(f"# Research: {query}\n\n")
    buffer.write(f"**Sources Analyzed**: {len(successful)} pages\n\n")
    buffer.write("---\n\n")

    for r in successful:
        if r.content:
            title = r.title or r.url
            buffer.write(f"## {title}\n")
            buffer.write(f"*Source: {r.url}*\n\n")
            if len(r.content) > max_preview:
                buffer.write(r.content[:max_preview])
                buffer.write("...")
            else:
                buffer.write(r.content)
            buffer.write("\n\n---\n\n")

    return buffer.getvalue()


# =============================================================================
# MAIN ENTRY POINTS
# =============================================================================

def run_research(config: ResearchConfig) -> None:
    """Execute research and output results."""
    progress = ProgressReporter(quiet=config.quiet)

    if config.stream:
        # Streaming mode: output results as they arrive
        if HAS_HTTPX and HAS_DDGS:
            async def stream_async():
                async for result in run_research_async(config, progress):
                    if result.success:
                        if config.quiet:
                            # In quiet+stream mode, just output content
                            print(format_result_raw(result) if config.quiet else format_result_raw(result))
                        else:
                            print(format_result_raw(result))
            asyncio.run(stream_async())
        else:
            for result in run_research_sync(config, progress):
                if result.success:
                    print(format_result_raw(result))
    else:
        # Batch mode: collect all results, then format
        results: List[FetchResult] = []

        if HAS_HTTPX and HAS_DDGS:
            async def collect_async():
                async for result in run_research_async(config, progress):
                    results.append(result)
            asyncio.run(collect_async())
        else:
            for result in run_research_sync(config, progress):
                results.append(result)

        # Output formatted results
        return results


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
  python web_research.py "query" --stream  # Stream output as results arrive

Blocked domains: reddit, twitter, facebook, youtube, tiktok, instagram, linkedin, medium
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
    parser.add_argument("--stream", action="store_true",
                        help="Stream output as results arrive (reduces memory usage)")

    args = parser.parse_args()

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
        stream=args.stream,
    )

    try:
        if args.stream:
            # Streaming mode outputs directly
            run_research(config)
        else:
            # Batch mode
            results = run_research(config)
            if results:
                if args.output == "json":
                    print(format_batch_json(results, config.query))
                elif args.output == "markdown":
                    print(format_batch_markdown(results, config.query, config.max_content_length))
                else:
                    print(format_batch_raw(results))

    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Research failed: {e}")
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
