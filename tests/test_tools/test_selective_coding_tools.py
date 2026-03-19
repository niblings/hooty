"""Tests for SelectiveCodingTools and create_coding_tools blocked_tools parameter."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from hooty.tools.coding_tools import (
    ConfirmableCodingTools,
    PlanModeCodingTools,
    SelectiveCodingTools,
    create_coding_tools,
)


@pytest.fixture()
def work_dir(tmp_path):
    """Create a working directory with a test file."""
    test_file = tmp_path / "hello.txt"
    test_file.write_text("hello world\n")
    return str(tmp_path)


class TestSelectiveCodingTools:
    """SelectiveCodingTools blocks specified methods and passes through others."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_blocked_write_file(self, work_dir):
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"write_file"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
        )
        result = tools.write_file("test.txt", "content")
        assert "Error" in result
        assert "write_file is not available" in result

    def test_blocked_edit_file(self, work_dir):
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"edit_file"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
        )
        result = tools.edit_file("hello.txt", "hello", "goodbye")
        assert "Error" in result
        assert "edit_file is not available" in result

    def test_blocked_run_shell(self, work_dir):
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"run_shell"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
        )
        result = tools.run_shell("echo hello")
        assert "Error" in result
        assert "run_shell is not available" in result

    def test_unblocked_write_file(self, work_dir):
        """write_file passes through when not blocked (confirm_ref=False skips confirm)."""
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"run_shell"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
        )
        result = tools.write_file("new.txt", "content")
        assert "Error" not in result or "not available" not in result
        assert (Path(work_dir) / "new.txt").exists()

    def test_unblocked_run_shell(self, work_dir):
        """run_shell passes through when not blocked (confirm_ref=False skips confirm)."""
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"write_file", "edit_file"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
            allowed_commands=["echo"],
        )
        result = tools.run_shell("echo hello")
        assert "not available" not in result

    def test_mixed_blocking(self, work_dir):
        """Only specified methods are blocked."""
        tools = SelectiveCodingTools(
            confirm_ref=[False],
            blocked_tools=frozenset({"write_file", "run_shell"}),
            base_dir=Path(work_dir),
            all=True,
            restrict_to_base_dir=True,
        )
        assert "not available" in tools.write_file("x.txt", "c")
        assert "not available" in tools.run_shell("echo x")
        # edit_file should pass through
        result = tools.edit_file("hello.txt", "hello world", "goodbye world")
        assert "edit_file is not available" not in result


class TestCreateCodingToolsBlockedTools:
    """create_coding_tools returns correct class based on blocked_tools."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def test_no_blocked_tools_with_confirm(self, work_dir):
        tools = create_coding_tools(work_dir, confirm_ref=[True])
        assert isinstance(tools, ConfirmableCodingTools)
        assert not isinstance(tools, SelectiveCodingTools)

    def test_blocked_tools_returns_selective(self, work_dir):
        tools = create_coding_tools(
            work_dir, blocked_tools=frozenset({"run_shell"})
        )
        assert isinstance(tools, SelectiveCodingTools)

    def test_blocked_tools_with_confirm_ref(self, work_dir):
        tools = create_coding_tools(
            work_dir,
            confirm_ref=[True],
            blocked_tools=frozenset({"write_file"}),
        )
        assert isinstance(tools, SelectiveCodingTools)

    def test_plan_mode_takes_precedence(self, work_dir):
        tools = create_coding_tools(
            work_dir,
            plan_mode=True,
            blocked_tools=frozenset({"run_shell"}),
        )
        assert isinstance(tools, PlanModeCodingTools)

    def test_empty_blocked_tools_no_effect(self, work_dir):
        """Empty frozenset should not create SelectiveCodingTools."""
        tools = create_coding_tools(
            work_dir, confirm_ref=[True], blocked_tools=frozenset()
        )
        assert isinstance(tools, ConfirmableCodingTools)
        assert not isinstance(tools, SelectiveCodingTools)


class TestBuildCodingToolsIntegration:
    """Test _build_coding_tools mapping from disallowed to correct class."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    def _build(self, disallowed_tools: list[str]):
        from hooty.agent_store import NEVER_INHERIT
        from hooty.config import AppConfig
        from hooty.tools.sub_agent_runner import _build_coding_tools

        config = AppConfig()
        config.working_directory = tempfile.mkdtemp()
        disallowed = set(disallowed_tools) | NEVER_INHERIT
        tools = []
        _build_coding_tools(config, disallowed, [True], tools)
        return tools[0]

    def test_all_blocked_returns_plan_mode(self):
        tools = self._build(["write_file", "edit_file", "run_shell"])
        assert isinstance(tools, PlanModeCodingTools)

    def test_shell_only_blocked_returns_selective(self):
        tools = self._build(["run_shell"])
        assert isinstance(tools, SelectiveCodingTools)
        assert "run_shell" in tools._blocked_tools

    def test_write_edit_blocked_returns_selective(self):
        tools = self._build(["write_file", "edit_file"])
        assert isinstance(tools, SelectiveCodingTools)
        assert "write_file" in tools._blocked_tools
        assert "edit_file" in tools._blocked_tools
        assert "run_shell" not in tools._blocked_tools

    def test_none_blocked_returns_confirmable(self):
        tools = self._build([])
        assert isinstance(tools, ConfirmableCodingTools)
        assert not isinstance(tools, SelectiveCodingTools)
