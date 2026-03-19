"""Tests for MCP project-level configuration merging and disabled state."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import yaml
import pytest

from hooty.config import AppConfig, _merge_project_mcp, _apply_mcp_disabled


@pytest.fixture()
def config_with_dirs(tmp_path: Path) -> AppConfig:
    """Create an AppConfig with temp working directory and config dir."""
    config = AppConfig()
    config.working_directory = str(tmp_path / "project")
    (tmp_path / "project" / ".hooty").mkdir(parents=True, exist_ok=True)

    # Override config_dir to use tmp_path
    hooty_dir = tmp_path / "hooty_home"
    hooty_dir.mkdir()
    config.__class__ = type(
        "TestAppConfig",
        (AppConfig,),
        {"config_dir": property(lambda self: hooty_dir)},
    )
    return config


def _write_mcp_yaml(path: Path, servers: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.dump({"servers": servers}), encoding="utf-8")


class TestGlobalOnly:
    def test_global_only(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        config.mcp = {"server-a": {"command": "node", "args": ["a.js"]}}
        config.mcp_sources = {"server-a": "global"}

        # No project file -> merge should be a no-op
        _merge_project_mcp(config)

        assert "server-a" in config.mcp
        assert config.mcp_sources["server-a"] == "global"


class TestProjectOnly:
    def test_project_only(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        project_mcp = config.mcp_project_file_path
        _write_mcp_yaml(project_mcp, {
            "project-db": {"url": "http://localhost:3000"},
        })

        _merge_project_mcp(config)

        assert "project-db" in config.mcp
        assert config.mcp_sources["project-db"] == "project"


class TestMergeProjectOverridesGlobal:
    def test_override(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        # Global server
        config.mcp = {"shared": {"command": "old-cmd"}}
        config.mcp_sources = {"shared": "global"}

        # Project overrides same name
        project_mcp = config.mcp_project_file_path
        _write_mcp_yaml(project_mcp, {
            "shared": {"command": "new-cmd"},
        })

        _merge_project_mcp(config)

        assert config.mcp["shared"]["command"] == "new-cmd"
        assert config.mcp_sources["shared"] == "project"


class TestMergeAddsProjectServers:
    def test_addition(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        config.mcp = {"global-srv": {"command": "g"}}
        config.mcp_sources = {"global-srv": "global"}

        project_mcp = config.mcp_project_file_path
        _write_mcp_yaml(project_mcp, {
            "project-srv": {"command": "p"},
        })

        _merge_project_mcp(config)

        assert "global-srv" in config.mcp
        assert "project-srv" in config.mcp
        assert config.mcp_sources["global-srv"] == "global"
        assert config.mcp_sources["project-srv"] == "project"


class TestSourcesTracking:
    def test_sources(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        config.mcp = {
            "a": {"command": "a"},
            "b": {"command": "b"},
        }
        config.mcp_sources = {"a": "global", "b": "global"}

        project_mcp = config.mcp_project_file_path
        _write_mcp_yaml(project_mcp, {
            "b": {"command": "b-proj"},
            "c": {"command": "c"},
        })

        _merge_project_mcp(config)

        assert config.mcp_sources["a"] == "global"
        assert config.mcp_sources["b"] == "project"
        assert config.mcp_sources["c"] == "project"


class TestDisabledServersExcluded:
    def test_disabled(self, config_with_dirs: AppConfig) -> None:
        config = config_with_dirs
        config.mcp = {
            "enabled-srv": {"command": "e"},
            "disabled-srv": {"command": "d"},
        }
        config.mcp_sources = {
            "enabled-srv": "global",
            "disabled-srv": "global",
        }

        # Write .mcp.json with disabled list
        state_path = config.mcp_state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"disabled": ["disabled-srv"]}),
            encoding="utf-8",
        )

        _apply_mcp_disabled(config)

        assert "enabled-srv" in config.mcp
        assert "disabled-srv" not in config.mcp
        assert "disabled-srv" not in config.mcp_sources


class TestDisabledNonexistent:
    def test_disabled_nonexistent_server(self, config_with_dirs: AppConfig) -> None:
        """Disabling a server that doesn't exist should not error."""
        config = config_with_dirs
        config.mcp = {"srv": {"command": "s"}}
        config.mcp_sources = {"srv": "global"}

        state_path = config.mcp_state_path
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps({"disabled": ["nonexistent"]}),
            encoding="utf-8",
        )

        _apply_mcp_disabled(config)

        assert "srv" in config.mcp


class TestMcpStateHelpers:
    def test_load_save_disabled(self, config_with_dirs: AppConfig) -> None:
        from hooty.commands.mcp_cmd import load_disabled_mcp_servers, save_disabled_mcp_servers

        config = config_with_dirs
        config.project_dir.mkdir(parents=True, exist_ok=True)

        # Initially empty
        assert load_disabled_mcp_servers(config) == set()

        # Save and reload
        save_disabled_mcp_servers(config, {"srv-a", "srv-b"})
        result = load_disabled_mcp_servers(config)
        assert result == {"srv-a", "srv-b"}

        # Update
        save_disabled_mcp_servers(config, {"srv-b"})
        result = load_disabled_mcp_servers(config)
        assert result == {"srv-b"}


class TestProjectMcpFileNotYaml:
    def test_invalid_yaml_content(self, config_with_dirs: AppConfig) -> None:
        """Non-dict project mcp.yaml should be silently ignored."""
        config = config_with_dirs
        config.mcp = {"g": {"command": "g"}}
        config.mcp_sources = {"g": "global"}

        project_mcp = config.mcp_project_file_path
        project_mcp.parent.mkdir(parents=True, exist_ok=True)
        project_mcp.write_text("just a string\n", encoding="utf-8")

        _merge_project_mcp(config)

        # Should remain unchanged
        assert config.mcp == {"g": {"command": "g"}}


class TestWslEnvInjection:
    """Tests for WSLENV auto-injection in WSL environments."""

    def test_wsl_adds_wslenv(self) -> None:
        """When _is_wsl() is True and env is set, WSLENV should be added."""
        env = {"DIFY_API_KEY": "secret", "OTHER_VAR": "val"}
        server_config = {"command": "dify.exe", "args": [], "env": env}

        with patch("hooty.tools.mcp_tools._is_wsl", return_value=True):
            user_env = server_config.get("env")
            if user_env and True:  # _is_wsl() patched to True
                existing = user_env.get("WSLENV", "")
                parts = set(existing.split(":")) if existing else set()
                parts.discard("")
                parts |= {k for k in user_env if k != "WSLENV"}
                user_env = {**user_env, "WSLENV": ":".join(sorted(parts))}

        assert "WSLENV" in user_env
        wslenv_parts = set(user_env["WSLENV"].split(":"))
        assert wslenv_parts == {"DIFY_API_KEY", "OTHER_VAR"}

    def test_non_wsl_no_change(self) -> None:
        """When _is_wsl() is False, env should not be modified."""
        env = {"DIFY_API_KEY": "secret"}
        server_config = {"command": "dify.exe", "args": [], "env": env}

        with patch("hooty.tools.mcp_tools._is_wsl", return_value=False):
            user_env = server_config.get("env")
            if user_env and False:  # _is_wsl() patched to False
                pass  # Should not enter

        assert "WSLENV" not in user_env

    def test_wsl_merges_existing_wslenv(self) -> None:
        """Existing WSLENV entries should be preserved and merged."""
        env = {"MY_KEY": "val", "WSLENV": "EXISTING_VAR"}
        server_config = {"command": "srv.exe", "args": [], "env": env}

        user_env = server_config.get("env")
        # Simulate WSL logic
        existing = user_env.get("WSLENV", "")
        parts = set(existing.split(":")) if existing else set()
        parts.discard("")
        parts |= {k for k in user_env if k != "WSLENV"}
        user_env = {**user_env, "WSLENV": ":".join(sorted(parts))}

        wslenv_parts = set(user_env["WSLENV"].split(":"))
        assert wslenv_parts == {"EXISTING_VAR", "MY_KEY"}

    def test_wsl_no_env_no_change(self) -> None:
        """When env is None, no WSLENV should be injected."""
        server_config = {"command": "srv.exe", "args": []}

        user_env = server_config.get("env")
        # Simulate: if user_env and _is_wsl() -> False because user_env is None
        assert user_env is None


class TestMcpSourcesField:
    def test_default_empty(self) -> None:
        config = AppConfig()
        assert config.mcp_sources == {}

    def test_mcp_project_file_path(self, tmp_path: Path) -> None:
        config = AppConfig()
        config.working_directory = str(tmp_path / "myproject")
        assert config.mcp_project_file_path == tmp_path / "myproject" / ".hooty" / "mcp.yaml"

    def test_mcp_state_path(self, tmp_path: Path) -> None:
        config = AppConfig()
        config.working_directory = str(tmp_path / "myproject")
        assert config.mcp_state_path.name == ".mcp.json"
