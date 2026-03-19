"""Tests for hooty.tools.sub_agent_tools module."""

from __future__ import annotations

from unittest.mock import patch

from hooty.agent_store import AgentDef
from hooty.config import AppConfig
from hooty.tools.sub_agent_tools import SubAgentTools


def _make_config(**kwargs) -> AppConfig:
    config = AppConfig()
    for k, v in kwargs.items():
        setattr(config, k, v)
    return config


def _make_agent_def(name: str = "test-agent", requires_config: list[str] | None = None, **kwargs) -> AgentDef:
    return AgentDef(
        name=name,
        description=kwargs.get("description", "Test agent"),
        instructions=kwargs.get("instructions", "Do test things"),
        disallowed_tools=kwargs.get("disallowed_tools", []),
        requires_config=requires_config or [],
    )


# ---------------------------------------------------------------------------
# requires_config: satisfied (no dialog)
# ---------------------------------------------------------------------------


class TestRequiresConfigSatisfied:
    def test_no_requires_config(self):
        """Agent without requires_config should not trigger any dialog."""
        config = _make_config(web_search=False)
        agent_def = _make_agent_def()
        tools = SubAgentTools({"test-agent": agent_def}, config)
        result = tools._ensure_required_config(agent_def)
        assert result is None

    def test_web_search_already_enabled(self):
        """Agent with requires_config=['web_search'] should pass when web_search is True."""
        config = _make_config(web_search=True)
        agent_def = _make_agent_def(requires_config=["web_search"])
        tools = SubAgentTools({"test-agent": agent_def}, config)
        result = tools._ensure_required_config(agent_def)
        assert result is None


# ---------------------------------------------------------------------------
# requires_config: not satisfied + user approves
# ---------------------------------------------------------------------------


class TestRequiresConfigApproved:
    @patch.object(SubAgentTools, "_prompt_enable_web_search", return_value=True)
    def test_user_approves_enables_config(self, mock_prompt):
        """User selecting Y should enable web_search on config."""
        config = _make_config(web_search=False)
        agent_def = _make_agent_def(requires_config=["web_search"])
        tools = SubAgentTools({"test-agent": agent_def}, config)

        result = tools._ensure_required_config(agent_def)

        assert result is None
        assert config.web_search is True
        mock_prompt.assert_called_once_with("test-agent")


# ---------------------------------------------------------------------------
# requires_config: not satisfied + user cancels
# ---------------------------------------------------------------------------


class TestRequiresConfigCancelled:
    @patch.object(SubAgentTools, "_prompt_enable_web_search", return_value=False)
    def test_user_cancels_returns_message(self, mock_prompt):
        """User selecting N should return a cancel message."""
        config = _make_config(web_search=False)
        agent_def = _make_agent_def(requires_config=["web_search"])
        tools = SubAgentTools({"test-agent": agent_def}, config)

        result = tools._ensure_required_config(agent_def)

        assert result is not None
        assert "Cancelled" in result
        assert config.web_search is False
        mock_prompt.assert_called_once_with("test-agent")


# ---------------------------------------------------------------------------
# run_agent integration with requires_config
# ---------------------------------------------------------------------------


class TestRunAgentRequiresConfig:
    @patch.object(SubAgentTools, "_prompt_enable_web_search", return_value=False)
    def test_run_agent_cancelled_by_config(self, mock_prompt):
        """run_agent should return cancel message when user denies config requirement."""
        config = _make_config(web_search=False)
        agent_def = _make_agent_def(name="web-researcher", requires_config=["web_search"])
        tools = SubAgentTools({"web-researcher": agent_def}, config)

        result = tools.run_agent("web-researcher", "research something")

        assert "Cancelled" in result

    @patch("hooty.tools.sub_agent_tools.SubAgentTools._ensure_required_config", return_value=None)
    @patch("hooty.tools.sub_agent_runner.run_sub_agent", return_value="Research results")
    def test_run_agent_proceeds_when_config_satisfied(self, mock_runner, mock_ensure):
        """run_agent should proceed normally when config requirements are met."""
        config = _make_config(web_search=True)
        agent_def = _make_agent_def(name="web-researcher", requires_config=["web_search"])
        tools = SubAgentTools({"web-researcher": agent_def}, config)

        result = tools.run_agent("web-researcher", "research something")

        assert result == "Research results"


# ---------------------------------------------------------------------------
# Instructions contain web-researcher
# ---------------------------------------------------------------------------


class TestInstructions:
    def test_instructions_mention_web_researcher(self):
        """Instructions should include web-researcher in agent selection guide."""
        config = _make_config()
        agent_def = _make_agent_def(name="web-researcher", description="Web research agent")
        tools = SubAgentTools({"web-researcher": agent_def}, config)
        assert "web-researcher" in tools.instructions
