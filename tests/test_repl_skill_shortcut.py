"""Tests for skill top-level slash command shortcuts."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from hooty.config import AppConfig, SkillsConfig
from hooty.skill_store import SkillInfo


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_config(tmp_path: Path, *, enabled: bool = True) -> AppConfig:
    """Create a minimal AppConfig pointing at tmp_path."""
    config_dir = tmp_path / ".hooty"
    config_dir.mkdir(parents=True, exist_ok=True)
    project_dir = config_dir / "projects" / "test-abc12345"
    project_dir.mkdir(parents=True, exist_ok=True)

    class _TestConfig(AppConfig):
        @property
        def config_dir(self) -> Path:
            return config_dir

        @property
        def project_dir(self) -> Path:
            return project_dir

        @property
        def skills_state_path(self) -> Path:
            return project_dir / ".skills.json"

        @property
        def global_skills_state_path(self) -> Path:
            return config_dir / ".skills.json"

    return _TestConfig(
        working_directory=str(tmp_path / "project"),
        skills=SkillsConfig(enabled=enabled),
    )


def _create_skill(
    base_dir: Path,
    name: str,
    description: str = "A test skill",
    instructions: str = "Do the thing.",
    *,
    disable_model_invocation: bool = False,
    user_invocable: bool = True,
) -> Path:
    """Create a minimal skill directory with SKILL.md."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    fm_lines = ["---"]
    fm_lines.append(f"name: {name}")
    fm_lines.append(f"description: {description}")
    if disable_model_invocation:
        fm_lines.append("disable-model-invocation: true")
    if not user_invocable:
        fm_lines.append("user-invocable: false")
    fm_lines.append("---")
    fm_lines.append("")
    fm_lines.append(instructions)

    (skill_dir / "SKILL.md").write_text("\n".join(fm_lines), encoding="utf-8")
    return skill_dir


def _make_skill_info(
    name: str,
    *,
    enabled: bool = True,
    user_invocable: bool = True,
    description: str = "test",
) -> SkillInfo:
    return SkillInfo(
        name=name,
        description=description,
        source="project (.hooty)",
        source_path=f"/tmp/{name}",
        enabled=enabled,
        disable_model_invocation=False,
        user_invocable=user_invocable,
        instructions="Do the thing.",
    )


# ---------------------------------------------------------------------------
# _try_skill_shortcut tests
# ---------------------------------------------------------------------------

class TestTrySkillShortcut:
    """Test _try_skill_shortcut dispatching."""

    def _make_repl_stub(self, config: AppConfig):
        """Create a minimal object that has the methods under test."""
        from hooty.repl import REPL

        repl = object.__new__(REPL)
        repl.config = config
        repl.console = MagicMock()
        repl._pending_skill_message = None
        return repl

    def test_match_success(self, tmp_path):
        """Matching a user-invocable skill sets _pending_skill_message."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(skills_dir, "explain-code", instructions="Explain $ARGUMENTS")
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        result = repl._try_skill_shortcut("/explain-code", ["main.py"])

        assert result is True
        assert repl._pending_skill_message is not None
        assert "Explain" in repl._pending_skill_message

    def test_no_match(self, tmp_path):
        """Non-existent skill returns False."""
        config = _make_config(tmp_path)
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        result = repl._try_skill_shortcut("/nonexistent", [])

        assert result is False
        assert repl._pending_skill_message is None

    def test_user_invocable_false(self, tmp_path):
        """Skill with user_invocable=False is not matched."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(skills_dir, "auto-only", user_invocable=False)
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        result = repl._try_skill_shortcut("/auto-only", [])

        assert result is False

    def test_skills_disabled(self, tmp_path):
        """When skills.enabled=False, always returns False."""
        config = _make_config(tmp_path, enabled=False)

        repl = self._make_repl_stub(config)
        result = repl._try_skill_shortcut("/anything", [])

        assert result is False

    def test_disabled_skill_not_matched(self, tmp_path):
        """A skill that exists but is disabled is not matched."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(skills_dir, "disabled-skill")
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        # Persist disabled state
        from hooty.skill_store import save_disabled_skills
        save_disabled_skills(config, {"disabled-skill"})

        repl = self._make_repl_stub(config)
        result = repl._try_skill_shortcut("/disabled-skill", [])

        assert result is False


# ---------------------------------------------------------------------------
# _refresh_skill_commands tests
# ---------------------------------------------------------------------------

class TestRefreshSkillCommands:
    """Test _refresh_skill_commands cache building."""

    def _make_repl_stub(self, config: AppConfig):
        from hooty.repl import REPL

        repl = object.__new__(REPL)
        repl.config = config
        repl._skill_command_cache = []
        return repl

    def test_builds_cache(self, tmp_path):
        """Cache contains user-invocable enabled skills."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(skills_dir, "my-skill", description="My cool skill")
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        repl._refresh_skill_commands()

        assert ("/my-skill", "My cool skill") in repl._skill_command_cache

    def test_excludes_existing_commands(self, tmp_path):
        """Skills whose names collide with built-in commands are excluded."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        # /help is a built-in command
        _create_skill(skills_dir, "help", description="Shadow help")
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        repl._refresh_skill_commands()

        names = [cmd for cmd, _ in repl._skill_command_cache]
        assert "/help" not in names

    def test_empty_when_skills_disabled(self, tmp_path):
        """Cache is empty when skills are disabled."""
        config = _make_config(tmp_path, enabled=False)

        repl = self._make_repl_stub(config)
        repl._refresh_skill_commands()

        assert repl._skill_command_cache == []

    def test_excludes_non_user_invocable(self, tmp_path):
        """Skills with user_invocable=False are excluded from cache."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(skills_dir, "auto-skill", user_invocable=False)
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        repl._refresh_skill_commands()

        names = [cmd for cmd, _ in repl._skill_command_cache]
        assert "/auto-skill" not in names

    def test_includes_manual_only_skills(self, tmp_path):
        """Skills with disable_model_invocation=True are included."""
        config = _make_config(tmp_path)
        skills_dir = tmp_path / "project" / ".hooty" / "skills"
        _create_skill(
            skills_dir, "manual-skill",
            description="Manual only",
            disable_model_invocation=True,
        )
        (tmp_path / "project").mkdir(parents=True, exist_ok=True)

        repl = self._make_repl_stub(config)
        repl._refresh_skill_commands()

        assert ("/manual-skill", "Manual only") in repl._skill_command_cache


# ---------------------------------------------------------------------------
# Completer integration
# ---------------------------------------------------------------------------

class TestCompleterIncludesSkills:
    """Verify that the slash command completer yields skill entries."""

    def test_skill_in_completions(self, tmp_path):
        """Skill commands appear in tab completions."""
        from hooty.repl import SLASH_COMMANDS

        # Build a mock repl_ref with a skill cache
        repl_ref = MagicMock()
        repl_ref._skill_command_cache = [("/my-skill", "My cool skill")]

        # Simulate the completer logic
        text = "/my-"
        completions = []
        for cmd, desc in list(SLASH_COMMANDS) + repl_ref._skill_command_cache:
            if cmd.startswith(text) and cmd != text:
                completions.append((cmd, desc))

        assert any(cmd == "/my-skill" for cmd, _ in completions)
