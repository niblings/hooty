"""Tests for Plan → Coding plan file handoff."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from hooty.config import AppConfig
from hooty.tools.coding_tools import HootyCodingTools, _filter_available_commands, clear_command_cache


class TestFilterAvailableCommands:
    """Test _filter_available_commands PATH filtering."""

    def setup_method(self):
        clear_command_cache()

    def test_filters_missing_commands(self):
        """Commands not on PATH should be excluded."""
        with patch("hooty.tools.coding_tools.shutil.which", return_value=None):
            result = _filter_available_commands(["nonexistent1", "nonexistent2"])
        assert result == []

    def test_keeps_existing_commands(self):
        """Commands found on PATH should be kept."""
        def fake_which(cmd, **kwargs):
            return f"/usr/bin/{cmd}" if cmd in ("git", "python3") else None

        with patch("hooty.tools.coding_tools.shutil.which", side_effect=fake_which):
            result = _filter_available_commands(["git", "python3", "missing"])
        assert result == ["git", "python3"]

    def test_project_local_wrapper(self, tmp_path):
        """Commands in base_dir should be found even if not on PATH."""
        # Create a local wrapper script
        wrapper = tmp_path / "mvnw"
        wrapper.write_text("#!/bin/sh\n", encoding="utf-8")
        wrapper.chmod(0o755)

        def fake_which(cmd, **kwargs):
            path = kwargs.get("path")
            if path and cmd == "mvnw":
                return str(tmp_path / "mvnw")
            return None

        with patch("hooty.tools.coding_tools.shutil.which", side_effect=fake_which):
            result = _filter_available_commands(["mvnw", "gradlew"], base_dir=tmp_path)
        assert result == ["mvnw"]

    def test_empty_list(self):
        """Empty input should return empty output."""
        result = _filter_available_commands([])
        assert result == []


class TestSessionPlansDirProperty:
    """Test AppConfig.session_plans_dir property."""

    def test_with_session_id(self):
        config = AppConfig(session_id="abc-123")
        expected = config.config_dir / "sessions" / "abc-123" / "plans"
        assert config.session_plans_dir == expected

    def test_without_session_id(self):
        config = AppConfig()
        assert config.session_plans_dir is None


class TestReadFileSessionDir:
    """Test HootyCodingTools.read_file session directory access."""

    def test_read_plan_file(self, tmp_path):
        """Files inside session directory should be readable."""
        session_dir = tmp_path / "session"
        plans_dir = session_dir / "plans"
        plans_dir.mkdir(parents=True)
        plan_file = plans_dir / "test-plan.md"
        plan_file.write_text("# Plan\n\nStep 1\nStep 2\n", encoding="utf-8")

        base_dir = tmp_path / "project"
        base_dir.mkdir()

        tools = HootyCodingTools(
            base_dir=base_dir,
            all=True,
            restrict_to_base_dir=True,
            session_dir=str(session_dir),
        )
        result = tools.read_file(str(plan_file))
        assert "# Plan" in result
        assert "Step 1" in result
        assert "Step 2" in result

    def test_reject_outside_path(self, tmp_path):
        """Paths outside both base_dir and session directory should be rejected."""
        session_dir = tmp_path / "session"
        session_dir.mkdir()
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")

        tools = HootyCodingTools(
            base_dir=base_dir,
            all=True,
            restrict_to_base_dir=True,
            session_dir=str(session_dir),
        )
        result = tools.read_file(str(outside))
        assert "Error" in result

    def test_fallthrough_to_parent(self, tmp_path):
        """Paths inside base_dir should still work via parent read_file."""
        base_dir = tmp_path / "project"
        base_dir.mkdir()
        src_file = base_dir / "main.py"
        src_file.write_text("print('hello')\n", encoding="utf-8")

        tools = HootyCodingTools(
            base_dir=base_dir,
            all=True,
            restrict_to_base_dir=True,
            session_dir=str(tmp_path / "session"),
        )
        result = tools.read_file(str(src_file))
        assert "print('hello')" in result


class TestReadFileProjectDir:
    """Test HootyCodingTools.read_file project directory access."""

    def test_read_plan_file_from_project_dir(self, tmp_path):
        """Files inside project directory should be readable."""
        project_dir = tmp_path / "projects" / "myproject"
        plans_dir = project_dir / "plans"
        plans_dir.mkdir(parents=True)
        plan_file = plans_dir / "test-plan.md"
        plan_file.write_text("# Project Plan\n\nDetails here\n", encoding="utf-8")

        base_dir = tmp_path / "workspace"
        base_dir.mkdir()

        tools = HootyCodingTools(
            base_dir=base_dir,
            all=True,
            restrict_to_base_dir=True,
            project_dir=str(project_dir),
        )
        result = tools.read_file(str(plan_file))
        assert "# Project Plan" in result
        assert "Details here" in result

    def test_reject_outside_both_dirs(self, tmp_path):
        """Paths outside both base_dir and project directory should be rejected."""
        project_dir = tmp_path / "projects" / "myproject"
        project_dir.mkdir(parents=True)
        base_dir = tmp_path / "workspace"
        base_dir.mkdir()
        outside = tmp_path / "secret.txt"
        outside.write_text("secret", encoding="utf-8")

        tools = HootyCodingTools(
            base_dir=base_dir,
            all=True,
            restrict_to_base_dir=True,
            project_dir=str(project_dir),
        )
        result = tools.read_file(str(outside))
        assert "Error" in result


class TestSavePlanFile:
    """Test REPL._save_plan_file logic (extracted for unit testing)."""

    def _make_repl_stub(self, tmp_path, response_text="", session_id="test-session"):
        """Create a minimal stub with the attributes _save_plan_file needs."""
        config = AppConfig(session_id=session_id)
        # Redirect config_dir so session_plans_dir resolves under tmp_path
        config.__class__ = type(
            "_TestConfig", (AppConfig,),
            {"config_dir": property(lambda self: tmp_path / ".hooty")},
        )

        stub = MagicMock()
        stub._last_response_text = response_text
        stub.config = config
        return stub

    def test_saves_markdown(self, tmp_path):
        """Plan text should be saved to a .md file."""
        from hooty.repl import REPL

        stub = self._make_repl_stub(tmp_path, response_text="# Design\n\nDetails here.")
        result = REPL._save_plan_file(stub)

        assert result is not None
        path = Path(result)
        assert path.exists()
        assert path.suffix == ".md"
        content = path.read_text(encoding="utf-8")
        assert "# Design" in content
        assert "Details here." in content

    def test_returns_none_for_empty(self, tmp_path):
        """Empty response text should return None."""
        from hooty.repl import REPL

        stub = self._make_repl_stub(tmp_path, response_text="")
        assert REPL._save_plan_file(stub) is None

        stub2 = self._make_repl_stub(tmp_path, response_text="   \n  ")
        assert REPL._save_plan_file(stub2) is None

    def test_saves_to_project_dir(self, tmp_path):
        """Plans are saved to project-scoped directory."""
        from hooty.repl import REPL

        config = AppConfig()
        config.working_directory = str(tmp_path)
        stub = MagicMock()
        stub._last_response_text = "# Plan"
        stub.config = config
        stub.session_id = "test-session"
        stub.pending_plan_ref = [None]
        result = REPL._save_plan_file(stub)
        assert result is not None
        assert "projects" in result
        assert "plans" in result
