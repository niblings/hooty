"""Web search tools for Hooty."""

from __future__ import annotations

import logging
from typing import Optional
from urllib.parse import urljoin, urlparse

import httpx
from agno.tools import Toolkit
from bs4 import BeautifulSoup

from hooty import __version__

logger = logging.getLogger("hooty")


def create_search_tools(region: str | None = None) -> Optional[Toolkit]:
    """Create DuckDuckGo search tools if ddgs is available."""
    try:
        from agno.tools.duckduckgo import DuckDuckGoTools

        kwargs: dict[str, object] = {"enable_search": True, "enable_news": True, "fixed_max_results": 3}
        if region:
            kwargs["region"] = region
        return DuckDuckGoTools(**kwargs)
    except ImportError:
        return None


_DEFAULT_MAX_CHARS = 20_000
_ABSOLUTE_MAX_CHARS = 80_000
_TIMEOUT = 10
_HEADERS = {"User-Agent": f"hooty/{__version__} (Interactive AI coding assistant)"}


def _is_html_content_type(content_type: str) -> bool:
    """Return True if Content-Type indicates HTML (empty defaults to HTML)."""
    media = content_type.split(";")[0].strip().lower()
    return media in ("text/html", "application/xhtml+xml", "")


def _is_binary_content_type(content_type: str) -> bool:
    """Return True if Content-Type indicates binary data."""
    media = content_type.split(";")[0].strip().lower()
    if not media or media.startswith("text/"):
        return False
    if media in ("application/json", "application/xml", "application/yaml",
                 "application/javascript", "application/xhtml+xml"):
        return False
    return True


def _extract_text(resp: httpx.Response) -> str:
    """Extract text from response based on Content-Type."""
    ct = resp.headers.get("content-type", "")
    if _is_binary_content_type(ct):
        media = ct.split(";")[0].strip().lower()
        return f"[Binary content: {media}]"
    if _is_html_content_type(ct):
        soup = BeautifulSoup(resp.text, "html.parser")
        return _extract_main_content(soup)
    return resp.text


def _extract_main_content(soup: BeautifulSoup) -> str:
    """Extract main content from HTML, removing nav/script/style."""
    # Remove non-content elements
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    # Prefer semantic content containers
    for selector in ["article", "main", "[role='main']"]:
        container = soup.select_one(selector)
        if container:
            text = container.get_text(separator="\n", strip=True)
            if len(text) > 100:
                return text

    # Fallback: use <section> elements if they have substantial content
    sections = soup.find_all("section")
    if sections:
        combined = "\n\n".join(s.get_text(separator="\n", strip=True) for s in sections)
        if len(combined) > 100:
            return combined

    # Final fallback: full body text
    body = soup.find("body")
    if body:
        return body.get_text(separator="\n", strip=True)
    return soup.get_text(separator="\n", strip=True)


def _fetch_page(url: str, client: httpx.Client | None = None) -> tuple[str, str]:
    """Fetch a single page. Returns (content_text, final_url)."""
    if client is not None:
        resp = client.get(url)
    else:
        resp = httpx.get(url, headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True)
    resp.raise_for_status()
    text = _extract_text(resp)
    return text, str(resp.url)


def _extract_same_domain_links(html: str, base_url: str, max_links: int) -> list[str]:
    """Extract up to max_links same-domain links from HTML."""
    soup = BeautifulSoup(html, "html.parser")
    base_domain = urlparse(base_url).netloc
    links: list[str] = []
    seen: set[str] = {base_url}
    for a_tag in soup.find_all("a", href=True):
        href = a_tag["href"]
        full_url = urljoin(base_url, href)
        # Strip fragment
        parsed = urlparse(full_url)
        clean_url = parsed._replace(fragment="").geturl()
        if parsed.netloc != base_domain:
            continue
        if clean_url in seen:
            continue
        seen.add(clean_url)
        links.append(clean_url)
        if len(links) >= max_links:
            break
    return links


def create_web_fetch_tools() -> Optional[Toolkit]:
    """Create a lightweight URL fetcher using httpx + BeautifulSoup."""

    def web_fetch(url: str, max_depth: int = 1, max_links: int = 1, max_chars: int = 20000) -> str:
        """Fetch a web page and return its text content.

        :param url: The URL of the web page to fetch.
        :param max_depth: Maximum crawl depth (1 = single page only, max 2). Default 1.
        :param max_links: Maximum number of pages to read (max 3). Default 1.
        :param max_chars: Maximum characters to return (default 20000, max 80000). Increase for thorough research.
        :return: The text content of the page(s).
        """
        max_depth = max(1, min(max_depth, 2))
        max_links = max(1, min(max_links, 3))
        max_chars = max(1000, min(max_chars, _ABSOLUTE_MAX_CHARS))

        logger.debug("[web] web_fetch: %s (max_depth=%d, max_links=%d)", url, max_depth, max_links)

        parts: list[str] = []
        visited: set[str] = set()

        with httpx.Client(
            headers=_HEADERS, timeout=_TIMEOUT, follow_redirects=True,
        ) as client:
            # Fetch the initial page
            try:
                resp = client.get(url)
                resp.raise_for_status()
            except Exception as exc:
                logger.debug("[web] web_fetch: error reading %s: %s", url, exc)
                return f"Failed to read content from {url}: {exc}"

            ct = resp.headers.get("content-type", "")
            final_url = str(resp.url)
            visited.add(final_url)
            visited.add(url)

            if _is_binary_content_type(ct):
                media = ct.split(";")[0].strip().lower()
                return f"[Binary content: {media}] — cannot extract text from {url}"

            # HTML: parse and keep raw_html for link extraction
            if _is_html_content_type(ct):
                raw_html = resp.text
                soup = BeautifulSoup(raw_html, "html.parser")
                main_text = _extract_main_content(soup)
            else:
                # Plain text, JSON, markdown, etc. — return as-is
                raw_html = None
                main_text = resp.text

            if main_text:
                parts.append(main_text)
                logger.debug("[web] web_fetch: fetched %s (%d chars)", final_url, len(main_text))

            # Follow same-domain links if depth > 1 (HTML only)
            if max_depth >= 2 and max_links > 1 and raw_html is not None:
                follow_links = _extract_same_domain_links(raw_html, final_url, max_links - 1)
                for link_url in follow_links:
                    if link_url in visited:
                        continue
                    visited.add(link_url)
                    try:
                        text, resolved = _fetch_page(link_url, client=client)
                        visited.add(resolved)
                        if text:
                            parts.append(text)
                            logger.debug("[web] web_fetch: fetched %s (%d chars)", resolved, len(text))
                    except Exception as exc:
                        logger.debug("[web] web_fetch: error reading %s: %s", link_url, exc)

        if not parts:
            logger.debug("[web] web_fetch: no content returned from %s", url)
            return f"Failed to read content from {url}"

        content = "\n\n---\n\n".join(parts)

        if len(content) > max_chars:
            total = len(content)
            logger.debug("[web] web_fetch: truncating %d -> %d chars", total, max_chars)
            content = (
                content[:max_chars]
                + f"\n\n[Truncated: {total} chars total,"
                  f" showing first {max_chars}]"
            )
        logger.debug("[web] web_fetch: returning %d chars (%d pages)", len(content), len(parts))
        return content

    toolkit = Toolkit(name="web_fetch", tools=[web_fetch])
    return toolkit
