"""Tests for MCP tools: health check, StderrPipe, and create_mcp_tools."""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock

import pytest

from hooty.tools.mcp_tools import _StderrPipe, check_mcp_health, create_mcp_tools


def _run(coro):
    return asyncio.run(coro)


class _FakeMCPTools:
    """Minimal fake of agno MCPTools for testing."""

    def __init__(
        self, *, prefix: str, initialized: bool, alive: bool,
        connect_succeeds: bool = True, server_name: str | None = None,
    ) -> None:
        self.tool_name_prefix = prefix
        self._hooty_server_name = server_name
        self._initialized = initialized
        self._alive = alive
        self._connect_succeeds = connect_succeeds
        self.connect_called = False

    async def connect(self) -> None:
        self.connect_called = True
        if self._connect_succeeds:
            self._initialized = True

    async def is_alive(self) -> bool:
        return self._alive


@pytest.fixture()
def _patch_mcp_import(monkeypatch):
    """Patch isinstance check so _FakeMCPTools passes as MCPTools."""
    import agno.tools.mcp as _mcp_mod

    monkeypatch.setattr(_mcp_mod, "MCPTools", _FakeMCPTools)


# ── check_mcp_health ──


def test_health_check_connects_and_succeeds(_patch_mcp_import):
    """Uninitialized tool should be connected during health check."""
    tools = [_FakeMCPTools(prefix="mcp__foo_", server_name="foo", initialized=False, alive=True)]
    failed = _run(check_mcp_health(tools))
    assert failed == []
    assert tools[0].connect_called


def test_health_check_already_initialized(_patch_mcp_import):
    tools = [_FakeMCPTools(prefix="mcp__foo_", server_name="foo", initialized=True, alive=True)]
    failed = _run(check_mcp_health(tools))
    assert failed == []
    assert not tools[0].connect_called  # no need to connect again


def test_health_check_connect_fails(_patch_mcp_import):
    tools = [_FakeMCPTools(
        prefix="mcp__bar_", server_name="bar", initialized=False, alive=False,
        connect_succeeds=False,
    )]
    failed = _run(check_mcp_health(tools))
    assert failed == ["bar"]


def test_health_check_not_alive(_patch_mcp_import):
    tools = [_FakeMCPTools(prefix="mcp__baz_", server_name="baz", initialized=True, alive=False)]
    failed = _run(check_mcp_health(tools))
    assert failed == ["baz"]


def test_health_check_mixed(_patch_mcp_import):
    tools = [
        _FakeMCPTools(prefix="mcp__ok_", server_name="ok", initialized=True, alive=True),
        _FakeMCPTools(prefix="mcp__bad_", server_name="bad", initialized=False, alive=False, connect_succeeds=False),
        _FakeMCPTools(prefix="mcp__dead_", server_name="dead", initialized=True, alive=False),
    ]
    failed = _run(check_mcp_health(tools))
    assert "bad" in failed
    assert "dead" in failed
    assert "ok" not in failed


def test_health_check_with_console(_patch_mcp_import):
    console = MagicMock()
    tools = [
        _FakeMCPTools(prefix="mcp__ok_", server_name="ok", initialized=True, alive=True),
        _FakeMCPTools(prefix="mcp__fail_", server_name="fail", initialized=False, alive=False, connect_succeeds=False),
    ]
    _run(check_mcp_health(tools, console_out=console))
    assert console.print.call_count == 2


def test_health_check_empty_list():
    failed = _run(check_mcp_health([]))
    assert failed == []


def test_health_check_non_mcp_tools_skipped():
    """Non-MCPTools objects in the list should be silently skipped."""
    tools = [MagicMock(spec=[])]  # not an MCPTools instance
    failed = _run(check_mcp_health(tools))
    assert failed == []


def test_health_check_connect_exception_handled(_patch_mcp_import):
    """connect() raising an exception should be caught, not propagated."""
    tool = _FakeMCPTools(prefix="mcp__err_", server_name="err", initialized=False, alive=False)

    async def _boom():
        raise RuntimeError("connection refused")

    tool.connect = _boom
    failed = _run(check_mcp_health([tool]))
    assert failed == ["err"]


# ── _StderrPipe ──


def test_stderr_pipe_has_fileno():
    pipe = _StderrPipe("test")
    try:
        fd = pipe.fileno()
        assert isinstance(fd, int)
    finally:
        pipe.close()


def test_stderr_pipe_logs_lines(caplog):
    with caplog.at_level(logging.DEBUG, logger="hooty.tools.mcp_tools"):
        pipe = _StderrPipe("test-server")
        pipe.write("hello\n")
        pipe.flush()
        # close() joins the reader thread, ensuring all lines are logged
        pipe.close()
    assert "MCP[test-server] stderr: hello" in caplog.text


def test_stderr_pipe_close_is_safe():
    pipe = _StderrPipe("x")
    pipe.close()
    # Second close should not raise
    pipe.close()


def test_stderr_pipe_write_after_close():
    pipe = _StderrPipe("x")
    pipe.close()
    # Should not raise
    result = pipe.write("ignored\n")
    assert result == len("ignored\n")


def test_stderr_pipe_passthrough(caplog, capsys):
    with caplog.at_level(logging.DEBUG, logger="hooty.tools.mcp_tools"):
        pipe = _StderrPipe("srv", passthrough=True)
        pipe.write("visible\n")
        pipe.flush()
        pipe.close()
    assert "MCP[srv] stderr: visible" in caplog.text
    captured = capsys.readouterr()
    assert "[srv] visible" in captured.err


def test_stderr_pipe_empty_lines_skipped(caplog):
    pipe = _StderrPipe("srv")
    try:
        with caplog.at_level(logging.DEBUG, logger="hooty.tools.mcp_tools"):
            pipe.write("\n\n\n")
            pipe.flush()
    finally:
        pipe.close()
    assert "stderr" not in caplog.text


# ── create_mcp_tools — headers ──


class _FakeMCPToolsCreated:
    """Captures constructor args for MCPTools."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self._hooty_server_name = None


class _FakeSSEClientParams:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeStreamableHTTPClientParams:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


@pytest.fixture()
def _patch_mcp_for_create(monkeypatch):
    """Patch MCPTools and params classes for create_mcp_tools tests."""
    import agno.tools.mcp as _mcp_mod

    monkeypatch.setattr(_mcp_mod, "MCPTools", _FakeMCPToolsCreated)
    monkeypatch.setattr(
        "hooty.tools.mcp_tools.MCPTools",
        _FakeMCPToolsCreated,
        raising=False,
    )

    # Patch the lazy imports inside create_mcp_tools
    import hooty.tools.mcp_tools as _mod

    # We need to patch at module level since the imports happen inside the function
    monkeypatch.setattr(
        f"{_mod.__name__}.MCPTools",
        _FakeMCPToolsCreated,
        raising=False,
    )


def test_create_mcp_tools_url_with_headers_streamable_http(_patch_mcp_for_create, monkeypatch):
    """URL + headers (no transport) should use StreamableHTTPClientParams."""
    captured_params = {}

    class FakeStreamableHTTP:
        def __init__(self, **kw):
            captured_params.update(kw)
            self._data = kw

    class FakeMCP:
        def __init__(self, **kw):
            self.kwargs = kw
            self._hooty_server_name = None

    import agno.tools.mcp as _mcp_mod
    monkeypatch.setattr(_mcp_mod, "MCPTools", FakeMCP)
    monkeypatch.setattr(
        "agno.tools.mcp.StreamableHTTPClientParams", FakeStreamableHTTP
    )

    config = {
        "my-api": {
            "url": "https://api.example.com",
            "headers": {"Authorization": "Bearer tok"},
        }
    }
    tools, warnings = create_mcp_tools(config)
    assert len(tools) == 1
    assert warnings == []
    # Should have used server_params, not url=
    assert "server_params" in tools[0].kwargs
    assert captured_params["url"] == "https://api.example.com"
    assert captured_params["headers"] == {"Authorization": "Bearer tok"}


def test_create_mcp_tools_url_with_headers_sse(_patch_mcp_for_create, monkeypatch):
    """URL + headers + transport=sse should use SSEClientParams."""
    captured_params = {}

    class FakeSSE:
        def __init__(self, **kw):
            captured_params.update(kw)
            self._data = kw

    class FakeMCP:
        def __init__(self, **kw):
            self.kwargs = kw
            self._hooty_server_name = None

    import agno.tools.mcp as _mcp_mod
    monkeypatch.setattr(_mcp_mod, "MCPTools", FakeMCP)
    monkeypatch.setattr("agno.tools.mcp.SSEClientParams", FakeSSE)

    config = {
        "my-sse": {
            "url": "http://localhost:3000/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer tok"},
        }
    }
    tools, warnings = create_mcp_tools(config)
    assert len(tools) == 1
    assert warnings == []
    assert "server_params" in tools[0].kwargs
    assert captured_params["url"] == "http://localhost:3000/sse"
    assert captured_params["headers"] == {"Authorization": "Bearer tok"}


def test_create_mcp_tools_url_without_headers_unchanged(_patch_mcp_for_create, monkeypatch):
    """URL without headers should use the url= kwarg directly (backward compat)."""

    class FakeMCP:
        def __init__(self, **kw):
            self.kwargs = kw
            self._hooty_server_name = None

    import agno.tools.mcp as _mcp_mod
    monkeypatch.setattr(_mcp_mod, "MCPTools", FakeMCP)

    config = {
        "my-api": {"url": "https://api.example.com"},
    }
    tools, warnings = create_mcp_tools(config)
    assert len(tools) == 1
    assert warnings == []
    assert tools[0].kwargs["url"] == "https://api.example.com"
    assert "server_params" not in tools[0].kwargs
