"""Tests for hooty.tools.sub_agent_tools module."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from hooty.agent_store import AgentDef
from hooty.tools.sub_agent_tools import SubAgentTools, _on_event, _session_stats_ref


def _make_agent_defs():
    return {
        "explore": AgentDef(
            name="explore",
            description="Codebase explorer",
            instructions="Explore the codebase",
            disallowed_tools=["write_file", "edit_file"],
            source="builtin",
        ),
        "summarize": AgentDef(
            name="summarize",
            description="Code summarizer",
            instructions="Summarize code",
            disallowed_tools=["write_file", "edit_file", "run_shell"],
            source="builtin",
        ),
    }


def _make_config():
    from hooty.config import AppConfig
    config = AppConfig()
    config.working_directory = "/tmp/test"
    return config


class TestSubAgentTools:
    def test_init(self):
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        assert tools.name == "sub_agent_tools"
        assert "explore" in tools.instructions
        assert "summarize" in tools.instructions

    def test_instructions_list_agents(self):
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        assert "Codebase explorer" in tools.instructions
        assert "Code summarizer" in tools.instructions

    def test_run_agent_unknown_name(self):
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        result = tools.run_agent("nonexistent", "do something")
        assert "Error" in result
        assert "Unknown agent" in result
        assert "explore" in result  # lists available agents

    @patch("hooty.tools.sub_agent_runner.run_sub_agent")
    def test_run_agent_success(self, mock_run):
        mock_run.return_value = "### Finding\nFound the answer"
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        result = tools.run_agent("explore", "find the entry point")
        assert result == "### Finding\nFound the answer"
        mock_run.assert_called_once()
        call_kwargs = mock_run.call_args
        assert call_kwargs.kwargs["agent_def"].name == "explore"
        assert call_kwargs.kwargs["task"] == "find the entry point"

    @patch("hooty.tools.sub_agent_runner.run_sub_agent")
    def test_run_agent_failure(self, mock_run):
        mock_run.side_effect = RuntimeError("connection failed")
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        result = tools.run_agent("explore", "do something")
        assert "Error" in result
        assert "connection failed" in result

    def test_has_run_agent_function(self):
        defs = _make_agent_defs()
        config = _make_config()
        tools = SubAgentTools(defs, config)
        # Check that run_agent is registered
        func_names = [f.name for f in tools.functions.values()]
        assert "run_agent" in func_names


class TestPowerShellToolsInheritance:
    """PowerShellTools inheritance in sub-agent tool creation."""

    @pytest.fixture(autouse=True)
    def _fast_filter(self, monkeypatch):
        monkeypatch.setattr(
            "hooty.tools.coding_tools._filter_available_commands",
            lambda cmds, **kw: list(cmds),
        )

    @patch("hooty.tools.powershell_tools.create_powershell_tools")
    def test_powershell_included_when_not_disallowed(self, mock_create_ps):
        from hooty.tools.sub_agent_runner import _create_sub_agent_tools

        mock_ps = object()
        mock_create_ps.return_value = mock_ps

        agent_def = AgentDef(
            name="writer",
            description="Writer agent",
            instructions="Write things",
            disallowed_tools=[],
            source="user",
        )
        config = _make_config()
        tools = _create_sub_agent_tools(agent_def, config)
        mock_create_ps.assert_called_once()
        assert mock_ps in tools

    @patch("hooty.tools.powershell_tools.create_powershell_tools")
    def test_powershell_excluded_when_disallowed(self, mock_create_ps):
        from hooty.tools.sub_agent_runner import _create_sub_agent_tools

        agent_def = AgentDef(
            name="explore",
            description="Explorer",
            instructions="Explore",
            disallowed_tools=["run_powershell"],
            source="builtin",
        )
        config = _make_config()
        _create_sub_agent_tools(agent_def, config)
        mock_create_ps.assert_not_called()

    @patch("hooty.tools.powershell_tools.create_powershell_tools")
    def test_powershell_none_skipped(self, mock_create_ps):
        """When PowerShell is not installed, create_powershell_tools returns None."""
        from hooty.tools.sub_agent_runner import _create_sub_agent_tools

        mock_create_ps.return_value = None

        agent_def = AgentDef(
            name="writer",
            description="Writer agent",
            instructions="Write things",
            disallowed_tools=[],
            source="user",
        )
        config = _make_config()
        tools = _create_sub_agent_tools(agent_def, config)
        mock_create_ps.assert_called_once()
        assert None not in tools


class TestOnEventRef:
    def test_default_is_none(self):
        assert _on_event[0] is None

    def test_can_set_callback(self):
        original = _on_event[0]
        try:
            def handler(et, an, d):
                pass
            _on_event[0] = handler
            assert _on_event[0] is handler
        finally:
            _on_event[0] = original


class TestSessionStatsRef:
    def test_default_is_none(self):
        assert _session_stats_ref[0] is None

    def test_can_set_session_stats(self):
        from hooty.session_stats import SessionStats
        original = _session_stats_ref[0]
        try:
            ss = SessionStats()
            _session_stats_ref[0] = ss
            assert _session_stats_ref[0] is ss
        finally:
            _session_stats_ref[0] = original

    def test_sub_agent_run_recorded_via_ref(self):
        from hooty.session_stats import SessionStats, SubAgentRunStats
        original = _session_stats_ref[0]
        try:
            ss = SessionStats()
            _session_stats_ref[0] = ss
            # Simulate what sub_agent_runner does
            ref = _session_stats_ref[0]
            ref.add_sub_agent_run(SubAgentRunStats(
                agent_name="explore",
                elapsed=3.5,
                tool_calls=7,
                input_tokens=2000,
                output_tokens=500,
            ))
            assert ss.total_sub_agent_runs == 1
            assert ss.sub_agent_runs[0].agent_name == "explore"
        finally:
            _session_stats_ref[0] = original
