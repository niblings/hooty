"""Tests for hooty.agent_store module."""

from __future__ import annotations

import yaml

from hooty.agent_store import (
    NEVER_INHERIT,
    AgentDef,
    AgentModelConfig,
    _builtin_yaml_path,
    _load_yaml,
    _parse_agent_def,
    load_agents_config,
)


# ---------------------------------------------------------------------------
# AgentDef dataclass
# ---------------------------------------------------------------------------


class TestAgentDef:
    def test_defaults(self):
        d = AgentDef(name="test", description="desc", instructions="inst")
        assert d.name == "test"
        assert d.description == "desc"
        assert d.instructions == "inst"
        assert d.disallowed_tools == []
        assert d.model is None
        assert d.max_turns == 25
        assert d.max_output_tokens == 4000
        assert d.source == ""

    def test_requires_config_default(self):
        d = AgentDef(name="test", description="desc", instructions="inst")
        assert d.requires_config == []

    def test_requires_config_set(self):
        d = AgentDef(
            name="test", description="desc", instructions="inst",
            requires_config=["web_search"],
        )
        assert d.requires_config == ["web_search"]

    def test_with_model(self):
        model = AgentModelConfig(provider="bedrock", model_id="claude-haiku")
        d = AgentDef(
            name="test", description="desc", instructions="inst",
            model=model, max_turns=10, max_output_tokens=2000,
        )
        assert d.model.provider == "bedrock"
        assert d.model.model_id == "claude-haiku"
        assert d.max_turns == 10
        assert d.max_output_tokens == 2000


class TestAgentModelConfig:
    def test_defaults(self):
        m = AgentModelConfig()
        assert m.provider == ""
        assert m.model_id == ""


# ---------------------------------------------------------------------------
# NEVER_INHERIT constant
# ---------------------------------------------------------------------------


class TestNeverInherit:
    def test_contains_expected(self):
        assert "run_agent" in NEVER_INHERIT
        assert "ask_user" in NEVER_INHERIT
        assert "exit_plan_mode" in NEVER_INHERIT
        assert "enter_plan_mode" in NEVER_INHERIT
        assert "think" in NEVER_INHERIT
        assert "analyze" in NEVER_INHERIT

    def test_does_not_contain_coding_tools(self):
        assert "read_file" not in NEVER_INHERIT
        assert "write_file" not in NEVER_INHERIT
        assert "grep" not in NEVER_INHERIT


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


class TestLoadYaml:
    def test_valid_yaml(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({
            "agents": {
                "explore": {
                    "description": "Explorer",
                    "instructions": "Explore things",
                }
            }
        }))
        result = _load_yaml(p)
        assert "explore" in result
        assert result["explore"]["description"] == "Explorer"

    def test_missing_file(self, tmp_path):
        p = tmp_path / "nonexistent.yaml"
        assert _load_yaml(p) == {}

    def test_no_agents_section(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text(yaml.dump({"other": "stuff"}))
        assert _load_yaml(p) == {}

    def test_invalid_yaml(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text("{{invalid yaml:")
        assert _load_yaml(p) == {}

    def test_non_dict_content(self, tmp_path):
        p = tmp_path / "agents.yaml"
        p.write_text("just a string")
        assert _load_yaml(p) == {}


class TestParseAgentDef:
    def test_valid_minimal(self):
        raw = {"description": "A tool", "instructions": "Do things"}
        result = _parse_agent_def("test", raw, "builtin")
        assert result is not None
        assert result.name == "test"
        assert result.description == "A tool"
        assert result.instructions == "Do things"
        assert result.source == "builtin"

    def test_missing_description(self):
        raw = {"instructions": "Do things"}
        assert _parse_agent_def("test", raw, "builtin") is None

    def test_missing_instructions(self):
        raw = {"description": "A tool"}
        assert _parse_agent_def("test", raw, "builtin") is None

    def test_with_all_fields(self):
        raw = {
            "description": "desc",
            "instructions": "inst",
            "disallowed_tools": ["write_file", "edit_file"],
            "model": {"provider": "bedrock", "model_id": "claude-haiku"},
            "max_turns": 10,
            "max_output_tokens": 2000,
        }
        result = _parse_agent_def("full", raw, "project")
        assert result is not None
        assert result.disallowed_tools == ["write_file", "edit_file"]
        assert result.model is not None
        assert result.model.provider == "bedrock"
        assert result.max_turns == 10
        assert result.max_output_tokens == 2000

    def test_invalid_disallowed_tools(self):
        raw = {
            "description": "desc",
            "instructions": "inst",
            "disallowed_tools": "not a list",
        }
        result = _parse_agent_def("test", raw, "builtin")
        assert result is not None
        assert result.disallowed_tools == []

    def test_requires_config_parsed(self):
        raw = {
            "description": "desc",
            "instructions": "inst",
            "requires_config": ["web_search"],
        }
        result = _parse_agent_def("test", raw, "builtin")
        assert result is not None
        assert result.requires_config == ["web_search"]

    def test_requires_config_invalid_type_fallback(self):
        raw = {
            "description": "desc",
            "instructions": "inst",
            "requires_config": "not a list",
        }
        result = _parse_agent_def("test", raw, "builtin")
        assert result is not None
        assert result.requires_config == []

    def test_model_without_required_fields(self):
        raw = {
            "description": "desc",
            "instructions": "inst",
            "model": {"provider": "bedrock"},  # missing model_id
        }
        result = _parse_agent_def("test", raw, "builtin")
        assert result is not None
        assert result.model is None


# ---------------------------------------------------------------------------
# Builtin YAML
# ---------------------------------------------------------------------------


class TestBuiltinYaml:
    def test_builtin_path_exists(self):
        path = _builtin_yaml_path()
        assert path.exists(), f"Built-in agents.yaml not found at {path}"

    def test_builtin_has_explore_and_summarize(self):
        path = _builtin_yaml_path()
        agents = _load_yaml(path)
        assert "explore" in agents
        assert "summarize" in agents

    def test_builtin_has_web_researcher(self):
        path = _builtin_yaml_path()
        agents = _load_yaml(path)
        assert "web-researcher" in agents
        wr = agents["web-researcher"]
        assert "description" in wr
        assert "instructions" in wr
        assert "requires_config" in wr
        assert "web_search" in wr["requires_config"]

    def test_builtin_has_assistant(self):
        path = _builtin_yaml_path()
        agents = _load_yaml(path)
        assert "assistant" in agents
        assistant = agents["assistant"]
        assert "description" in assistant
        assert "instructions" in assistant
        assert assistant.get("disallowed_tools", []) == []

    def test_builtin_explore_has_required_fields(self):
        path = _builtin_yaml_path()
        agents = _load_yaml(path)
        explore = agents["explore"]
        assert "description" in explore
        assert "instructions" in explore
        assert "disallowed_tools" in explore
        assert "write_file" in explore["disallowed_tools"]


# ---------------------------------------------------------------------------
# Merge logic (load_agents_config)
# ---------------------------------------------------------------------------


class TestLoadAgentsConfig:
    def _make_config(self, tmp_path):
        from hooty.config import AppConfig
        config = AppConfig()
        config.working_directory = str(tmp_path)
        return config

    def test_builtin_always_loaded(self, tmp_path):
        config = self._make_config(tmp_path)
        result = load_agents_config(config)
        assert "explore" in result
        assert "summarize" in result
        assert result["explore"].source == "builtin"

    def test_global_override(self, tmp_path):
        config = self._make_config(tmp_path)
        # Create global agents.yaml
        global_dir = config.config_dir
        global_dir.mkdir(parents=True, exist_ok=True)
        global_file = global_dir / "agents.yaml"
        global_file.write_text(yaml.dump({
            "agents": {
                "explore": {
                    "description": "Custom explore",
                    "instructions": "Custom instructions",
                    "disallowed_tools": ["write_file"],
                }
            }
        }))
        try:
            result = load_agents_config(config)
            assert result["explore"].source == "global"
            assert result["explore"].description == "Custom explore"
            # summarize still comes from builtin
            assert result["summarize"].source == "builtin"
        finally:
            global_file.unlink(missing_ok=True)

    def test_project_override(self, tmp_path):
        config = self._make_config(tmp_path)
        # Create project agents.yaml
        project_dir = tmp_path / ".hooty"
        project_dir.mkdir(parents=True, exist_ok=True)
        project_file = project_dir / "agents.yaml"
        project_file.write_text(yaml.dump({
            "agents": {
                "explore": {
                    "description": "Project explore",
                    "instructions": "Project instructions",
                }
            }
        }))
        result = load_agents_config(config)
        assert result["explore"].source == "project"
        assert result["explore"].description == "Project explore"

    def test_user_defined_agent(self, tmp_path):
        config = self._make_config(tmp_path)
        project_dir = tmp_path / ".hooty"
        project_dir.mkdir(parents=True, exist_ok=True)
        project_file = project_dir / "agents.yaml"
        project_file.write_text(yaml.dump({
            "agents": {
                "reviewer": {
                    "description": "Code reviewer",
                    "instructions": "Review code for bugs",
                    "disallowed_tools": ["write_file", "edit_file"],
                }
            }
        }))
        result = load_agents_config(config)
        assert "reviewer" in result
        assert result["reviewer"].source == "project"
        # Builtins still present
        assert "explore" in result
        assert "summarize" in result

    def test_invalid_config_returns_empty(self):
        result = load_agents_config("not a config")
        assert result == {}

    def test_merge_order(self, tmp_path):
        """Project overrides global which overrides builtin."""
        config = self._make_config(tmp_path)

        # Global
        global_dir = config.config_dir
        global_dir.mkdir(parents=True, exist_ok=True)
        global_file = global_dir / "agents.yaml"
        global_file.write_text(yaml.dump({
            "agents": {
                "explore": {
                    "description": "Global explore",
                    "instructions": "Global instructions",
                }
            }
        }))

        # Project
        project_dir = tmp_path / ".hooty"
        project_dir.mkdir(parents=True, exist_ok=True)
        project_file = project_dir / "agents.yaml"
        project_file.write_text(yaml.dump({
            "agents": {
                "explore": {
                    "description": "Project explore",
                    "instructions": "Project instructions",
                }
            }
        }))

        try:
            result = load_agents_config(config)
            # Project wins over global
            assert result["explore"].source == "project"
            assert result["explore"].description == "Project explore"
        finally:
            global_file.unlink(missing_ok=True)
