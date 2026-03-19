"""Tests for hooty.hooks module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from hooty.hooks import (
    HookEntry,
    HookEvent,
    HookResult,
    _execute_command_hook,
    _matches,
    apply_disabled_state,
    emit_hook,
    emit_hook_sync,
    get_additional_context,
    get_block_reason,
    has_allow_decision,
    has_blocking,
    load_disabled_hooks,
    load_hooks_config,
    save_disabled_hooks,
)


def _run(coro):
    """Helper to run async tests."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# HookEntry
# ---------------------------------------------------------------------------


class TestHookEntry:
    def test_defaults(self):
        e = HookEntry(command="echo hello")
        assert e.command == "echo hello"
        assert e.matcher == ""
        assert e.blocking is False
        assert e.async_exec is False
        assert e.timeout == 5
        assert e.enabled is True

    def test_key(self):
        e = HookEntry(command="~/scripts/test.sh")
        assert e.key == "~/scripts/test.sh"


class TestHookEventSubagent:
    """Test SubagentStart/SubagentEnd event values."""

    def test_subagent_start_exists(self):
        assert HookEvent.SUBAGENT_START.value == "SubagentStart"

    def test_subagent_end_exists(self):
        assert HookEvent.SUBAGENT_END.value == "SubagentEnd"

    def test_subagent_start_valid_event(self):
        assert HookEvent("SubagentStart") == HookEvent.SUBAGENT_START

    def test_subagent_end_valid_event(self):
        assert HookEvent("SubagentEnd") == HookEvent.SUBAGENT_END

    def test_matcher_field_agent_name(self):
        from hooty.hooks import _MATCHER_FIELD
        assert _MATCHER_FIELD["SubagentStart"] == "agent_name"
        assert _MATCHER_FIELD["SubagentEnd"] == "agent_name"

    def test_matches_subagent_start(self):
        entry = HookEntry(command="echo test", matcher="explore")
        data = {"agent_name": "explore", "task": "find something"}
        assert _matches(entry, "SubagentStart", data)

    def test_no_match_subagent_start(self):
        entry = HookEntry(command="echo test", matcher="summarize")
        data = {"agent_name": "explore", "task": "find something"}
        assert not _matches(entry, "SubagentStart", data)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config(tmp_path):
    """Create a mock AppConfig with temp directories."""
    config = MagicMock()
    config.config_dir = tmp_path / "global"
    config.config_dir.mkdir()
    config.working_directory = str(tmp_path / "project")
    (tmp_path / "project" / ".hooty").mkdir(parents=True)
    config.project_dir = tmp_path / "project_dir"
    config.project_dir.mkdir()
    # Patch isinstance check
    config.__class__ = _get_app_config_class()
    return config


def _get_app_config_class():
    from hooty.config import AppConfig
    return AppConfig


class TestLoadHooksConfig:
    def test_empty_no_files(self, mock_config):
        result = load_hooks_config(mock_config)
        assert result == {}

    def test_global_hooks(self, mock_config):
        hooks_yaml = {
            "hooks": {
                "SessionStart": [
                    {"command": "echo start", "timeout": 3},
                ],
            }
        }
        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(hooks_yaml), encoding="utf-8",
        )
        result = load_hooks_config(mock_config)
        assert "SessionStart" in result
        assert len(result["SessionStart"]) == 1
        assert result["SessionStart"][0].command == "echo start"
        assert result["SessionStart"][0].timeout == 3

    def test_subagent_hooks(self, mock_config):
        hooks_yaml = {
            "hooks": {
                "SubagentStart": [
                    {"command": "echo sub-start", "matcher": "explore"},
                ],
                "SubagentEnd": [
                    {"command": "echo sub-end"},
                ],
            }
        }
        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(hooks_yaml), encoding="utf-8",
        )
        result = load_hooks_config(mock_config)
        assert "SubagentStart" in result
        assert result["SubagentStart"][0].matcher == "explore"
        assert "SubagentEnd" in result
        assert result["SubagentEnd"][0].command == "echo sub-end"

    def test_project_hooks(self, mock_config):
        hooks_yaml = {
            "hooks": {
                "PreToolUse": [
                    {"command": "echo lint", "matcher": "write_file", "blocking": True},
                ],
            }
        }
        project_hooks = Path(mock_config.working_directory) / ".hooty" / "hooks.yaml"
        project_hooks.write_text(yaml.dump(hooks_yaml), encoding="utf-8")

        result = load_hooks_config(mock_config)
        assert "PreToolUse" in result
        entry = result["PreToolUse"][0]
        assert entry.command == "echo lint"
        assert entry.matcher == "write_file"
        assert entry.blocking is True

    def test_merge_global_and_project(self, mock_config):
        global_yaml = {"hooks": {"SessionStart": [{"command": "echo global"}]}}
        project_yaml = {"hooks": {"SessionStart": [{"command": "echo project"}]}}

        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(global_yaml), encoding="utf-8",
        )
        project_hooks = Path(mock_config.working_directory) / ".hooty" / "hooks.yaml"
        project_hooks.write_text(yaml.dump(project_yaml), encoding="utf-8")

        result = load_hooks_config(mock_config)
        assert len(result["SessionStart"]) == 2
        assert result["SessionStart"][0].command == "echo global"
        assert result["SessionStart"][1].command == "echo project"

    def test_invalid_event_name_skipped(self, mock_config):
        hooks_yaml = {"hooks": {"InvalidEvent": [{"command": "echo bad"}]}}
        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(hooks_yaml), encoding="utf-8",
        )
        result = load_hooks_config(mock_config)
        assert "InvalidEvent" not in result

    def test_missing_command_skipped(self, mock_config):
        hooks_yaml = {"hooks": {"SessionStart": [{"matcher": "test"}]}}
        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(hooks_yaml), encoding="utf-8",
        )
        result = load_hooks_config(mock_config)
        assert result.get("SessionStart", []) == []

    def test_async_field(self, mock_config):
        hooks_yaml = {"hooks": {"Stop": [{"command": "echo bg", "async": True}]}}
        (mock_config.config_dir / "hooks.yaml").write_text(
            yaml.dump(hooks_yaml), encoding="utf-8",
        )
        result = load_hooks_config(mock_config)
        assert result["Stop"][0].async_exec is True


# ---------------------------------------------------------------------------
# State management
# ---------------------------------------------------------------------------


class TestStateManagement:
    def test_load_save_disabled(self, mock_config):
        assert load_disabled_hooks(mock_config) == set()

        save_disabled_hooks(mock_config, {"SessionStart:echo start"})
        assert load_disabled_hooks(mock_config) == {"SessionStart:echo start"}

        save_disabled_hooks(mock_config, set())
        assert load_disabled_hooks(mock_config) == set()

    def test_apply_disabled_state(self, mock_config):
        hooks_config = {
            "SessionStart": [HookEntry(command="echo start")],
            "PreToolUse": [HookEntry(command="echo lint")],
        }
        save_disabled_hooks(mock_config, {"SessionStart:echo start"})
        apply_disabled_state(hooks_config, mock_config)

        assert hooks_config["SessionStart"][0].enabled is False
        assert hooks_config["PreToolUse"][0].enabled is True


# ---------------------------------------------------------------------------
# Matcher
# ---------------------------------------------------------------------------


class TestMatcher:
    def test_no_matcher_always_matches(self):
        entry = HookEntry(command="echo", matcher="")
        assert _matches(entry, "PreToolUse", {"tool_name": "write_file"})

    def test_matcher_on_tool_name(self):
        entry = HookEntry(command="echo", matcher="write_file|create_file")
        assert _matches(entry, "PreToolUse", {"tool_name": "write_file"})
        assert _matches(entry, "PreToolUse", {"tool_name": "create_file"})
        assert not _matches(entry, "PreToolUse", {"tool_name": "read_file"})

    def test_matcher_on_message(self):
        entry = HookEntry(command="echo", matcher="password")
        assert _matches(entry, "UserPromptSubmit", {"message": "reset my password"})
        assert not _matches(entry, "UserPromptSubmit", {"message": "hello"})

    def test_matcher_ignored_for_non_matchable_event(self):
        entry = HookEntry(command="echo", matcher="anything")
        assert _matches(entry, "SessionStart", {})

    def test_invalid_regex_returns_false(self):
        entry = HookEntry(command="echo", matcher="[invalid")
        assert not _matches(entry, "PreToolUse", {"tool_name": "write_file"})


# ---------------------------------------------------------------------------
# Command execution
# ---------------------------------------------------------------------------


class TestExecuteCommandHook:
    def test_success_plain_text(self):
        entry = HookEntry(command="echo 'hello world'", timeout=5)
        result = _run(_execute_command_hook(entry, {"hook_event": "test"}))
        assert result.success is True
        assert result.exit_code == 0
        assert result.additional_context == "hello world"

    def test_success_json_output(self):
        cmd = """echo '{"decision": "allow", "reason": "ok", "additionalContext": "ctx"}'"""
        entry = HookEntry(command=cmd, timeout=5)
        result = _run(_execute_command_hook(entry, {"hook_event": "test"}))
        assert result.success is True
        assert result.decision == "allow"
        assert result.reason == "ok"
        assert result.additional_context == "ctx"

    def test_exit_code_2_block(self):
        entry = HookEntry(command="echo 'blocked' >&2; exit 2", timeout=5)
        result = _run(_execute_command_hook(entry, {"hook_event": "test"}))
        assert result.success is True
        assert result.exit_code == 2
        assert result.decision == "block"
        assert result.reason == "blocked"

    def test_nonzero_exit(self):
        entry = HookEntry(command="exit 1", timeout=5)
        result = _run(_execute_command_hook(entry, {"hook_event": "test"}))
        assert result.success is False
        assert result.exit_code == 1

    def test_timeout(self):
        entry = HookEntry(command="sleep 10", timeout=1)
        result = _run(_execute_command_hook(entry, {"hook_event": "test"}))
        assert result.success is False
        assert "timed out" in result.error

    def test_stdin_data_received(self):
        cmd = "python3 -c \"import sys,json; d=json.load(sys.stdin); print(d['hook_event'])\""
        entry = HookEntry(command=cmd, timeout=5)
        result = _run(_execute_command_hook(
            entry, {"hook_event": "SessionStart", "session_id": "test"},
        ))
        assert result.success is True
        assert result.additional_context == "SessionStart"


# ---------------------------------------------------------------------------
# emit_hook
# ---------------------------------------------------------------------------


class TestEmitHook:
    def test_no_hooks_returns_empty(self):
        results = _run(emit_hook(
            HookEvent.SESSION_START, {}, "sid", "/tmp",
        ))
        assert results == []

    def test_fires_matching_hooks(self):
        config = {
            "SessionStart": [HookEntry(command="echo fired")],
        }
        results = _run(emit_hook(
            HookEvent.SESSION_START, config, "sid", "/tmp",
        ))
        assert len(results) == 1
        assert results[0].success is True
        assert results[0].additional_context == "fired"

    def test_skips_disabled_hooks(self):
        entry = HookEntry(command="echo fired", enabled=False)
        config = {"SessionStart": [entry]}
        results = _run(emit_hook(
            HookEvent.SESSION_START, config, "sid", "/tmp",
        ))
        assert results == []

    def test_matcher_filters(self):
        config = {
            "PreToolUse": [
                HookEntry(command="echo matched", matcher="write_file"),
            ],
        }
        results = _run(emit_hook(
            HookEvent.PRE_TOOL_USE, config, "sid", "/tmp",
            tool_name="read_file",
        ))
        assert results == []

        results = _run(emit_hook(
            HookEvent.PRE_TOOL_USE, config, "sid", "/tmp",
            tool_name="write_file",
        ))
        assert len(results) == 1


# ---------------------------------------------------------------------------
# emit_hook_sync
# ---------------------------------------------------------------------------


class TestEmitHookSync:
    def test_sync_wrapper(self):
        config = {
            "SessionStart": [HookEntry(command="echo sync_test")],
        }
        results = emit_hook_sync(
            HookEvent.SESSION_START, config, "sid", "/tmp",
        )
        assert len(results) == 1
        assert results[0].additional_context == "sync_test"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_has_blocking(self):
        results = [
            HookResult(success=True, exit_code=0),
            HookResult(success=True, exit_code=2, decision="block", reason="no"),
        ]
        assert has_blocking(results) is True
        assert has_blocking([results[0]]) is False

    def test_get_block_reason(self):
        results = [
            HookResult(success=True, exit_code=2, reason="forbidden"),
        ]
        assert get_block_reason(results) == "forbidden"
        assert get_block_reason([]) == "Blocked by hook"

    def test_get_additional_context(self):
        results = [
            HookResult(success=True, additional_context="ctx1"),
            HookResult(success=True, additional_context=""),
            HookResult(success=True, additional_context="ctx2"),
        ]
        assert get_additional_context(results) == "ctx1\nctx2"

    def test_has_allow_decision(self):
        results = [HookResult(success=True, decision="allow")]
        assert has_allow_decision(results) is True
        results = [HookResult(success=True, decision="")]
        assert has_allow_decision(results) is False
