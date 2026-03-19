"""Tests for /mcp add and /mcp remove commands."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from hooty.config import AppConfig
from hooty.commands.mcp_cmd import (
    _cmd_mcp_add,
    _cmd_mcp_remove,
    _is_url,
    _load_mcp_yaml,
    _parse_add_options,
    _save_mcp_yaml,
    load_disabled_mcp_servers,
)


@pytest.fixture()
def config_with_dirs(tmp_path: Path) -> AppConfig:
    """Create an AppConfig with temp working directory and config dir."""
    config = AppConfig()
    config.working_directory = str(tmp_path / "project")
    (tmp_path / "project" / ".hooty").mkdir(parents=True, exist_ok=True)

    hooty_dir = tmp_path / "hooty_home"
    hooty_dir.mkdir()
    config.__class__ = type(
        "TestAppConfig",
        (AppConfig,),
        {"config_dir": property(lambda self: hooty_dir)},
    )
    return config


@pytest.fixture()
def mock_ctx(config_with_dirs: AppConfig) -> MagicMock:
    """Create a mock CommandContext with the test config."""
    ctx = MagicMock()
    ctx.config = config_with_dirs
    ctx.console = MagicMock()
    return ctx


# -- _parse_add_options -----------------------------------------------------


class TestParseAddOptions:
    def test_defaults(self) -> None:
        is_global, env, headers, transport, rest = _parse_add_options(
            ["myserver", "node", "s.js"]
        )
        assert is_global is False
        assert env == {}
        assert headers == {}
        assert transport is None
        assert rest == ["myserver", "node", "s.js"]

    def test_global_flag(self) -> None:
        is_global, env, headers, transport, rest = _parse_add_options(
            ["--global", "myserver", "node"]
        )
        assert is_global is True
        assert rest == ["myserver", "node"]

    def test_env_single(self) -> None:
        is_global, env, headers, transport, rest = _parse_add_options(
            ["-e", "KEY=val", "myserver", "node"]
        )
        assert env == {"KEY": "val"}
        assert rest == ["myserver", "node"]

    def test_env_multiple(self) -> None:
        is_global, env, headers, transport, rest = _parse_add_options(
            ["-e", "A=1", "-e", "B=2", "myserver", "node"]
        )
        assert env == {"A": "1", "B": "2"}
        assert rest == ["myserver", "node"]

    def test_env_with_equals_in_value(self) -> None:
        _is_global, env, _h, _t, rest = _parse_add_options(
            ["-e", "URL=http://host?a=1&b=2", "srv", "cmd"]
        )
        assert env == {"URL": "http://host?a=1&b=2"}

    def test_header_single(self) -> None:
        _g, _e, headers, _t, rest = _parse_add_options(
            ["--header", "Authorization: Bearer tok", "srv", "http://x"]
        )
        assert headers == {"Authorization": "Bearer tok"}
        assert rest == ["srv", "http://x"]

    def test_header_multiple(self) -> None:
        _g, _e, headers, _t, rest = _parse_add_options(
            [
                "--header", "Authorization: Bearer tok",
                "--header", "X-Custom: value",
                "srv", "http://x",
            ]
        )
        assert headers == {"Authorization": "Bearer tok", "X-Custom": "value"}

    def test_header_value_with_colon(self) -> None:
        _g, _e, headers, _t, rest = _parse_add_options(
            ["--header", "X-Data: a: b: c", "srv", "http://x"]
        )
        assert headers == {"X-Data": "a: b: c"}

    def test_header_invalid_no_colon_space(self) -> None:
        _g, _e, headers, _t, rest = _parse_add_options(
            ["--header", "BadHeader", "srv", "http://x"]
        )
        # Stored with empty value — caller validates
        assert headers == {"BadHeader": ""}

    def test_transport_http(self) -> None:
        _g, _e, _h, transport, rest = _parse_add_options(
            ["--transport", "http", "srv", "http://x"]
        )
        assert transport == "http"

    def test_transport_sse(self) -> None:
        _g, _e, _h, transport, rest = _parse_add_options(
            ["--transport", "sse", "srv", "http://x"]
        )
        assert transport == "sse"

    def test_all_options_combined(self) -> None:
        is_global, env, headers, transport, rest = _parse_add_options(
            [
                "--global", "--transport", "sse",
                "--header", "Auth: tok",
                "srv", "http://x",
            ]
        )
        assert is_global is True
        assert transport == "sse"
        assert headers == {"Auth": "tok"}
        assert rest == ["srv", "http://x"]

    def test_short_header_h(self) -> None:
        _g, _e, headers, _t, rest = _parse_add_options(
            ["-h", "Authorization: Bearer tok", "srv", "http://x"]
        )
        assert headers == {"Authorization": "Bearer tok"}

    def test_long_env(self) -> None:
        _g, env, _h, _t, rest = _parse_add_options(
            ["--env", "KEY=val", "srv", "cmd"]
        )
        assert env == {"KEY": "val"}
        assert rest == ["srv", "cmd"]


# -- _load_mcp_yaml / _save_mcp_yaml ----------------------------------------


class TestMcpYamlIO:
    def test_load_nonexistent(self, tmp_path: Path) -> None:
        assert _load_mcp_yaml(tmp_path / "nope.yaml") == {}

    def test_roundtrip(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.yaml"
        servers = {"my-srv": {"command": "node", "args": ["s.js"]}}
        _save_mcp_yaml(path, servers)

        loaded = _load_mcp_yaml(path)
        assert loaded == servers

    def test_load_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "mcp.yaml"
        path.write_text("not a dict", encoding="utf-8")
        assert _load_mcp_yaml(path) == {}

    def test_save_creates_parent_dirs(self, tmp_path: Path) -> None:
        path = tmp_path / "deep" / "nested" / "mcp.yaml"
        _save_mcp_yaml(path, {"s": {"command": "c"}})
        assert path.exists()
        assert _load_mcp_yaml(path) == {"s": {"command": "c"}}


# -- /mcp add ---------------------------------------------------------------


class TestCmdMcpAdd:
    def test_add_basic(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["myserver", "node", "server.js"])

        # Check project mcp.yaml was written
        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert "myserver" in servers
        assert servers["myserver"]["command"] == "node"
        assert servers["myserver"]["args"] == ["server.js"]

        # Check success message
        mock_ctx.console.print.assert_any_call(
            "  [success]\u2713 Added server 'myserver' in project mcp.yaml[/success]"
        )

    def test_add_global(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--global", "srv", "python", "-m", "srv"])

        path = mock_ctx.config.mcp_file_path
        servers = _load_mcp_yaml(path)
        assert "srv" in servers
        assert servers["srv"]["command"] == "python"
        assert servers["srv"]["args"] == ["-m", "srv"]

    def test_add_with_env(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["-e", "API_KEY=secret", "-e", "PORT=3000", "srv", "cmd"])

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["srv"]["env"] == {"API_KEY": "secret", "PORT": "3000"}

    def test_add_no_args_shows_usage(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, [])
        mock_ctx.console.print.assert_called()
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("Usage" in s for s in call_args)

    def test_add_missing_command_shows_error(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["name-only"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("required" in s for s in call_args)

    def test_add_overwrite_existing(self, mock_ctx: MagicMock) -> None:
        path = mock_ctx.config.mcp_project_file_path
        _save_mcp_yaml(path, {"srv": {"command": "old"}})

        _cmd_mcp_add(mock_ctx, ["srv", "new-cmd", "arg1"])

        servers = _load_mcp_yaml(path)
        assert servers["srv"]["command"] == "new-cmd"
        mock_ctx.console.print.assert_any_call(
            "  [success]\u2713 Updated server 'srv' in project mcp.yaml[/success]"
        )

    def test_add_command_only_no_args(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["srv", "my-command"])

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["srv"] == {"command": "my-command"}
        assert "args" not in servers["srv"]

    def test_add_preserves_other_servers(self, mock_ctx: MagicMock) -> None:
        path = mock_ctx.config.mcp_project_file_path
        _save_mcp_yaml(path, {"existing": {"command": "keep"}})

        _cmd_mcp_add(mock_ctx, ["new-srv", "cmd"])

        servers = _load_mcp_yaml(path)
        assert servers["existing"]["command"] == "keep"
        assert servers["new-srv"]["command"] == "cmd"

    def test_add_stdio_with_header_rejected(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--header", "Auth: tok", "srv", "node", "s.js"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("--header is not supported" in s for s in call_args)

    def test_add_stdio_with_transport_rejected(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--transport", "sse", "srv", "node", "s.js"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("--transport is not supported" in s for s in call_args)


# -- /mcp add (url-based) ---------------------------------------------------


class TestCmdMcpAddUrl:
    def test_add_url_http(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["my-api", "http://localhost:3000"])

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["my-api"] == {"url": "http://localhost:3000"}
        assert "command" not in servers["my-api"]

    def test_add_url_https(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["my-api", "https://api.example.com/mcp"])

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["my-api"] == {"url": "https://api.example.com/mcp"}

    def test_add_url_global(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--global", "api", "http://host:8080"])

        path = mock_ctx.config.mcp_file_path
        servers = _load_mcp_yaml(path)
        assert servers["api"] == {"url": "http://host:8080"}

    def test_add_url_with_env_rejected(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["-e", "KEY=val", "srv", "http://localhost:3000"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("not supported" in s for s in call_args)

        # Should NOT have written anything
        path = mock_ctx.config.mcp_project_file_path
        assert not path.exists()

    def test_add_url_with_extra_args_rejected(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["srv", "http://localhost:3000", "extra"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("extra arguments" in s for s in call_args)

    def test_add_url_overwrite_stdio(self, mock_ctx: MagicMock) -> None:
        """Overwriting a stdio server with a url server should work."""
        path = mock_ctx.config.mcp_project_file_path
        _save_mcp_yaml(path, {"srv": {"command": "old"}})

        _cmd_mcp_add(mock_ctx, ["srv", "http://localhost:5000"])

        servers = _load_mcp_yaml(path)
        assert servers["srv"] == {"url": "http://localhost:5000"}
        assert "command" not in servers["srv"]

    def test_add_url_with_header(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(
            mock_ctx,
            ["--header", "Authorization: Bearer tok", "my-api", "https://api.example.com"],
        )

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["my-api"]["url"] == "https://api.example.com"
        assert servers["my-api"]["headers"] == {"Authorization": "Bearer tok"}
        assert "transport" not in servers["my-api"]

    def test_add_url_with_multiple_headers(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(
            mock_ctx,
            [
                "--header", "Authorization: Bearer tok",
                "--header", "X-Custom: value",
                "srv", "https://api.example.com",
            ],
        )

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["srv"]["headers"] == {
            "Authorization": "Bearer tok",
            "X-Custom": "value",
        }

    def test_add_url_with_transport_sse(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(
            mock_ctx,
            ["--transport", "sse", "my-sse", "http://localhost:3000/sse"],
        )

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["my-sse"]["url"] == "http://localhost:3000/sse"
        assert servers["my-sse"]["transport"] == "sse"

    def test_add_url_with_transport_http_no_key(self, mock_ctx: MagicMock) -> None:
        """transport=http is the default, so no transport key in yaml."""
        _cmd_mcp_add(
            mock_ctx,
            ["--transport", "http", "srv", "http://localhost:3000"],
        )

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["srv"] == {"url": "http://localhost:3000"}
        assert "transport" not in servers["srv"]

    def test_add_url_with_transport_and_header(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(
            mock_ctx,
            [
                "--transport", "sse",
                "--header", "Authorization: Bearer tok",
                "my-sse", "http://localhost:3000/sse",
            ],
        )

        path = mock_ctx.config.mcp_project_file_path
        servers = _load_mcp_yaml(path)
        assert servers["my-sse"] == {
            "url": "http://localhost:3000/sse",
            "transport": "sse",
            "headers": {"Authorization": "Bearer tok"},
        }

    def test_add_url_invalid_transport(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--transport", "grpc", "srv", "http://x"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("Invalid transport" in s for s in call_args)

    def test_add_url_invalid_header_format(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_add(mock_ctx, ["--header", "BadHeader", "srv", "http://x"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("Invalid header format" in s for s in call_args)


# -- _is_url ----------------------------------------------------------------


class TestIsUrl:
    def test_http(self) -> None:
        assert _is_url("http://localhost:3000") is True

    def test_https(self) -> None:
        assert _is_url("https://api.example.com") is True

    def test_command(self) -> None:
        assert _is_url("node") is False

    def test_path(self) -> None:
        assert _is_url("/usr/bin/python") is False


# -- /mcp remove ------------------------------------------------------------


class TestCmdMcpRemove:
    def test_remove_basic(self, mock_ctx: MagicMock) -> None:
        path = mock_ctx.config.mcp_project_file_path
        _save_mcp_yaml(path, {"srv": {"command": "c"}, "other": {"command": "o"}})

        _cmd_mcp_remove(mock_ctx, ["srv"])

        servers = _load_mcp_yaml(path)
        assert "srv" not in servers
        assert "other" in servers
        mock_ctx.console.print.assert_any_call(
            "  [success]\u2713 Removed server 'srv' from project mcp.yaml[/success]"
        )

    def test_remove_global(self, mock_ctx: MagicMock) -> None:
        path = mock_ctx.config.mcp_file_path
        _save_mcp_yaml(path, {"gsrv": {"command": "g"}})

        _cmd_mcp_remove(mock_ctx, ["--global", "gsrv"])

        assert not path.exists()  # File removed when empty

    def test_remove_nonexistent_shows_error(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_remove(mock_ctx, ["nosuch"])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("not found" in s for s in call_args)

    def test_remove_no_args_shows_usage(self, mock_ctx: MagicMock) -> None:
        _cmd_mcp_remove(mock_ctx, [])
        call_args = [str(c) for c in mock_ctx.console.print.call_args_list]
        assert any("Usage" in s for s in call_args)

    def test_remove_cleans_disabled_state(self, mock_ctx: MagicMock) -> None:
        config = mock_ctx.config
        path = config.mcp_project_file_path
        _save_mcp_yaml(path, {"srv": {"command": "c"}})

        # Mark as disabled
        config.project_dir.mkdir(parents=True, exist_ok=True)
        state_path = config.mcp_state_path
        state_path.write_text(
            json.dumps({"disabled": ["srv"]}), encoding="utf-8"
        )

        _cmd_mcp_remove(mock_ctx, ["srv"])

        disabled = load_disabled_mcp_servers(config)
        assert "srv" not in disabled

    def test_remove_last_server_deletes_file(self, mock_ctx: MagicMock) -> None:
        path = mock_ctx.config.mcp_project_file_path
        _save_mcp_yaml(path, {"only": {"command": "c"}})

        _cmd_mcp_remove(mock_ctx, ["only"])

        assert not path.exists()
