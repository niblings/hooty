"""Tests for hooty.prompt_store module."""

from __future__ import annotations

from hooty.prompt_store import (
    PromptsConfig,
    _eval_when,
    load_prompts,
    resolve_instructions,
)


# ---------------------------------------------------------------------------
# load_prompts
# ---------------------------------------------------------------------------


class TestLoadPrompts:
    def test_returns_prompts_config(self):
        cfg = load_prompts()
        assert isinstance(cfg, PromptsConfig)

    def test_has_memory_policy(self):
        cfg = load_prompts()
        assert "Memory policy" in cfg.memory_policy
        assert "update_user_memory" in cfg.memory_policy

    def test_has_planning_mode(self):
        cfg = load_prompts()
        assert "planning" in cfg.modes
        mp = cfg.modes["planning"]
        assert "architect" in mp.role.lower()
        assert len(mp.instructions) > 0

    def test_has_coding_mode(self):
        cfg = load_prompts()
        assert "coding" in cfg.modes
        mp = cfg.modes["coding"]
        assert "engineer" in mp.role.lower()
        assert len(mp.instructions) > 0

    def test_memory_policy_includes_preferences(self):
        cfg = load_prompts()
        assert "preferences" in cfg.memory_policy.lower()


# ---------------------------------------------------------------------------
# _eval_when
# ---------------------------------------------------------------------------


class TestEvalWhen:
    def test_positive_flag_true(self):
        assert _eval_when("reasoning_active", {"reasoning_active": True}) is True

    def test_positive_flag_false(self):
        assert _eval_when("reasoning_active", {"reasoning_active": False}) is False

    def test_positive_flag_missing(self):
        assert _eval_when("reasoning_active", {}) is False

    def test_negated_flag_true(self):
        assert _eval_when("not reasoning_active", {"reasoning_active": True}) is False

    def test_negated_flag_false(self):
        assert _eval_when("not reasoning_active", {"reasoning_active": False}) is True

    def test_negated_flag_missing(self):
        assert _eval_when("not reasoning_active", {}) is True

    def test_whitespace_handling(self):
        assert _eval_when("  not reasoning_active  ", {"reasoning_active": False}) is True


# ---------------------------------------------------------------------------
# resolve_instructions
# ---------------------------------------------------------------------------


class TestResolveInstructions:
    def test_plain_strings_pass_through(self):
        raw = ["Hello", "World"]
        result = resolve_instructions(raw, {}, {})
        assert result == ["Hello", "World"]

    def test_template_variable_substitution(self):
        raw = ["Step: {reasoning_step}done."]
        result = resolve_instructions(
            raw, {}, {"reasoning_step": "think deeply, "},
        )
        assert result == ["Step: think deeply, done."]

    def test_missing_template_variable_becomes_empty(self):
        raw = ["Before {missing}after"]
        result = resolve_instructions(raw, {}, {})
        assert result == ["Before after"]

    def test_when_condition_included(self):
        raw = [{"when": "not reasoning_active", "value": "Use think()."}]
        result = resolve_instructions(raw, {"reasoning_active": False}, {})
        assert result == ["Use think()."]

    def test_when_condition_excluded(self):
        raw = [{"when": "not reasoning_active", "value": "Use think()."}]
        result = resolve_instructions(raw, {"reasoning_active": True}, {})
        assert result == []

    def test_when_item_with_template_vars(self):
        raw = [{"when": "not reasoning_active", "value": "Do {action}."}]
        result = resolve_instructions(
            raw, {"reasoning_active": False}, {"action": "analyze"},
        )
        assert result == ["Do analyze."]

    def test_mixed_items(self):
        raw = [
            "Always included.",
            {"when": "feature_x", "value": "Feature X enabled."},
            "Also included.",
        ]
        result = resolve_instructions(raw, {"feature_x": True}, {})
        assert result == [
            "Always included.",
            "Feature X enabled.",
            "Also included.",
        ]


# ---------------------------------------------------------------------------
# Regression: resolved instructions match original hardcoded content
# ---------------------------------------------------------------------------


class TestRegressionPlanning:
    """Planning mode instructions should contain key phrases from the original."""

    def setup_method(self):
        cfg = load_prompts()
        self.instructions = resolve_instructions(
            cfg.modes["planning"].instructions,
            flags={},
            template_vars={},
        )
        self.joined = "\n".join(self.instructions)

    def test_mode_label(self):
        assert "PLANNING mode" in self.joined

    def test_primary_output(self):
        assert "MARKDOWN DOCUMENT" in self.joined

    def test_no_code(self):
        assert "NEVER produce implementation code" in self.joined

    def test_workflow_extended_thinking(self):
        assert "use extended thinking for deep reasoning" in self.joined

    def test_no_think_analyze_references(self):
        assert "think()" not in self.joined
        assert "analyze()" not in self.joined

    def test_exit_plan_mode(self):
        assert "exit_plan_mode()" in self.joined

    def test_ask_user(self):
        assert "ask_user()" in self.joined


class TestRegressionCoding:
    """Coding mode instructions should contain key phrases from the original."""

    def setup_method(self):
        cfg = load_prompts()
        self.instructions = resolve_instructions(
            cfg.modes["coding"].instructions,
            flags={"reasoning_active": False},
            template_vars={},
        )
        self.joined = "\n".join(self.instructions)

    def test_mode_label(self):
        assert "CODING mode" in self.joined

    def test_step_by_step(self):
        assert "step by step" in self.joined

    def test_edit_preference(self):
        assert "edit_file" in self.joined

    def test_enter_plan_mode(self):
        assert "enter_plan_mode()" in self.joined

    def test_ask_user(self):
        assert "ask_user()" in self.joined

    def test_assistant_delegation(self):
        assert "assistant" in self.joined

    def test_task_decomposition(self):
        assert "Task decomposition" in self.joined
