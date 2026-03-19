"""Tests for shared dev tool command whitelist."""

import pytest

from hooty.tools.dev_commands import DEV_TOOL_COMMANDS


class TestDevToolCommands:
    """Test DEV_TOOL_COMMANDS constant."""

    def test_not_empty(self):
        assert len(DEV_TOOL_COMMANDS) > 0

    def test_all_lowercase(self):
        for cmd in DEV_TOOL_COMMANDS:
            assert cmd == cmd.lower(), f"Command '{cmd}' is not lowercase"

    def test_no_duplicates(self):
        assert len(DEV_TOOL_COMMANDS) == len(set(DEV_TOOL_COMMANDS))

    @pytest.mark.parametrize(
        "cmd",
        [
            # General
            "git",
            "make",
            "docker",
            # Python
            "python",
            "uv",
            "ruff",
            "pytest",
            # JavaScript / TypeScript
            "node",
            "npm",
            "tsc",
            # Java
            "java",
            "mvn",
            "gradle",
            # Go
            "go",
            # Rust
            "cargo",
            "rustc",
            # C / C++
            "gcc",
            "cmake",
            # Ruby
            "ruby",
            "gem",
            # .NET
            "dotnet",
        ],
    )
    def test_contains_representative_commands(self, cmd):
        assert cmd in DEV_TOOL_COMMANDS
