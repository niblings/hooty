"""MCP server connection management for Hooty."""

from __future__ import annotations

import io
import logging
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)

DEFAULT_MCP_TIMEOUT = 30

console = Console()


@lru_cache(maxsize=1)
def _is_wsl() -> bool:
    """Detect if running inside WSL (Windows Subsystem for Linux)."""
    try:
        return "microsoft" in Path("/proc/version").read_text().lower()
    except OSError:
        return False


def create_mcp_tools(
    mcp_config: dict[str, dict[str, Any]],
    *,
    mcp_debug: bool = False,
) -> tuple[list, list[str]]:
    """Create MCP tools from mcp.yaml servers section.

    Supports three connection types:
    - stdio: command + args
    - http (streamable-http): url (default for url-based)
    - sse: url + transport: sse

    Returns (tools, warnings) — warnings are deferred so the caller
    can display them after a spinner finishes.
    """
    warnings: list[str] = []

    try:
        from agno.tools.mcp import MCPTools
    except ImportError:
        warnings.append(
            "  [yellow]⚠ MCP tools require additional packages.[/yellow]\n"
            "  [dim]pip install hooty[mcp][/dim]"
        )
        return [], warnings

    tools = []
    for name, server_config in mcp_config.items():
        try:
            if not isinstance(server_config, dict):
                warnings.append(
                    f"  [yellow]⚠ MCP server '{name}': config must be a mapping[/yellow]"
                )
                continue

            timeout = server_config.get("timeout", DEFAULT_MCP_TIMEOUT)
            # Prefix: "mcp__{safe}_" + Agno appends "_" → "mcp__{safe}__tool_name"
            safe_name = name.replace("-", "_")
            prefix = f"mcp__{safe_name}_"
            if "url" in server_config:
                url = server_config["url"]
                if not url or not isinstance(url, str):
                    warnings.append(
                        f"  [yellow]⚠ MCP server '{name}': url must be a non-empty string[/yellow]"
                    )
                    continue
                raw_transport = server_config.get("transport")
                # Normalize: "http" and "streamable-http" are equivalent (default)
                transport = "sse" if raw_transport == "sse" else None
                headers = server_config.get("headers")
                if headers:
                    if transport == "sse":
                        from agno.tools.mcp import SSEClientParams

                        params = SSEClientParams(url=url, headers=headers)
                    else:
                        from agno.tools.mcp import StreamableHTTPClientParams

                        params = StreamableHTTPClientParams(url=url, headers=headers)
                    url_tool = MCPTools(
                        server_params=params,
                        timeout_seconds=timeout,
                        tool_name_prefix=prefix,
                    )
                else:
                    url_tool = MCPTools(
                        url=url,
                        transport=transport,
                        timeout_seconds=timeout,
                        tool_name_prefix=prefix,
                    )
                url_tool._hooty_server_name = name  # type: ignore[attr-defined]
                tools.append(url_tool)
            elif "command" in server_config:
                command = server_config["command"]
                if not command or not isinstance(command, str):
                    warnings.append(
                        f"  [yellow]⚠ MCP server '{name}': command must be a non-empty string[/yellow]"
                    )
                    continue
                args = server_config.get("args", [])
                if not isinstance(args, list):
                    warnings.append(
                        f"  [yellow]⚠ MCP server '{name}': args must be a list[/yellow]"
                    )
                    continue

                from mcp.client.stdio import StdioServerParameters

                user_env = server_config.get("env")
                if user_env is not None and not isinstance(user_env, dict):
                    warnings.append(
                        f"  [yellow]⚠ MCP server '{name}': env must be a mapping[/yellow]"
                    )
                    continue

                # WSL: add WSLENV so custom env vars are forwarded to Windows processes
                if user_env and _is_wsl():
                    existing = user_env.get("WSLENV", "")
                    parts = set(existing.split(":")) if existing else set()
                    parts.discard("")
                    parts |= {k for k in user_env if k != "WSLENV"}
                    user_env = {**user_env, "WSLENV": ":".join(sorted(parts))}

                params = StdioServerParameters(
                    command=command,
                    args=args,
                    env=user_env,
                )
                tool = MCPTools(
                    server_params=params,
                    timeout_seconds=timeout,
                    tool_name_prefix=prefix,
                )
                tool._hooty_server_name = name  # type: ignore[attr-defined]
                _suppress_stdio_stderr(tool, server_name=name, passthrough=mcp_debug)
                tools.append(tool)
            else:
                warnings.append(
                    f"  [yellow]⚠ MCP server '{name}': url or command is required[/yellow]"
                )
        except Exception as e:
            # Show only the first line of the error (pydantic etc. are verbose)
            err_first_line = str(e).split("\n", 1)[0]
            warnings.append(
                f"  [yellow]⚠ MCP server '{name}': {err_first_line}[/yellow]"
            )

    return tools, warnings


async def check_mcp_health(
    tools: list,
    console_out: Console | None = None,
) -> list[str]:
    """Connect MCP tools eagerly and report health status.

    Agno normally defers MCP connection until the first arun().
    This function connects each tool up-front so the user gets
    immediate feedback about which servers are reachable.

    Returns list of server names that failed health check.
    """
    try:
        from agno.tools.mcp import MCPTools
    except ImportError:
        return []

    failed = []
    for tool in tools:
        if not isinstance(tool, MCPTools):
            continue
        # _hooty_server_name is set by create_mcp_tools() for display
        name = getattr(tool, "_hooty_server_name", None)
        if name is None:
            name = getattr(tool, "tool_name_prefix", "unknown").strip("_")

        # Attempt connection if not yet connected
        if not tool._initialized:
            try:
                await tool.connect()
            except Exception:
                logger.debug("MCP[%s] connect() failed", name, exc_info=True)

        # Evaluate status after connection attempt
        if not tool._initialized:
            failed.append(name)
            if console_out:
                console_out.print(f"  [red]✗ MCP server '{name}' failed to connect[/red]")
        elif not await tool.is_alive():
            failed.append(name)
            if console_out:
                console_out.print(f"  [red]✗ MCP server '{name}' is not responding[/red]")
        else:
            if console_out:
                console_out.print(f"  [green]✓ MCP server '{name}' connected[/green]")
    return failed


class _StderrPipe:
    """OS-level pipe with a reader thread that feeds lines to logger.debug.

    subprocess / anyio.open_process require a real file descriptor for
    stderr, so a pure-Python file-like object won't work.  This class
    creates an ``os.pipe()``, wraps the write-end as a ``TextIOWrapper``
    (which has ``fileno()``), and spawns a daemon thread that reads lines
    from the read-end and logs them.

    When *passthrough* is True (``--mcp-debug``), lines are also echoed
    to ``sys.stderr``.
    """

    def __init__(self, server_name: str, *, passthrough: bool = False) -> None:
        self._name = server_name
        self._passthrough = passthrough
        self._muted = False

        read_fd, write_fd = os.pipe()
        # Write-end: handed to subprocess as stderr
        self._write_file = io.open(write_fd, "w", encoding="utf-8", errors="replace")
        # Read-end: consumed by daemon thread
        self._read_file = io.open(read_fd, "r", encoding="utf-8", errors="replace")
        self._thread = threading.Thread(
            target=self._drain, daemon=True, name=f"mcp-stderr-{server_name}",
        )
        self._thread.start()

    # ── TextIO-compatible surface (passed to stdio_client as errlog) ──

    def write(self, data: str) -> int:
        try:
            return self._write_file.write(data)
        except (ValueError, OSError):
            return len(data)

    def flush(self) -> None:
        try:
            self._write_file.flush()
        except (ValueError, OSError):
            pass

    def fileno(self) -> int:
        return self._write_file.fileno()

    @property
    def closed(self) -> bool:
        return self._write_file.closed

    # ── lifecycle ──

    def mute(self) -> None:
        """Suppress all further output (used before shutdown to hide process death noise)."""
        self._muted = True

    def close(self) -> None:
        """Close write-end; reader thread will drain remaining data and exit."""
        try:
            self._write_file.close()
        except (ValueError, OSError):
            pass
        self._thread.join(timeout=2.0)
        try:
            self._read_file.close()
        except (ValueError, OSError):
            pass

    # ── internal ──

    def _drain(self) -> None:
        """Read lines from the pipe and forward to logger (+ stderr)."""
        import sys

        try:
            for line in self._read_file:
                if self._muted:
                    continue
                line = line.rstrip("\n")
                if not line.strip():
                    continue
                logger.debug("MCP[%s] stderr: %s", self._name, line)
                if self._passthrough:
                    try:
                        sys.stderr.write(f"[{self._name}] {line}\n")
                    except (ValueError, OSError):
                        pass
        except (ValueError, OSError):
            pass  # pipe closed


def _suppress_stdio_stderr(
    tool: Any, server_name: str = "unknown", *, passthrough: bool = False,
) -> None:
    """Patch MCPTools._connect to redirect MCP server stderr to logger.

    agno's MCPTools calls stdio_client() without errlog param,
    causing server stderr to leak into the terminal.

    stderr is redirected through _StderrPipe which provides a real
    file descriptor (required by subprocess) and a daemon thread that
    forwards lines to logger.debug (visible with --debug).  When
    *passthrough* is True (--mcp-debug), lines are also echoed to
    sys.stderr.

    A fresh _StderrPipe is created on each connect() and closed on
    close(), so that repeated connect/close cycles work correctly.
    """

    original_connect = tool._connect
    tool._stderr_pipe = None

    async def _patched_connect() -> None:
        import agno.tools.mcp.mcp as _mcp_mod

        # Create fresh stderr pipe for each connection cycle
        stderr_pipe = _StderrPipe(server_name, passthrough=passthrough)
        tool._stderr_pipe = stderr_pipe

        def _quiet_stdio_client(server_params: Any) -> Any:
            from mcp.client.stdio import stdio_client

            return stdio_client(server_params, errlog=stderr_pipe)

        _orig = _mcp_mod.stdio_client
        _mcp_mod.stdio_client = _quiet_stdio_client
        try:
            await original_connect()
        finally:
            _mcp_mod.stdio_client = _orig

    original_close = tool.close

    async def _patched_close() -> None:
        # Mute before closing — subprocess may emit noise as it dies
        if tool._stderr_pipe is not None:
            tool._stderr_pipe.mute()
        await original_close()
        if tool._stderr_pipe is not None:
            tool._stderr_pipe.close()
            tool._stderr_pipe = None

    tool._connect = _patched_connect
    tool.close = _patched_close
