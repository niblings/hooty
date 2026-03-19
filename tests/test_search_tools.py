"""Tests for hooty.tools.search_tools module."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import httpx


def _make_mock_response(text: str = "<html><body><p>Hello world</p></body></html>",
                        url: str = "https://example.com/",
                        content_type: str = "text/html") -> MagicMock:
    """Create a mock httpx.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = text
    mock_resp.url = url
    mock_resp.headers = {"content-type": content_type}
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


def _make_mock_client(response: MagicMock | None = None) -> MagicMock:
    """Create a mock httpx.Client context manager."""
    if response is None:
        response = _make_mock_response()
    mock_client = MagicMock()
    mock_client.get.return_value = response
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=False)
    return mock_client


def _get_web_fetch_fn(toolkit):
    """Extract the web_fetch function from a toolkit."""
    for fn in toolkit.functions.values():
        if fn.name == "web_fetch":
            return fn
    return None


class TestWebFetchHeaders:
    """Verify web_fetch sends the correct User-Agent header."""

    def test_uses_custom_user_agent(self):
        """web_fetch should pass _HEADERS with hooty/{version} User-Agent."""
        from hooty import __version__
        from hooty.tools.search_tools import _HEADERS

        assert "User-Agent" in _HEADERS
        assert f"hooty/{__version__}" in _HEADERS["User-Agent"]

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_httpx_client_called_with_headers(self, mock_client_cls):
        """web_fetch should create httpx.Client with _HEADERS."""
        from hooty.tools.search_tools import _HEADERS, create_web_fetch_tools

        mock_client = _make_mock_client()
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        assert toolkit is not None

        web_fetch_fn = _get_web_fetch_fn(toolkit)
        assert web_fetch_fn is not None

        result = web_fetch_fn.entrypoint(url="https://example.com/")

        mock_client_cls.assert_called_once_with(
            headers=_HEADERS,
            timeout=10,
            follow_redirects=True,
        )
        mock_client.get.assert_called_once_with("https://example.com/")
        assert "Hello world" in result

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_error_handling(self, mock_client_cls):
        """web_fetch should return error message on failure."""
        from hooty.tools.search_tools import create_web_fetch_tools

        mock_client = MagicMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        web_fetch_fn = _get_web_fetch_fn(toolkit)

        result = web_fetch_fn.entrypoint(url="https://unreachable.example.com/")
        assert "Failed to read content" in result


class TestUserAgentVersion:
    def test_version_in_user_agent(self):
        """User-Agent string should contain the current version."""
        from hooty import __version__
        from hooty.tools.search_tools import _HEADERS

        assert __version__ in _HEADERS["User-Agent"]
        assert _HEADERS["User-Agent"].startswith("hooty/")


class TestMaxCharsParam:
    """Verify max_chars parameter controls truncation."""

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_default_truncation(self, mock_client_cls):
        """Default max_chars=20000 should truncate long content."""
        from hooty.tools.search_tools import create_web_fetch_tools

        long_text = "x" * 30_000
        mock_client = _make_mock_client(
            _make_mock_response(f"<html><body><p>{long_text}</p></body></html>")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        web_fetch_fn = _get_web_fetch_fn(toolkit)

        result = web_fetch_fn.entrypoint(url="https://example.com/")
        assert "Truncated" in result
        assert len(result) < 25_000

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_increased_max_chars(self, mock_client_cls):
        """max_chars=50000 should allow more content through."""
        from hooty.tools.search_tools import create_web_fetch_tools

        long_text = "x" * 30_000
        mock_client = _make_mock_client(
            _make_mock_response(f"<html><body><p>{long_text}</p></body></html>")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        web_fetch_fn = _get_web_fetch_fn(toolkit)

        result = web_fetch_fn.entrypoint(url="https://example.com/", max_chars=50000)
        assert "Truncated" not in result

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_max_chars_clamped_to_absolute_max(self, mock_client_cls):
        """max_chars above 80000 should be clamped."""
        from hooty.tools.search_tools import _ABSOLUTE_MAX_CHARS, create_web_fetch_tools

        long_text = "x" * 100_000
        mock_client = _make_mock_client(
            _make_mock_response(f"<html><body><p>{long_text}</p></body></html>")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        web_fetch_fn = _get_web_fetch_fn(toolkit)

        result = web_fetch_fn.entrypoint(url="https://example.com/", max_chars=999999)
        assert "Truncated" in result
        assert f"showing first {_ABSOLUTE_MAX_CHARS}" in result


class TestExtractMainContent:
    def test_article_preferred(self):
        """Should prefer <article> content over full body."""
        from hooty.tools.search_tools import _extract_main_content
        from bs4 import BeautifulSoup

        html = """
        <html><body>
            <nav>Navigation</nav>
            <article>This is the main article content that is long enough to be selected as the primary content source.</article>
            <footer>Footer</footer>
        </body></html>
        """
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_main_content(soup)
        assert "main article content" in result
        assert "Navigation" not in result
        assert "Footer" not in result

    def test_fallback_to_body(self):
        """Should fall back to body text when no semantic containers."""
        from hooty.tools.search_tools import _extract_main_content
        from bs4 import BeautifulSoup

        html = "<html><body><p>Simple page content</p></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        result = _extract_main_content(soup)
        assert "Simple page content" in result


class TestContentTypeHandling:
    """Verify Content-Type based response handling."""

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_plain_text_returned_as_is(self, mock_client_cls):
        """text/plain responses should be returned without HTML parsing."""
        from hooty.tools.search_tools import create_web_fetch_tools

        raw_text = "Line 1\nLine 2\nLine 3"
        mock_client = _make_mock_client(
            _make_mock_response(raw_text, content_type="text/plain")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/file.txt")
        assert result == raw_text

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_json_returned_as_is(self, mock_client_cls):
        """application/json responses should be returned without HTML parsing."""
        from hooty.tools.search_tools import create_web_fetch_tools

        json_text = '{"key": "value", "items": [1, 2, 3]}'
        mock_client = _make_mock_client(
            _make_mock_response(json_text, content_type="application/json")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/api/data")
        assert result == json_text

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_markdown_returned_as_is(self, mock_client_cls):
        """text/markdown responses should be returned without HTML parsing."""
        from hooty.tools.search_tools import create_web_fetch_tools

        md_text = "# Title\n\n- item 1\n- item 2"
        mock_client = _make_mock_client(
            _make_mock_response(md_text, content_type="text/markdown")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/README.md")
        assert result == md_text

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_html_still_parsed(self, mock_client_cls):
        """text/html responses should still be parsed with BeautifulSoup."""
        from hooty.tools.search_tools import create_web_fetch_tools

        html = "<html><body><p>Parsed content</p><script>evil()</script></body></html>"
        mock_client = _make_mock_client(
            _make_mock_response(html, content_type="text/html; charset=utf-8")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/")
        assert "Parsed content" in result
        assert "evil()" not in result

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_no_content_type_defaults_to_html(self, mock_client_cls):
        """Missing Content-Type should default to HTML parsing."""
        from hooty.tools.search_tools import create_web_fetch_tools

        html = "<html><body><p>Default parsing</p><script>js()</script></body></html>"
        mock_client = _make_mock_client(
            _make_mock_response(html, content_type="")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/")
        assert "Default parsing" in result
        assert "js()" not in result

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_binary_returns_error(self, mock_client_cls):
        """Binary Content-Type should return an error message."""
        from hooty.tools.search_tools import create_web_fetch_tools

        mock_client = _make_mock_client(
            _make_mock_response("PNG binary data", content_type="image/png")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/image.png")
        assert "Binary content" in result
        assert "image/png" in result

    @patch("hooty.tools.search_tools.httpx.Client")
    def test_no_link_following_for_non_html(self, mock_client_cls):
        """Non-HTML responses should not trigger link following even with max_depth=2."""
        from hooty.tools.search_tools import create_web_fetch_tools

        json_text = '{"links": ["https://example.com/page2"]}'
        mock_client = _make_mock_client(
            _make_mock_response(json_text, content_type="application/json")
        )
        mock_client_cls.return_value = mock_client

        toolkit = create_web_fetch_tools()
        fn = _get_web_fetch_fn(toolkit)
        result = fn.entrypoint(url="https://example.com/api", max_depth=2, max_links=3)
        # Should return just the JSON, with only 1 call (no link following)
        assert result == json_text
        mock_client.get.assert_called_once()
